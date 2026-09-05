"""Loads .env into a typed Settings object. Nothing else in the codebase should
call os.environ directly for pipeline configuration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / ".env.local", override=True)  # gitignored local secrets win


@dataclass(frozen=True)
class Settings:
    # Provider-agnostic on purpose: the LLM client is a plain OpenAI-SDK-compatible
    # client (see llm/client.py), so these can point at Sarvam (the intended
    # production provider) or any other OpenAI-compatible endpoint (e.g. Claude's
    # or Gemini's compatibility layer) as a temporary stand-in — just env values,
    # no code changes either way.
    llm_api_key: str
    llm_base_url: str
    llm_model_primary: str
    llm_model_fallback: str
    crawl_max_depth: int
    crawl_max_pages: int
    crawl_timeout_s: int
    max_replan_iterations: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.sarvam.ai/v2"),
        llm_model_primary=os.environ.get("LLM_MODEL_PRIMARY", "glm-5.2"),
        llm_model_fallback=os.environ.get("LLM_MODEL_FALLBACK", "sarvam-105b"),
        crawl_max_depth=int(os.environ.get("CRAWL_MAX_DEPTH", "3")),
        crawl_max_pages=int(os.environ.get("CRAWL_MAX_PAGES", "20")),
        crawl_timeout_s=int(os.environ.get("CRAWL_TIMEOUT_S", "90")),
        max_replan_iterations=int(os.environ.get("MAX_REPLAN_ITERATIONS", "2")),
    )
