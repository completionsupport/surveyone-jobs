import argparse
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from .model import make_job, relevant, expired, deduplicate, date, iso
from .network import Fetcher
from .parsers import parse
from .registry import enabled_sources, rotated_sources, source_key

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


def collect(output_root=None):
    now = datetime.now(timezone.utc)
    config = load(ROOT / "jobs/config/sources.json", {})
    keywords = load(ROOT / "jobs/config/keywords.json", {})
    # Audit runs can keep all output/pending notifications separate from production.
    output_root = Path(output_root) if output_root is not None else ROOT
    feedpath, statepath = output_root / "public/jobs/jobs.json", output_root / "jobs/state.json"
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
    source_health = state.setdefault("sourceHealth", {})
    sources = enabled_sources(config)
    ordered = rotated_sources(sources, state.get("sourceCursor"))
    started = time.monotonic()
    run_seconds = max(60, min(1200, int(config.get("maxRunSeconds", 900))))
    source_limit = max(1, min(10000, int(config.get("maxSourcesPerRun", 100))))
    link_budget = config.get("checkLinksPerRun", 8)
    for source in ordered:
        previous_health = source_health.get(source.get("name", "unnamed"), {})
        last_success = date(previous_health.get("lastSuccess"))
        poll_hours = max(1, int(source.get("pollIntervalHours", 1)))
        if last_success and (now - last_success).total_seconds() < poll_hours * 3600:
            continue
        if checked >= source_limit or time.monotonic() - started >= run_seconds:
            break
        checked += 1
        state["sourceCursor"] = source_key(source)
        fetch = None
        try:
            fetch = Fetcher(
                source,
                config.get("maxRequestsPerSource", 12),
                source.get("maxResponseBytes", config.get("maxResponseBytes", 2000000)),
            )
            queue, visited = [source["url"]], set()
            pages = records_read = matched = 0
            while queue and fetch.remaining > 1:
                if time.monotonic() - started >= run_seconds:
                    break
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                status, body = fetch.request(url)
                if status in (404, 410):
                    if url == source["url"]:
                        raise ValueError("Source endpoint no longer exists")
                    continue
                records, links = parse(body, url, source)
                pages += 1
                records_read += len(records)
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
                    matched += 1
            if pages == 0:
                raise ValueError("No source page read")
            for job in sorted(previous.values(), key=lambda j: checks.get(j["id"], "")):
                if link_budget <= 0 or fetch.remaining <= 1 or time.monotonic() - started >= run_seconds:
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
            source_health[source["name"]] = dict(
                status="partial" if queue else "healthy",
                lastSuccess=previous_health.get("lastSuccess") if queue else iso(now),
                lastAttempt=iso(now),
                pages=pages, records=records_read, matchingRecords=matched,
                lastFailure=source_health.get(source["name"], {}).get("lastFailure"),
                consecutiveFailures=0,
            )
        except Exception as error:
            failures += 1
            source_health[source.get("name", "unnamed")] = dict(
                status="failed",
                lastSuccess=previous_health.get("lastSuccess"),
                lastFailure=iso(now),
                lastAttempt=iso(now),
                consecutiveFailures=int(previous_health.get("consecutiveFailures", 0)) + 1,
                errorType=type(error).__name__,
            )
            print(
                f"Source {source.get('name', 'unnamed')}: {type(error).__name__}; retained cached jobs"
            )
        finally:
            session = getattr(fetch, "session", None)
            if session is not None:
                session.close()
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
        configuredSources=len(config.get("sources", [])),
        enabledUniqueSources=len(sources),
        sourcesChecked=checked,
        successful=successes,
        failed=failures,
        newJobs=len(new),
        updatedJobs=sum(j["id"] in previous and j != previous[j["id"]] for j in active),
        expiredJobs=len(set(previous) - {j["id"] for j in active}),
        totalActiveJobs=len(active),
        healthySources=sum(source_health.get(s["name"], {}).get("status") == "healthy" for s in sources),
    )
    print(json.dumps(summary, indent=2))
    save(output_root / "jobs/last-run.json", dict(checkedAt=iso(now), **summary))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(
                "## Survey Jobs\n\n"
                + "\n".join(f"- {k}: {v}" for k, v in summary.items())
                + "\n"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, help="Isolate an audit feed and state; never sends FCM")
    args = parser.parse_args()
    collect(args.output_root)
