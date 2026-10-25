"""Authoritative admin jobs overlay, separate from scraper cache and automatic FCM.

Editorial entries fail closed when disabled/unavailable: a cached copy must never
restore a withdrawn job or its contact number. Ordinary source jobs are unaffected.
"""

import json
import os
import re
from urllib.parse import urlsplit
from .model import date, iso
from .network import Fetcher

MAX_JOBS = 1000
MAX_BYTES = 16000000
ID = re.compile(r"editorial_[a-f0-9]{32}")
PHONE = re.compile(r"\+[1-9][0-9]{6,14}")


def is_editorial(job):
    return job.get("origin") == "EDITORIAL" or str(job.get("id", "")).startswith("editorial_")


def public_url(value, required=False):
    if not value and not required:
        return ""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\]|%(?:0[ad]|00)", value, re.I):
        raise ValueError("Invalid editorial HTTPS URL")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host, re.I)
            or re.search(r"(?:^|\.)(?:localhost|local|internal|lan|home|test|invalid|example)$", host, re.I)):
        raise ValueError("Invalid editorial HTTPS URL")
    return value


def text(row, key, maximum, required=False):
    value = row.get(key, "")
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise ValueError("Invalid editorial text")
    if required and not value.strip():
        raise ValueError("Missing editorial text")
    return value.strip()


def parse_snapshot(payload, now):
    if (not isinstance(payload, dict) or payload.get("version") != 1 or payload.get("authoritative") is not True
            or payload.get("origin") != "EDITORIAL" or not isinstance(payload.get("jobs"), list)
            or len(payload["jobs"]) > MAX_JOBS or payload.get("totalJobs") != len(payload["jobs"])):
        raise ValueError("Incomplete editorial snapshot")
    generated = date(payload.get("generatedAt"))
    if not generated or not -300 <= (now - generated).total_seconds() <= 900:
        raise ValueError("Stale editorial snapshot")
    result = {}
    for raw in payload["jobs"]:
        if not isinstance(raw, dict) or raw.get("origin") != "EDITORIAL" or not ID.fullmatch(str(raw.get("id", ""))):
            raise ValueError("Invalid editorial identity")
        if type(raw.get("revision")) is not int or raw["revision"] < 1:
            raise ValueError("Invalid editorial revision")
        if "status" in raw and raw["status"] != "PUBLISHED":
            raise ValueError("Unpublished job in public snapshot")
        expires, posted, discovered = (date(raw.get(key)) for key in ("expiresAt", "postedAt", "discoveredAt"))
        if not expires or not posted or not discovered:
            raise ValueError("Missing editorial dates")
        phone = text(raw, "phoneE164", 16)
        if phone and not PHONE.fullmatch(phone):
            raise ValueError("Invalid editorial phone")
        call, whatsapp = raw.get("allowCall", False), raw.get("allowWhatsApp", False)
        if type(call) is not bool or type(whatsapp) is not bool:
            raise ValueError("Invalid editorial contact permission")
        external = public_url(raw.get("externalApplyUrl", ""))
        if (call or whatsapp) and not phone or not (phone and (call or whatsapp)) and not external:
            raise ValueError("Editorial job has no enabled contact method")
        code = text(raw, "countryCode", 2, True)
        if not re.fullmatch("[A-Z]{2}", code):
            raise ValueError("Invalid editorial country")
        row = {key: text(raw, key, maximum, required) for key, maximum, required in (
            ("title", 240, True), ("company", 160, True), ("country", 100, True), ("city", 100, False),
            ("category", 100, True), ("description", 4000, True), ("employmentType", 80, False), ("contactName", 100, False))}
        row.update(id=raw["id"], revision=raw["revision"], origin="EDITORIAL", countryCode=code,
                   location=", ".join(filter(None, [row["city"], row["country"]])), postedAt=iso(posted), discoveredAt=iso(discovered),
                   expiresAt=iso(expires), phoneE164=phone if call or whatsapp else "", allowCall=call, allowWhatsApp=whatsapp,
                   externalApplyUrl=external, source="SurveyOne", sourceUrl="https://surveyone.app/en/jobs/",
                   applyUrl="https://surveyone.app/en/job/?id=" + raw["id"], remote=False)
        # Stable IDs survive edits. A duplicate snapshot row cannot create a duplicate job.
        if raw["id"] not in result or raw["revision"] > result[raw["id"]]["revision"]:
            result[raw["id"]] = row
    return [job for job in result.values() if date(job["expiresAt"]) > now]


def load_editorial(config, now, fetcher_factory=Fetcher):
    setting = config.get("editorialFeed") or {}
    override = os.getenv("SURVEYONE_EDITORIAL_JOBS_FEED_URL", "").strip()
    if not override and (not isinstance(setting, dict) or setting.get("enabled") is not True):
        return [], {"status": "disabled", "activeJobs": 0}
    fetch = None
    try:
        url = public_url(override or setting.get("url", ""), required=True)
        parsed = urlsplit(url)
        if parsed.query or parsed.fragment:
            raise ValueError("Use the public feed endpoint without query parameters")
        fetch = fetcher_factory({"name": "SurveyOne editorial jobs", "url": url, "allowedHosts": [parsed.hostname]}, 4, MAX_BYTES)
        status, body = fetch.request(url)
        if status != 200:
            raise ValueError("Editorial feed unavailable")
        jobs = parse_snapshot(json.loads(body), now)
        return jobs, {"status": "healthy", "activeJobs": len(jobs)}
    except Exception as error:
        return [], {"status": "unavailable", "activeJobs": 0, "errorType": type(error).__name__}
    finally:
        session = getattr(fetch, "session", None)
        if session is not None:
            session.close()


def replace_editorial(previous, authoritative):
    """Never union old editorial records with a new snapshot, even an empty one."""
    result = {job["id"]: job for job in previous if not is_editorial(job)}
    for job in authoritative:
        result[job["id"]] = job
    return list(result.values())
