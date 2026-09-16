import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def normalize_url(url):
    p = urlsplit(url)
    if p.scheme.lower() != "https" or not p.hostname or p.username or p.password:
        raise ValueError("Only public HTTPS URLs are supported")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in ("gclid", "fbclid", "msclkid")
    ]
    return urlunsplit(
        ("https", p.netloc.lower(), p.path or "/", urlencode(sorted(query)), "")
    )


def date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            return None
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def relevant(title, keywords):
    title = normalize(title)

    def matches(word):
        return (
            re.search(r"(?<!\w)" + re.escape(normalize(word)) + r"(?!\w)", title)
            is not None
        )

    return not any(matches(x) for x in keywords["exclude"]) and any(
        matches(x) for x in keywords["include"]
    )


def category(title):
    title = normalize(title)
    for words, label in [
        (("lidar", "uav", "drone", "laser scanning"), "UAV / LiDAR"),
        (("hydrographic",), "Hydrographic"),
        (("utility", "gpr"), "Utility Survey"),
        (("gis", "geospatial", "geomatics"), "GIS / Geospatial"),
        (("engineer",), "Survey Engineering"),
    ]:
        if any(word in title for word in words):
            return label
    return "Land Surveying"


def make_job(raw, source, now):
    title = BeautifulText(raw.get("title", ""))[:240]
    company = BeautifulText(
        raw.get("company") or source.get("company") or source["name"]
    )[:160]
    location = BeautifulText(raw.get("location") or source.get("location", ""))[:200]
    country = str(raw.get("country") or source.get("country", ""))[:100]
    aliases = {
        "uae": "United Arab Emirates",
        "ae": "United Arab Emirates",
        "sa": "Saudi Arabia",
        "saudi": "Saudi Arabia",
        "qa": "Qatar",
        "eg": "Egypt",
        "kw": "Kuwait",
        "om": "Oman",
        "bh": "Bahrain",
    }
    country = aliases.get(country.casefold(), country)
    url = normalize_url(raw["applyUrl"])
    identity = "|".join(
        (normalize(company), normalize(title), normalize(location), url)
    )
    posted = date(raw.get("postedAt"))
    return dict(
        id=hashlib.sha256(identity.encode()).hexdigest(),
        title=title,
        company=company,
        location=location,
        city=str(raw.get("city", ""))[:100],
        country=country,
        category=category(title),
        postedAt=iso(posted) if posted else None,
        discoveredAt=iso(now),
        expiresAt=iso(date(raw["expiresAt"])) if date(raw.get("expiresAt")) else None,
        source=source["name"],
        sourceUrl=source["url"],
        applyUrl=url,
        remote=bool(raw.get("remote", False)),
    )


def BeautifulText(value):
    from bs4 import BeautifulSoup

    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def expired(job, now, days=45):
    until = date(job.get("expiresAt"))
    base = date(job.get("postedAt")) or date(job.get("discoveredAt")) or now
    return until <= now if until else base + timedelta(days=days) <= now


def deduplicate(jobs):
    # Do not collapse distinct requisitions with the same title/location. Tracking-only URL
    # differences normalize away; meaningful query IDs and paths stay distinct.
    result = {}
    for job in jobs:
        key = (
            normalize(job["company"]),
            normalize(job["title"]),
            normalize(job["location"]),
            normalize_url(job["applyUrl"]),
        )
        result.setdefault(key, job)
    return list(result.values())
