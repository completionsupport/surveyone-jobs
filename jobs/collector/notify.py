"""FCM HTTP v1. Reserve a batch in git BEFORE sending it (at-most-once attempts)."""

import argparse
import hashlib
import json
import os
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
}


def country_code(country):
    value = str(country or "").strip()
    if len(value) == 2 and value.isalpha():
        return value.lower()
    return COUNTRY_CODES.get(value.casefold())


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


def send():
    import google.auth.transport.requests
    from google.oauth2 import service_account
    import requests

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
    for group in batch.get("batches", []):
        payload = {
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
            }
        }
        response = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
            json=payload,
            headers={"Authorization": "Bearer " + credentials.token},
            timeout=30,
        )
        # Do not print response bodies or credentials. Ambiguous delivery is not automatically retried.
        if response.status_code != 200:
            raise RuntimeError(f"FCM send failed: HTTP {response.status_code}")
        sent += 1
    print(f"{sent} country-targeted jobs notification batch(es) accepted by FCM")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["reserve", "send"])
    args = parser.parse_args()
    reserve() if args.action == "reserve" else send()
