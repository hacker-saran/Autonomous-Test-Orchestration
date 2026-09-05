"""LLM client wrapper (defaults to Sarvam AI).

The target provider is OpenAI-compatible, so we use the `openai` SDK pointed
at its endpoint instead of hand-rolled HTTP. `LLM_BASE_URL`/`LLM_API_KEY`/
`LLM_MODEL_PRIMARY`/`LLM_MODEL_FALLBACK` default to Sarvam's endpoint and
models, but are plain config — pointing them at any other OpenAI-compatible
endpoint (e.g. Claude's or Gemini's compatibility layer, as a temporary
stand-in while waiting on Sarvam beta access) needs no code change. Every
agent that needs a structured LLM output goes through `call_structured()`
below — no agent talks to the provider's API directly.

Every structured output is forced through a single-tool call (never
prompt-and-hope JSON):
  1. One tool is defined from the target Pydantic model's JSON schema.
  2. The call forces that tool via `tool_choice`.
  3. The returned tool-call arguments are parsed as JSON and validated against
     the Pydantic model.
  4. On a validation error, the error text is appended to the conversation and
     the call is retried once more (max 2 attempts total against one model).
  5. If the primary model errors or is unavailable, the call is retried
     against LLM_MODEL_FALLBACK.
  6. If every attempt fails, a `SchemaValidationError` is raised. Callers
     (the orchestrator) must catch this and record it as an escalation — it
     must never crash the pipeline.

Note: reasoning models return chain-of-thought in a separate
`reasoning_content` field on the message, not `content`. This wrapper never
reads or surfaces that field. If a rationale is needed downstream (e.g. in the
final report), it must be an explicit field on the response model
(e.g. `HealerVerdict.rationale`) that the model fills in as part of its
structured tool call.
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


def _tool_name_for(response_model: type[BaseModel]) -> str:
    return f"emit_{response_model.__name__.lower()}"


def _build_tool(response_model: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _tool_name_for(response_model),
            "description": f"Emit a validated {response_model.__name__} payload.",
            "parameters": response_model.model_json_schema(),
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
    tool: dict[str, Any],
    tool_name: str,
    response_model: type[ModelT],
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
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": tool_name}},
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            last_error = "model returned no tool call"
            logger.warning(
                "call_structured: %s attempt %d/%d on %s: %s",
                response_model.__name__, attempt, _MAX_VALIDATION_ATTEMPTS, model_name, last_error,
            )
            messages.append({"role": "user", "content": f"You must call the {tool_name} tool. Retry."})
            continue

        call = tool_calls[0]
        try:
            parsed = _coerce_stringified_json(json.loads(call.function.arguments))
            return response_model.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            logger.warning(
                "call_structured: %s attempt %d/%d on %s failed validation: %s",
                response_model.__name__, attempt, _MAX_VALIDATION_ATTEMPTS, model_name, last_error,
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.function.name, "arguments": call.function.arguments},
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": f"Validation error, fix your arguments and retry: {exc}",
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
    """Call the configured LLM provider, forcing a single tool call shaped like
    `response_model`, validate the result, and return an instance of
    `response_model`.

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

    tool = _build_tool(response_model)
    tool_name = _tool_name_for(response_model)
    client = _client()

    last_api_error: Exception | None = None
    for model_name in models_to_try:
        for attempt in range(1, _MAX_API_ATTEMPTS_PER_MODEL + 1):
            try:
                return _call_with_validation_retry(
                    client, model_name, system_prompt, user_prompt, tool, tool_name, response_model
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
