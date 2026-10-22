"""Builds the daily digest and emails it via Gmail SMTP.

No AI ranking — jobs are grouped by company in the order they were found,
listing everything that passed the keyword/location pre-filter in filters.py.
"""
from __future__ import annotations

import logging
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import load_settings

logger = logging.getLogger("job_alert.digest")


def build_digest_html(
    new_jobs: list[dict],
    open_jobs: list[dict],
    broken_companies: list[dict],
) -> str:
    """The digest goes out every day, so it always states the full picture:
    what turned up since yesterday, and everything still open underneath.
    A quiet day produces a short mail rather than no mail, which is the only
    way silence in the inbox reliably means "nothing open" instead of
    "the cron died three days ago"."""
    new_ids = {j["id"] for j in new_jobs}
    standing = [j for j in open_jobs if j["id"] not in new_ids]

    if new_jobs:
        headline = f"{len(new_jobs)} new job(s)"
    elif standing:
        headline = "No new jobs today"
    else:
        headline = "No open jobs"
    parts = [f"<h2>Daily Job Digest — {headline}</h2>"]

    if new_jobs:
        parts.append("<h3>🆕 New since yesterday</h3>")
        parts.append(_render_groups(new_jobs))

    if standing:
        parts.append(f"<h3>Still open ({len(standing)})</h3>")
        parts.append(_render_groups(standing))

    if not new_jobs and not standing:
        parts.append(
            "<p>Nothing matching your filters is open right now. "
            "The scan ran fine — there is just nothing to show.</p>"
        )

    settings = load_settings()
    if settings.app_url:
        parts.append(
            f'<p style="margin-top:20px">'
            f'<a href="{settings.app_url}">Open the dashboard</a> — '
            f'every job found so far, mark them done, edit your company list.'
            f'</p>'
        )

    if broken_companies:
        parts.append("<h3>⚠️ Broken fetchers</h3><ul>")
        for c in broken_companies:
            parts.append(
                f"<li><b>{_escape(c['name'])}</b>: "
                f"{_escape(c.get('last_error') or 'unknown error')}</li>"
            )
        parts.append("</ul>")

    return "\n".join(parts)


def _render_groups(jobs: list[dict]) -> str:
    by_company: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_company[j["company_name"]].append(j)

    parts = []
    for company, company_jobs in sorted(by_company.items()):
        parts.append(f"<h4>{_escape(company)} ({len(company_jobs)})</h4><ul>")
        for j in company_jobs:
            location = f" — {_escape(j['location'])}" if j.get("location") else ""
            parts.append(
                f'<li><a href="{j["url"]}">{_escape(j["title"])}</a>{location}</li>'
            )
        parts.append("</ul>")
    return "\n".join(parts)


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _send(subject: str, html_body: str) -> bool:
    settings = load_settings()
    if not settings.gmail_address or not settings.gmail_app_password:
        logger.warning("Email not configured (GMAIL_ADDRESS/GMAIL_APP_PASSWORD missing); skipping send")
        return False

    # DIGEST_TO_EMAIL may list several addresses, comma- or semicolon-separated.
    raw = settings.digest_to_email or settings.gmail_address
    recipients = [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]
    if not recipients:
        logger.warning("No digest recipient configured; skipping send")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
            server.login(settings.gmail_address, settings.gmail_app_password)
            server.sendmail(settings.gmail_address, recipients, msg.as_string())
        logger.info("Digest sent to %d recipient(s)", len(recipients))
        return True
    except Exception as e:
        logger.error("Failed to send email (%s): %s", subject, e)
        return False


def send_email_digest(html_body: str, new_count: int, open_count: int) -> bool:
    """Subject line leads with whatever matters most that day, so the
    inbox is scannable without opening anything."""
    if new_count:
        subject = f"Job Alert — {new_count} new"
    elif open_count:
        subject = f"Job Alert — no new, {open_count} still open"
    else:
        subject = "Job Alert — nothing open"
    return _send(subject, html_body)


def send_ai_limit_alert(reason: str) -> bool:
    body = (
        f"<p>The job-alert-tool's AI usage hit a limit and is falling back to "
        f"non-AI behavior (pattern-guessing for discovery, structured-data-only "
        f"for fetching) until it resets.</p><p><b>Reason:</b> {_escape(reason)}</p>"
    )
    return _send("Job Alert Tool — AI limit reached", body)
