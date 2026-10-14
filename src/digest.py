"""Builds the daily digest message and sends it via Telegram, chunked to
respect Telegram's 4096-char message limit."""
from __future__ import annotations

import logging

import requests

from .config import load_settings

logger = logging.getLogger("job_alert.digest")

TELEGRAM_MAX_CHARS = 4096
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
PRIORITY_EMOJI = {"high": "\U0001F7E2", "medium": "\U0001F7E1", "low": "\U000026AA"}


def build_digest_text(jobs: list[dict], broken_companies: list[dict]) -> str:
    if not jobs and not broken_companies:
        return ""

    lines = ["*Daily Job Digest*", ""]

    jobs_sorted = sorted(
        jobs,
        key=lambda j: (PRIORITY_ORDER.get(j.get("priority", "low"), 2), -(j.get("fit_score") or 0)),
    )

    by_priority: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}
    for j in jobs_sorted:
        by_priority.setdefault(j.get("priority", "low"), []).append(j)

    for priority in ("high", "medium", "low"):
        group = by_priority.get(priority, [])
        if not group:
            continue
        emoji = PRIORITY_EMOJI.get(priority, "")
        lines.append(f"{emoji} *{priority.upper()} PRIORITY* ({len(group)})")
        for j in group:
            lines.append(
                f"• [{_escape(j['title'])} @ {_escape(j['company_name'])}]({j['url']}) "
                f"— score {j.get('fit_score')}"
            )
            if j.get("why_it_fits"):
                lines.append(f"  _{_escape(j['why_it_fits'])}_")
            if j.get("red_flags"):
                lines.append(f"  ⚠️ {_escape(j['red_flags'])}")
        lines.append("")

    if broken_companies:
        lines.append("⚠️ *Broken fetchers*")
        for c in broken_companies:
            lines.append(f"• {_escape(c['name'])}: {_escape(c.get('last_error') or 'unknown error')}")
        lines.append("")

    return "\n".join(lines).strip()


def _escape(text: str) -> str:
    # Minimal Markdown V1 escaping for Telegram (avoid breaking on literal _ * [ ])
    for ch in ("_", "*", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def _chunk_text(text: str, max_chars: int = TELEGRAM_MAX_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(text: str) -> bool:
    settings = load_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing); skipping send")
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    ok = True
    for chunk in _chunk_text(text):
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": chunk,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("Failed to send Telegram message chunk: %s", e)
            ok = False
    return ok
