"""Publish admin vacancies without scraping employers or sending notifications."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .editorial import load_editorial, replace_editorial
from .main import ROOT, load, save
from .model import date, iso
from .countries import published_job
from .taxonomy import filter_job

# The already-published Android client accepts at most 4 MiB and 10,000 rows.
MAX_FEED_BYTES = 4 * 1024 * 1024


def sync(output_root=None):
    root = Path(output_root) if output_root is not None else ROOT
    feedpath, statepath = root / "public/jobs/jobs.json", root / "jobs/state.json"
    if not feedpath.is_file() or feedpath.stat().st_size > MAX_FEED_BYTES:
        raise ValueError("A valid existing app feed is required")
    old = load(feedpath, {})
    if (not isinstance(old, dict) or old.get("version") != 1
            or not isinstance(old.get("jobs"), list) or len(old["jobs"]) > 10000
            or old.get("totalJobs") != len(old["jobs"])
            or any(not isinstance(j, dict) or not isinstance(j.get("id"), str) or not j["id"] for j in old["jobs"])):
        raise ValueError("The existing app feed is malformed; nothing was changed")
    state = load(statepath, {})
    if not isinstance(state, dict):
        raise ValueError("Collector state is malformed; nothing was changed")
    now = datetime.now(timezone.utc)
    config = load(ROOT / "jobs/config/sources.json", {})
    jobs, health = load_editorial(config, now)
    # Match the full collector: a withdrawn/expired/unavailable admin entry must
    # not be resurrected from a cached phone number. Employer rows stay intact.
    active = [published_job(filter_job(job)) for job in replace_editorial(old["jobs"], jobs)]
    active.sort(key=lambda j: date(j.get("postedAt")) or date(j.get("discoveredAt"))
                or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    changed = active != old["jobs"]
    result = {**old, "totalJobs": len(active), "jobs": active}
    if changed:
        result["generatedAt"] = iso(now)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if len(active) > 10000 or len(encoded.encode("utf-8")) > MAX_FEED_BYTES:
        raise ValueError("Merged feed exceeds the published app limits; nothing was changed")
    state["editorialFeed"] = dict(checkedAt=iso(now), **health)
    if changed:
        save(feedpath, result)
    # Never enqueue jobs or change seen/pending/notified/delivery reservations.
    save(statepath, state)
    summary = dict(mode="editorial_only", changed=changed, totalJobs=len(active),
                   editorialFeedStatus=health["status"], editorialActiveJobs=len(jobs),
                   notificationsSent=False)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, help="Use an isolated feed and state for verification")
    sync(parser.parse_args().output_root)
