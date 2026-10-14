"""AI fit-scoring: for each new job, ask Claude how well it fits my profile.

profile.md is sent as a cached system block (cache_control: ephemeral) so it's
only billed as a fresh prompt-cache write once per 5-minute cache window, no
matter how many jobs are scored against it in the same run.
"""
from __future__ import annotations

import json
import logging
import re

import anthropic

from . import db
from .config import load_config, load_settings

logger = logging.getLogger("job_alert.scorer")

_cfg = load_config().get("scoring", {})
MODEL = _cfg.get("model", "claude-haiku-5-5")
MAX_TOKENS = _cfg.get("max_tokens", 1024)

RESPONSE_SCHEMA_PROMPT = """You are helping screen job postings against my profile (given above).
Given the job below, respond with ONLY a JSON object (no markdown fences, no
commentary) with exactly these keys:

{{
  "fit_score": <integer 0-100, how well this job fits my profile>,
  "why_it_fits": "<1-2 sentences>",
  "gaps": "<1-2 sentences on skill/experience gaps, or empty string if none>",
  "red_flags": "<1-2 sentences on concerns, or empty string if none>",
  "priority": "<one of: high, medium, low>"
}}

Job:
Company: {company}
Title: {title}
Location: {location}
URL: {url}
Description: {description}
"""


class ScoringError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    settings = load_settings()
    if not settings.anthropic_api_key:
        raise ScoringError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _parse_response(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)
    return {
        "fit_score": int(data.get("fit_score", 0)),
        "why_it_fits": str(data.get("why_it_fits", "")),
        "gaps": str(data.get("gaps", "")),
        "red_flags": str(data.get("red_flags", "")),
        "priority": str(data.get("priority", "low")).lower(),
    }


def score_job(job: dict, profile_text: str | None = None) -> dict:
    """Returns {fit_score, why_it_fits, gaps, red_flags, priority}."""
    profile_text = profile_text if profile_text is not None else db.get_profile()
    client = _client()

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": profile_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{
            "role": "user",
            "content": RESPONSE_SCHEMA_PROMPT.format(
                company=job.get("company", ""),
                title=job.get("title", ""),
                location=job.get("location") or "unspecified",
                url=job.get("url", ""),
                description=(job.get("description") or "")[:3000],
            ),
        }],
    )
    raw_text = "".join(block.text for block in message.content if block.type == "text")
    try:
        return _parse_response(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ScoringError(f"could not parse scoring response for job {job.get('id')}: {e}") from e


def score_jobs(jobs: list[dict]) -> list[tuple[dict, dict | None, str | None]]:
    """Scores each job, isolating failures. Returns list of
    (job, score_result_or_None, error_or_None)."""
    profile_text = db.get_profile()
    results = []
    for job in jobs:
        try:
            score = score_job(job, profile_text=profile_text)
            results.append((job, score, None))
        except Exception as e:
            logger.warning("Scoring failed for job %s (%s): %s", job.get("id"), job.get("title"), e)
            results.append((job, None, str(e)))
    return results
