"""FCM HTTP v1. Reserve a batch in git BEFORE sending it (at-most-once attempts)."""

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from .main import ROOT, load, save
from .model import expired

BATCH = ROOT / "jobs/notification.json"

COUNTRY_CODES = {
    "united arab emirates": "ae", "uae": "ae", "saudi arabia": "sa",
    "qatar": "qa", "kuwait": "kw", "bahrain": "bh", "oman": "om",
    "egypt": "eg", "jordan": "jo", "iraq": "iq", "lebanon": "lb",
    "united kingdom": "gb", "uk": "gb", "ireland": "ie",
    "united states": "us", "usa": "us", "canada": "ca", "australia": "au",
    "new zealand": "nz", "south africa": "za", "india": "in",
    "pakistan": "pk", "bangladesh": "bd", "philippines": "ph",
    "malaysia": "my", "singapore": "sg", "indonesia": "id",
    "poland": "pl", "ukraine": "ua", "slovakia": "sk",
    "bosnia and herzegovina": "ba", "north macedonia": "mk",
}


def country_code(country):
    value = str(country or "").strip()
    if re.fullmatch(r"[A-Za-z]{2}", value):
        return value.lower()
    return COUNTRY_CODES.get(value.casefold())


def fcm_payload(group):
    """Build one country-only FCM v1 message with a stable reporting label."""
    return {
        "message": {
            "topic": "survey_jobs_" + group["countryCode"],
            "data": {
                "destination": "survey_jobs",
                "jobs_count": str(len(group["ids"])),
                "jobs_batch": group["id"],
                "jobs_country": group["country"],
                "job_id": group["ids"][0] if len(group["ids"]) == 1 else "",
            },
            "android": {"priority": "high", "ttl": "86400s"},
            "fcm_options": {"analytics_label": "survey_jobs_country"},
        }
    }


def reserve():
    state = load(ROOT / "jobs/state.json", {})
    notified = set(state.get("notified", []))
    jobs = load(ROOT / "public/jobs/jobs.json", {"jobs": []})["jobs"]
    now = datetime.now(timezone.utc)
    expiry_days = load(ROOT / "jobs/config/sources.json", {}).get("expiryDays", 45)
    pending_jobs = [
        j for j in jobs if j["id"] in state.get("pending", [])
        and j["id"] not in notified and not expired(j, now, expiry_days)
    ]
    groups = {}
    for job in pending_jobs:
        code = country_code(job.get("country"))
        if code:
            groups.setdefault(code, []).append(job)
    ids = sorted(j["id"] for values in groups.values() for j in values)
    batches = []
    for code, values in sorted(groups.items()):
        group_ids = sorted(j["id"] for j in values)
        batches.append(dict(
            id=hashlib.sha256((code + "|" + "|".join(group_ids)).encode()).hexdigest(),
            countryCode=code,
            country=values[0].get("country", ""),
            ids=group_ids,
        ))
    batch = dict(id=hashlib.sha256("|".join(ids).encode()).hexdigest(), ids=ids, batches=batches)
    save(BATCH, batch)
    if ids:
        state["notified"] = sorted(notified | set(ids))
        state["pending"] = sorted(set(state.get("pending", [])) - set(ids))
        save(ROOT / "jobs/state.json", state)
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"send={'true' if ids else 'false'}\n")


def send(test_topic=None, test_country=None):
    import google.auth.transport.requests
    from google.oauth2 import service_account
    import requests

    if test_topic is not None:
        # The manual test can NEVER address a normal country topic or a device token.
        if not re.fullmatch(r"surveyone_jobs_qa_[a-f0-9]{32}", test_topic):
            raise ValueError("Only an isolated random QA topic is allowed")
        if not re.fullmatch(r"[a-z]{2}", test_country or ""):
            raise ValueError("Select a two-letter country code")
        now = datetime.now(timezone.utc)
        expiry = load(ROOT / "jobs/config/sources.json", {}).get("expiryDays", 45)
        jobs = [j for j in load(ROOT / "public/jobs/jobs.json", {"jobs": []})["jobs"]
                if country_code(j.get("country")) == test_country and not expired(j, now, expiry)]
        if not jobs:
            raise ValueError("No active real job for the test country; no notification sent")
        job = jobs[0]
        group = dict(id="qa-" + test_topic.removeprefix("surveyone_jobs_qa_"),
                     ids=[job["id"]], countryCode=test_country, country=job["country"])
        batch = dict(ids=group["ids"], batches=[group])
    else:
        batch = load(BATCH, {"ids": [], "batches": []})
    if not batch["ids"]:
        return
    info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    project = info["project_id"]
    if not project.replace("-", "").isalnum():
        raise ValueError("Invalid project ID")
    sent = 0
    outcomes = []
    for group in batch.get("batches", []):
        payload = fcm_payload(group)
        if test_topic:
            payload["message"]["topic"] = test_topic
            payload["message"]["fcm_options"]["analytics_label"] = "survey_jobs_qa"
        outcome = dict(countryCode=group["countryCode"], jobCount=len(group["ids"]), status="unknown")
        try:
            response = requests.post(
                f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
                json=payload,
                headers={"Authorization": "Bearer " + credentials.token},
                timeout=30,
            )
            outcome["httpStatus"] = response.status_code
            if response.status_code == 200:
                outcome["status"] = "accepted_by_fcm"
                sent += 1
            else:
                outcome["status"] = "rejected_by_fcm"
        except requests.RequestException:
            # An ambiguous delivery is never retried automatically (prevents notification spam).
            outcome["status"] = "delivery_unknown_network_error"
        outcomes.append(outcome)
        save(ROOT / "jobs/notification-delivery.json", dict(test=bool(test_topic), outcomes=outcomes,
             note="FCM acceptance is not proof of device delivery. No credentials or tokens stored."))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as report:
            report.write("\n## Jobs notification delivery\n\n")
            for result in outcomes:
                report.write(f"- {result['countryCode']}: {result['jobCount']} job(s), {result['status']}\n")
            report.write("\nFCM acceptance does not prove receipt on a phone.\n")
    print(f"{sent} country-targeted jobs notification batch(es) accepted by FCM")
    if sent != len(outcomes):
        raise RuntimeError("Some notification requests failed; inspect the redacted delivery report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["reserve", "send", "test"])
    parser.add_argument("--topic")
    parser.add_argument("--country")
    args = parser.parse_args()
    if args.action == "reserve":
        reserve()
    elif args.action == "test":
        if not args.topic or not args.country:
            parser.error("Test requires an isolated QA topic and country")
        send(args.topic, args.country)
    else:
        send()
