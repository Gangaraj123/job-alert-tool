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


def build_digest_html(jobs: list[dict], broken_companies: list[dict]) -> str:
    if not jobs and not broken_companies:
        return ""

    by_company: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_company[j["company_name"]].append(j)

    parts = [f"<h2>Daily Job Digest — {len(jobs)} new job(s)</h2>"]

    for company, company_jobs in sorted(by_company.items()):
        parts.append(f"<h3>{_escape(company)} ({len(company_jobs)})</h3><ul>")
        for j in company_jobs:
            location = f" — {_escape(j['location'])}" if j.get("location") else ""
            parts.append(
                f'<li><a href="{j["url"]}">{_escape(j["title"])}</a>{location}</li>'
            )
        parts.append("</ul>")

    if broken_companies:
        parts.append("<h3>⚠️ Broken fetchers</h3><ul>")
        for c in broken_companies:
            parts.append(f"<li><b>{_escape(c['name'])}</b>: {_escape(c.get('last_error') or 'unknown error')}</li>")
        parts.append("</ul>")

    return "\n".join(parts)


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_email_digest(html_body: str, job_count: int) -> bool:
    settings = load_settings()
    if not settings.gmail_address or not settings.gmail_app_password:
        logger.warning("Email not configured (GMAIL_ADDRESS/GMAIL_APP_PASSWORD missing); skipping send")
        return False

    to_addr = settings.digest_to_email or settings.gmail_address

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Alert Digest — {job_count} new job(s)"
    msg["From"] = settings.gmail_address
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
            server.login(settings.gmail_address, settings.gmail_app_password)
            server.sendmail(settings.gmail_address, [to_addr], msg.as_string())
        return True
    except Exception as e:
        logger.error("Failed to send digest email: %s", e)
        return False
