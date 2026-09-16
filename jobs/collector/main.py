import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from .model import make_job, relevant, expired, deduplicate, date, iso
from .network import Fetcher
from .parsers import parse

ROOT = Path(__file__).resolve().parents[2]


def load(path, fallback):
    return json.loads(path.read_text("utf-8")) if path.exists() else fallback


def save(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text("utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, "utf-8")
    temp.replace(path)


def collect():
    now = datetime.now(timezone.utc)
    config = load(ROOT / "jobs/config/sources.json", {})
    keywords = load(ROOT / "jobs/config/keywords.json", {})
    feedpath, statepath = ROOT / "public/jobs/jobs.json", ROOT / "jobs/state.json"
    old = load(
        feedpath, {"version": 1, "generatedAt": None, "totalJobs": 0, "jobs": []}
    )
    state = load(
        statepath, {"seen": [], "notified": [], "pending": [], "linkChecks": {}}
    )
    previous = {j["id"]: j for j in old["jobs"]}
    first_discovered = state.setdefault("firstDiscovered", {})
    for job in previous.values():
        first_discovered.setdefault(job["id"], job["discoveredAt"])
    merged = dict(previous)
    successes = failures = checked = 0
    dead = set()
    checks = state.setdefault("linkChecks", {})
    link_budget = config.get("checkLinksPerRun", 8)
    for source in config.get("sources", []):
        if not source.get("enabled"):
            continue
        checked += 1
        try:
            fetch = Fetcher(
                source,
                config.get("maxRequestsPerSource", 12),
                config.get("maxResponseBytes", 2000000),
            )
            queue, visited = [source["url"]], set()
            while queue and fetch.remaining > 1:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                status, body = fetch.request(url)
                if status in (404, 410):
                    continue
                records, links = parse(body, url, source)
                queue.extend(links[: config.get("maxRequestsPerSource", 12)])
                for raw in records:
                    if not relevant(
                        str(raw.get("title", "")) + " " + str(raw.get("category", "")),
                        keywords,
                    ):
                        continue
                    try:
                        job = make_job(raw, source, now)
                    except (ValueError, TypeError):
                        continue
                    job["discoveredAt"] = first_discovered.setdefault(
                        job["id"], job["discoveredAt"]
                    )
                    merged[job["id"]] = job
            for job in sorted(previous.values(), key=lambda j: checks.get(j["id"], "")):
                if link_budget <= 0 or fetch.remaining <= 1:
                    break
                if job["sourceUrl"] != source["url"]:
                    continue
                last = date(checks.get(job["id"]))
                if last and (now - last).days < 7:
                    continue
                status, _ = fetch.request(job["applyUrl"])
                checks[job["id"]] = iso(now)
                link_budget -= 1
                if status in (404, 410):
                    dead.add(job["id"])
            successes += 1
        except Exception as error:
            failures += 1
            print(
                f"Source {source.get('name', 'unnamed')}: {type(error).__name__}; retained cached jobs"
            )
    active = deduplicate(
        [
            j
            for j in merged.values()
            if j["id"] not in dead and not expired(j, now, config.get("expiryDays", 45))
        ]
    )
    active.sort(
        key=lambda j: date(j.get("postedAt")) or date(j["discoveredAt"]), reverse=True
    )
    seen = set(state.get("seen", [])) | set(previous)
    new = [j["id"] for j in active if j["id"] not in seen]
    state["seen"] = sorted(seen | {j["id"] for j in active})
    state["pending"] = sorted(
        (set(state.get("pending", [])) | set(new)) - set(state.get("notified", []))
    )
    expiry_days = config.get("expiryDays", 45)
    if (
        active != old["jobs"]
        or old.get("expiryDays", 45) != expiry_days
        or not feedpath.exists()
    ):
        save(
            feedpath,
            dict(
                version=1,
                generatedAt=iso(now),
                expiryDays=expiry_days,
                totalJobs=len(active),
                jobs=active,
            ),
        )
    save(statepath, state)
    summary = dict(
        sourcesChecked=checked,
        successful=successes,
        failed=failures,
        newJobs=len(new),
        updatedJobs=sum(j["id"] in previous and j != previous[j["id"]] for j in active),
        expiredJobs=len(set(previous) - {j["id"] for j in active}),
        totalActiveJobs=len(active),
    )
    print(json.dumps(summary, indent=2))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(
                "## Survey Jobs\n\n"
                + "\n".join(f"- {k}: {v}" for k, v in summary.items())
                + "\n"
            )


if __name__ == "__main__":
    collect()
