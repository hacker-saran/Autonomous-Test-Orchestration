"""LLM client wrapper (defaults to Sarvam AI).

The target provider is OpenAI-compatible, so we use the `openai` SDK pointed
at its endpoint instead of hand-rolled HTTP. `LLM_BASE_URL`/`LLM_API_KEY`/
`LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK` default to Sarvam's endpoint and
models, but are plain config — pointing them at any other OpenAI-compatible
endpoint (e.g. Claude's or Gemini's compatibility layer, as a temporary
stand-in while waiting on Sarvam beta access) needs no code change. Every
agent that needs a structured LLM output goes through `call_structured()`
below — no agent talks to the provider's API directly.

Every structured output is forced through the provider's Structured Outputs
mode (never prompt-and-hope JSON, and no dependency on tool-calling support):
  1. The call sets `response_format={"type": "json_schema", "json_schema": {...}}`
     built from the target Pydantic model's JSON schema (non-strict — see
     `_build_response_format`).
  2. The model's reply text (`message.content`) is parsed as JSON and validated
     against the Pydantic model.
  3. On a validation error, the reply is appended to the conversation along
     with the error text, and the call is retried once more (max 2 attempts
     total against one model).
  4. Each model gets up to `_MAX_API_ATTEMPTS_PER_MODEL` attempts with a short
     backoff for a transient SDK/network error (a 400/5xx that clears up
     moments later on the exact same key/model — the openai SDK's own retry
     only covers 429/5xx) before falling back to LLM_MODEL_FALLBACK.
  5. If every attempt on every model fails, a `SchemaValidationError` is
     raised. Callers (the orchestrator) must catch this and record it as an
     escalation — it must never crash the pipeline.

We deliberately avoid tool calling here: some OpenAI-compatible providers
(e.g. Sarvam) don't reliably honor a forced `tool_choice`, or mis-serialize
nested objects/arrays inside tool-call arguments. `response_format` json_schema
mode asks the provider to constrain its own text generation to the schema
directly, which every provider we've targeted supports more reliably. As
cheap extra insurance, `_coerce_stringified_json` still recursively re-parses
any value that looks like JSON encoded as a string, in case a provider/gateway
does that even outside tool-calling (seen live on an OpenRouter-backed model
behind a TrueFoundry gateway, under the older tool-calling design this
replaced).

Note: reasoning models return chain-of-thought in a separate
`reasoning_content` field on the message, not `content`. This wrapper never
reads or surfaces that field. If a rationale is needed downstream (e.g. in the
final report), it must be an explicit field on the response model
(e.g. `HealerVerdict.rationale`) that the model fills in as part of its
structured JSON reply.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from orchestrator.config import get_settings

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

_MAX_VALIDATION_ATTEMPTS = 2
_MAX_TOKENS = 16384
# Transient provider-side hiccups (a 400/5xx that clears up moments later on
# the exact same key/model — auth-layer propagation delays, brief infra
# blips) get one same-model retry with a short backoff before we give up on
# that model. The openai SDK's own retry only covers 429/5xx; it does not
# retry 400s, which is exactly the error shape seen here.
_MAX_API_ATTEMPTS_PER_MODEL = 2
_API_RETRY_BACKOFF_S = 2.0


class SchemaValidationError(Exception):
    """Raised when a response_model could not be produced after all retries
    and model fallbacks. Callers must catch this and treat it as an
    escalation, never let it crash the pipeline.
    """


def _client() -> OpenAI:
    """Sarvam requires an extra `api-subscription-key` header alongside the
    Authorization header the openai SDK sends by default. Other OpenAI-compatible
    providers (e.g. swapping LLM_BASE_URL to Anthropic's or Gemini's compat
    endpoint while waiting on Sarvam beta access) don't need it, so it's only
    attached when actually talking to Sarvam.
    """
    settings = get_settings()
    default_headers = {}
    if "sarvam.ai" in settings.llm_base_url:
        default_headers["api-subscription-key"] = settings.llm_api_key

    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        default_headers=default_headers,
    )


def _build_response_format(response_model: type[BaseModel]) -> dict[str, Any]:
    """`strict: True` (OpenAI's stricter json_schema variant) additionally
    requires every property to be listed in `required` and
    `additionalProperties: false` throughout — Pydantic's `model_json_schema()`
    doesn't emit that for models with optional/defaulted fields (e.g. `Flow`),
    so we deliberately omit `strict` and rely on plain (non-strict) json_schema
    mode instead.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__,
            "schema": response_model.model_json_schema(),
        },
    }


