"""Live, read-only source audit. Never modifies the public feed or sends FCM.

Run: python -m jobs.audit_sources --output .tmp/jobs-source-audit.json
An HTTP success, a parsable feed and a currently eligible vacancy are reported separately.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .collector.main import ROOT, load, save
from .collector.model import deduplicate, expired, iso, make_job, relevant
from .collector.network import Fetcher
from .collector.parsers import parse


def audit_source(source, config, keywords, now):
    result = dict(name=source["name"], url=source["url"], enabled=source.get("enabled", False),
                  status="failed", pages=0, records=0, relevant=0, eligible=0, countries={})
    fetch = Fetcher(source, min(24, int(source.get("maxRequestsPerSource",
                                                  config.get("maxRequestsPerSource", 12)))),
                    source.get("maxResponseBytes", config.get("maxResponseBytes", 2000000)))
    try:
        queue, visited, jobs = [source["url"]], set(), []
        while queue and fetch.remaining > 1:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            status, body = fetch.request(url)
            if status != 200:
                raise ValueError("Source page unavailable")
            records, links = parse(body, url, source)
            result["pages"] += 1
            result["records"] += len(records)
            queue.extend(links[:config.get("maxRequestsPerSource", 12)])
            for row in records:
                if relevant(str(row.get("title", "")) + " " + str(row.get("category", "")), keywords):
                    result["relevant"] += 1
                    job = make_job(row, source, now)
                    if not expired(job, now, config.get("expiryDays", 45)):
                        jobs.append(job)
        if not result["pages"]:
            raise ValueError("No source page read")
        jobs = deduplicate(jobs)
        result.update(status="partial" if queue else "parsed", eligible=len(jobs),
                      countries=dict(sorted(Counter(j["country"] or "Unknown" for j in jobs).items())))
    except Exception as error:
        # No response body, filename, credentials or personal data in the audit.
        result["errorType"] = type(error).__name__
    finally:
        fetch.session.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "jobs/config/sources.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-disabled", action="store_true")
    args = parser.parse_args()
    config = load(args.config, {})
    keywords = load(ROOT / "jobs/config/keywords.json", {})
    now = datetime.now(timezone.utc)
    results = []
    for source in config.get("sources", []):
        if not source.get("enabled") and not args.include_disabled:
            continue
        result = audit_source(source, config, keywords, now)
        results.append(result)
        print(f"{result['name']}: {result['status']}; {result['eligible']} eligible", flush=True)
        save(args.output, dict(checkedAt=iso(now), sourcesTested=len(results),
                              parsed=sum(r["status"] == "parsed" for r in results),
                              withEligibleJobs=sum(r["eligible"] > 0 for r in results), sources=results))


if __name__ == "__main__":
    main()
