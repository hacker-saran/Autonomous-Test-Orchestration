"""Loads .env into a typed Settings object. Nothing else in the codebase should
call os.environ directly for pipeline configuration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    sarvam_api_key: str
    sarvam_base_url: str
    sarvam_model_primary: str
    sarvam_model_fallback: str
    crawl_max_depth: int
    crawl_max_pages: int
    crawl_timeout_s: int
    max_replan_iterations: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        sarvam_api_key=os.environ.get("SARVAM_API_KEY", ""),
        sarvam_base_url=os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai/v2"),
        sarvam_model_primary=os.environ.get("SARVAM_MODEL_PRIMARY", "glm-5.2"),
        sarvam_model_fallback=os.environ.get("SARVAM_MODEL_FALLBACK", "sarvam-105b"),
        crawl_max_depth=int(os.environ.get("CRAWL_MAX_DEPTH", "3")),
        crawl_max_pages=int(os.environ.get("CRAWL_MAX_PAGES", "20")),
        crawl_timeout_s=int(os.environ.get("CRAWL_TIMEOUT_S", "90")),
        max_replan_iterations=int(os.environ.get("MAX_REPLAN_ITERATIONS", "2")),
    )