def _coerce_stringified_json(value: Any) -> Any:
    """Some function-calling gateways/proxies (seen live: an OpenRouter-backed
    model via a TrueFoundry gateway) occasionally emit a nested object or
    array as a JSON-encoded *string* inside a tool call's arguments instead
    of a native structure — e.g. `{"flows": ["{\\"id\\": ...}", ...]}` instead
    of `{"flows": [{"id": ...}, ...]}`. Recursively re-parse any string that
    looks like embedded JSON so Pydantic validation sees real nested objects
    rather than failing with "should be a valid dictionary".
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "{[":
            try:
                return _coerce_stringified_json(json.loads(stripped))
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, list):
        return [_coerce_stringified_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _coerce_stringified_json(v) for k, v in value.items()}
    return value


def _call_with_validation_retry(
    client: OpenAI,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    response_format: dict[str, Any],
    response_model: type[ModelT],
    extra_body: dict[str, Any],
) -> ModelT:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: str | None = None

    for attempt in range(1, _MAX_VALIDATION_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format=response_format,
            max_tokens=_MAX_TOKENS,
            extra_body=extra_body,
        )
        message = response.choices[0].message
        content = message.content
        finish_reason = response.choices[0].finish_reason

        if finish_reason == "length":
            last_error = f"response truncated at max_tokens={_MAX_TOKENS} (finish_reason=length)"
            logger.warning(
                "call_structured: %s attempt %d/%d on %s: %s",
                response_model.__name__, attempt, _MAX_VALIDATION_ATTEMPTS, model_name, last_error,
            )
            messages.append({"role": "assistant", "content": content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your reply was cut off before finishing the JSON. Reply again with the "
                        "complete JSON payload only, more concisely if needed to fit."
                    ),
                }
            )
            continue

        if not content:
            last_error = "model returned no content"
            logger.warning(
                "call_structured: %s attempt %d/%d on %s: %s",
                response_model.__name__, attempt, _MAX_VALIDATION_ATTEMPTS, model_name, last_error,
            )
            messages.append({"role": "user", "content": "You must reply with the JSON payload. Retry."})
            continue

        try:
            # response_format/json_schema mode makes the model generate its own
            # reply text directly against the schema, so it's much less prone to
            # the stringified-nested-JSON issue tool-calling gateways can
            # introduce — but _coerce_stringified_json is cheap insurance in
            # case some provider/gateway does it here too.
            parsed = _coerce_stringified_json(json.loads(content))
            return response_model.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            logger.warning(
                "call_structured: %s attempt %d/%d on %s failed validation: %s",
                response_model.__name__, attempt, _MAX_VALIDATION_ATTEMPTS, model_name, last_error,
            )
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Validation error, fix your JSON and reply with the corrected payload only: {exc}",
                }
            )

    raise SchemaValidationError(
        f"{response_model.__name__} validation failed after {_MAX_VALIDATION_ATTEMPTS} attempts "
        f"on model {model_name}: {last_error}"
    )


def call_structured(
    system_prompt: str,
    user_prompt: str,
    response_model: type[ModelT],
    model: str | None = None,
) -> ModelT:
    """Call the configured LLM provider, constraining its reply to the JSON
    schema of `response_model` via `response_format`, validate the result, and
    return an instance of `response_model`.

    Tries `model` (or LLM_MODEL_PRIMARY if unset) first; if that model
    errors or is unavailable, retries against LLM_MODEL_FALLBACK. Schema
    validation failures on a given model are retried in-place (see
    `_call_with_validation_retry`) and are NOT treated as a reason to fall
    back to a different model.
    """
    settings = get_settings()
    primary = model or settings.llm_model_primary
    models_to_try = [primary]
    if settings.llm_model_fallback != primary:
        models_to_try.append(settings.llm_model_fallback)

    response_format = _build_response_format(response_model)
    client = _client()

    # Sarvam's reasoning models default to "thinking" mode, which spends
    # max_tokens on reasoning_content before ever writing to content -- for a
    # forced structured-extraction call we want the schema-conformant answer,
    # not chain-of-thought, so thinking is switched off for Sarvam specifically.
    extra_body: dict[str, Any] = {}
    if "sarvam.ai" in settings.llm_base_url:
        extra_body["reasoning_effort"] = None

    last_api_error: Exception | None = None
    for model_name in models_to_try:
        for attempt in range(1, _MAX_API_ATTEMPTS_PER_MODEL + 1):
            try:
                return _call_with_validation_retry(
                    client, model_name, system_prompt, user_prompt, response_format, response_model, extra_body
                )
            except SchemaValidationError:
                raise
            except Exception as exc:  # noqa: BLE001 - any SDK/network error triggers retry/fallback
                last_api_error = exc
                if attempt < _MAX_API_ATTEMPTS_PER_MODEL:
                    logger.warning(
                        "call_structured: model %s errored (attempt %d/%d), retrying in %.1fs: %s",
                        model_name, attempt, _MAX_API_ATTEMPTS_PER_MODEL, _API_RETRY_BACKOFF_S, exc,
                    )
                    time.sleep(_API_RETRY_BACKOFF_S)
                else:
                    logger.warning("call_structured: model %s errored, trying fallback: %s", model_name, exc)

    raise SchemaValidationError(
        f"All models {models_to_try} failed for {response_model.__name__}: {last_api_error}"
    )
