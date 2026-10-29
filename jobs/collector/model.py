import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .countries import country_name


COUNTRY_ALIASES = {
    "eg": "Egypt", "مصر": "Egypt", "القاهرة": "Egypt",
    "السعودية": "Saudi Arabia", "المملكة العربية السعودية": "Saudi Arabia",
    "الرياض": "Saudi Arabia", "جدة": "Saudi Arabia",
    "ae": "United Arab Emirates", "الإمارات": "United Arab Emirates",
    "qa": "Qatar", "قطر": "Qatar", "kw": "Kuwait", "الكويت": "Kuwait",
    "bh": "Bahrain", "البحرين": "Bahrain", "om": "Oman", "سلطنة عمان": "Oman",
    "jo": "Jordan", "الأردن": "Jordan", "lb": "Lebanon", "لبنان": "Lebanon",
    "iq": "Iraq", "العراق": "Iraq",
    "are": "United Arab Emirates", "sau": "Saudi Arabia", "qat": "Qatar",
    "omn": "Oman", "bhr": "Bahrain", "kwt": "Kuwait", "egy": "Egypt",
    "jor": "Jordan", "lbn": "Lebanon", "irq": "Iraq",
    "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates",
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "sa": "Saudi Arabia", "ksa": "Saudi Arabia", "saudi": "Saudi Arabia", "saudi arabia": "Saudi Arabia",
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
    "ng": "Nigeria", "nga": "Nigeria", "nigeria": "Nigeria",
    "ke": "Kenya", "ken": "Kenya", "kenya": "Kenya",
    "pk": "Pakistan", "pak": "Pakistan",
    "za": "South Africa", "zaf": "South Africa",
    "ph": "Philippines", "phl": "Philippines",
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
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError("A bounded public HTTPS URL is required")
    p = urlsplit(url)
    if p.scheme.lower() != "https" or not p.hostname or p.username or p.password:
        raise ValueError("Only public HTTPS URLs are supported")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in ("gclid", "fbclid", "msclkid")
    ]
    # Dar Al Riyadh's public application uses a client-side job-details route.
    # Retain only this validated vacancy identifier; ordinary tracking fragments
    # still disappear and different jobs must never collapse to the board home.
    fragment = p.fragment if re.fullmatch(r"/JobDetails/\d+", p.fragment) else ""
    return urlunsplit(
        ("https", p.netloc.lower(), p.path or "/", urlencode(sorted(query)), fragment)
    )


def application_key(value):
    """Known public ATS aliases identify one requisition, not extra vacancies."""
    url = normalize_url(value)
    parsed = urlsplit(url)
    host = parsed.hostname
    if host == 'jobs.smartrecruiters.com':
        match = re.match(r'^/([^/]+)/(\d+)', parsed.path)
        if match:
            return 'smartrecruiters:' + match[1].casefold() + ':' + match[2]
    if host == 'apply.workable.com':
        match = re.search(r'/j/([a-f0-9]{10})(?:/|$)', parsed.path, re.I)
        if match:
            return 'workable:' + match[1].upper()
    if host in ('jobs.lever.co', 'jobs.eu.lever.co'):
        match = re.match(r'^/([^/]+)/([a-f0-9-]{36})(?:/apply)?/?$', parsed.path, re.I)
        if match:
            return 'lever:' + host + ':' + match[1].casefold() + ':' + match[2].casefold()
    if host in ('boards.greenhouse.io', 'job-boards.greenhouse.io'):
        match = re.match(r'^/([^/]+)/jobs/(\d+)', parsed.path)
        if match:
            return 'greenhouse:' + match[1].casefold() + ':' + match[2]
    return url


def date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            # Public career cards sometimes use an unambiguous written month.
            # Never interpret ambiguous numeric day/month dates as a new vacancy.
            result = None
            for pattern in ("%d %B %Y", "%d %b %Y"):
                try:
                    result = datetime.strptime(str(value).strip(), pattern)
                    break
                except ValueError:
                    continue
            if result is None:
                return None
    return (
        result.replace(tzinfo=timezone.utc)
        if result.tzinfo is None
        else result.astimezone(timezone.utc)
    )


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def quantity_surveying_role(title):
    """Commercial quantity surveying is distinct from field/land surveying."""
    value = normalize(title)
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = re.sub(r"[\W_]+", " ", value)
    return bool(re.search(r"\b(?:quantity|quantities|quntity|quanity|quantitiy|quanitity|qty|cost)\s+(?:surveyor\w*|surveying)\b|\bqs\b", value)
                or re.search(r"(?:حصر\s+(?:ال)?كميات|(?:حاسب|حساب|مساح|مساحين)\s+(?:ال)?(?:كميات|كمية))", value))


