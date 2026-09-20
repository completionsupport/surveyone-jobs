import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


COUNTRY_ALIASES = {
    "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates",
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "sa": "Saudi Arabia", "saudi": "Saudi Arabia", "saudi arabia": "Saudi Arabia",
    "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia",
    "qatar": "Qatar", "doha": "Qatar", "kuwait": "Kuwait", "bahrain": "Bahrain",
    "oman": "Oman", "muscat": "Oman", "egypt": "Egypt", "cairo": "Egypt",
    "jordan": "Jordan", "iraq": "Iraq", "lebanon": "Lebanon",
    "united states": "United States", "usa": "United States", "us": "United States",
    "canada": "Canada", "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "ireland": "Ireland", "australia": "Australia", "new zealand": "New Zealand",
    "south africa": "South Africa", "india": "India", "pakistan": "Pakistan",
    "bangladesh": "Bangladesh", "philippines": "Philippines", "malaysia": "Malaysia",
    "singapore": "Singapore", "indonesia": "Indonesia",
}

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
CANADA_CODES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}


def infer_country(location):
    """Infer a notification country only when the location contains strong evidence.

    Region-only values such as Worldwide, APAC or Europe intentionally return an empty value,
    because broadcasting them to one country would be misleading.
    """
    text = str(location or "").strip()
    folded = normalize(text)
    for alias, country in COUNTRY_ALIASES.items():
        if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", folded):
            return country
    tokens = {token.upper() for token in re.findall(r"\b[A-Za-z]{2}\b", text)}
    if tokens & US_STATE_CODES:
        return "United States"
    if tokens & CANADA_CODES:
        return "Canada"
    return ""


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
        (("quantity surveyor", "cost surveyor"), "Quantity Surveying"),
        (("building surveyor", "fire surveyor"), "Building Surveying"),
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
    country = COUNTRY_ALIASES.get(country.casefold(), country)
    if not country:
        country = infer_country(location)
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
        description=BeautifulText(raw.get("description", ""))[:4000],
        employmentType=BeautifulText(raw.get("employmentType", ""))[:80],
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
    # First collapse exact application URLs after removing tracking parameters. Then merge
    # cross-postings only when their stable fields match and their descriptions are strongly
    # similar. Distinct requisition URLs without that evidence deliberately remain separate.
    result = {}
    semantic = []
    for job in jobs:
        url_key = normalize_url(job["applyUrl"])
        if url_key in result:
            continue
        company = normalize(job.get("company"))
        title = normalize(job.get("title"))
        country = normalize(job.get("country"))
        city = normalize(job.get("city") or job.get("location"))
        description = normalize(job.get("description"))
        posted = date(job.get("postedAt"))
        duplicate = False
        if description:
            for previous in semantic:
                if (company, title, country, city) != previous[:4]:
                    continue
                previous_posted, previous_description = previous[4], previous[5]
                if posted and previous_posted and abs((posted - previous_posted).days) > 3:
                    continue
                if SequenceMatcher(None, description[:2000], previous_description[:2000]).ratio() >= 0.90:
                    duplicate = True
                    break
        if duplicate:
            continue
        result[url_key] = job
        if description:
            semantic.append((company, title, country, city, posted, description))
    return list(result.values())