def excluded_role(title, keywords):
    title = normalize(title)
    if quantity_surveying_role(title):
        return True
    return any(re.search(r"(?<!\w)" + re.escape(normalize(word)) + r"(?!\w)", title)
               is not None for word in keywords["exclude"])


def relevant(title, keywords):
    title = normalize(title)
    return not excluded_role(title, keywords) and any(
        re.search(r"(?<!\w)" + re.escape(normalize(word)) + r"(?!\w)", title)
        is not None for word in keywords["include"]
    )


def category(title):
    title = normalize(title)
    for words, label in [
        (("quantity surveyor", "cost surveyor"), "Quantity Surveying"),
        (("building surveyor", "fire surveyor"), "Building Surveying"),
        (("lidar", "uav", "drone", "laser scanning"), "UAV / LiDAR"),
        (("hydrographic", "hydrographer", "hydrography"), "Hydrographic"),
        (("utility", "gpr"), "Utility Survey"),
        (("gis", "geospatial", "geomatics", "earth observation", "earth-observation", "remote sensing",
          "geodesy", "cartograph", "cartógrafo", "cartografo", "insar", "geographic information",
          "geographical information", "geoai", "geoinformatics", "mapping technician", "géomati", "geomati",
          "geodata", "kartingenjör", "kartograf", "arcgis", "qgis"), "GIS / Geospatial"),
        (("engineer",), "Survey Engineering"),
    ]:
        if any(word in title for word in words):
            return label
    return "GIS / Geospatial" if re.search(r"\bsig\b", title) else "Land Surveying"


def make_job(raw, source, now):
    title = BeautifulText(raw.get("title", ""))[:240]
    public_company = raw.get("company")
    if normalize(public_company) in ("company", "company name"):
        public_company = ""
    company = BeautifulText(public_company or source.get("company") or source["name"])[:160]
    location = BeautifulText(raw.get("location") or source.get("location", ""))[:200]
    country = str(raw.get("country") or source.get("country", ""))[:100]
    country = COUNTRY_ALIASES.get(country.casefold(), country)
    if not country:
        country = infer_country(location)
    if not country:
        # Employer-specific city labels must not become global country aliases
        # (for example, Alexandria also exists outside Egypt).
        country = source.get("locationCountryMap", {}).get(normalize(location), "")
    country = country_name(country)
    url = normalize_url(raw["applyUrl"])
    identity = "|".join(
        (normalize(company), normalize(title), normalize(location), url)
    )
    posted = date(raw.get("postedAt"))
    result = dict(
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
    if raw.get("canonicalApplyUrl"):
        try:
            result["canonicalApplyUrl"] = normalize_url(raw["canonicalApplyUrl"])
        except (ValueError, TypeError):
            pass
    return result


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
    semantic = {}
    for job in jobs:
        # One requisition can advertise multiple countries. Keep these distinct so
        # country-specific delivery does not silently discard Egypt or Saudi Arabia.
        # Some employers deliberately use one shared application form for several roles.
        # Keep distinct titles while still collapsing the same requisition/country/title.
        try:
            primary = application_key(job.get("canonicalApplyUrl") or job["applyUrl"])
        except (ValueError, TypeError):
            primary = application_key(job["applyUrl"])
        url_key = (primary, normalize(country_name(job.get("country"))),
                   normalize(job.get("title")))
        if url_key in result:
            continue
        company = normalize(job.get("company"))
        title = normalize(job.get("title"))
        country = normalize(country_name(job.get("country")))
        city = normalize(job.get("city") or job.get("location"))
        description = normalize(job.get("description"))
        posted = date(job.get("postedAt"))
        duplicate = False
        if description:
            for previous_posted, previous_description in semantic.get((company, title, country, city), []):
                if posted and previous_posted and abs((posted - previous_posted).days) > 3:
                    continue
                if SequenceMatcher(None, description[:2000], previous_description[:2000]).ratio() >= 0.90:
                    duplicate = True
                    break
        if duplicate:
            continue
        result[url_key] = job
        if description:
            semantic.setdefault((company, title, country, city), []).append((posted, description))
    return list(result.values())
