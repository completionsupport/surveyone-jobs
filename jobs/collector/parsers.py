"""Parsers return metadata only. Site selectors live entirely in configuration."""

import json
import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup


def jsonld(text, url):
    soup = BeautifulSoup(text, "html.parser")
    found = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            if "JobPosting" in ([kind] if isinstance(kind, str) else kind):
                locations = value.get("jobLocation", [])
                if not isinstance(locations, list):
                    locations = [locations]
                for location in locations or [{}]:
                    address = (
                        location.get("address", {})
                        if isinstance(location, dict)
                        else {}
                    )
                    if not isinstance(address, dict):
                        address = {}
                    country = address.get("addressCountry", "")
                    if isinstance(country, dict):
                        country = country.get("name", "")
                    org = value.get("hiringOrganization", {})
                    found.append(
                        dict(
                            title=value.get("title", ""),
                            company=(
                                org.get("name", "") if isinstance(org, dict) else ""
                            ),
                            city=address.get("addressLocality", ""),
                            country=country,
                            location=", ".join(
                                str(x)
                                for x in (address.get("addressLocality"), country)
                                if x
                            ),
                            category=value.get("occupationalCategory", ""),
                            postedAt=value.get("datePosted"),
                            expiresAt=value.get("validThrough"),
                            applyUrl=urljoin(url, value.get("url") or url),
                            remote=value.get("jobLocationType") == "TELECOMMUTE",
                        )
                    )
            if "@graph" in value:
                visit(value["@graph"])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue
    return found


def xml_root(text):
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML entities are unsupported")
    return ET.fromstring(text)


def rss(text, url):
    root = xml_root(text)
    jobs = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        values = {}
        for child in item:
            tag = child.tag.split("}")[-1]
            if tag == "link":
                if child.attrib.get("rel", "alternate") == "alternate":
                    values["applyUrl"] = urljoin(
                        url, child.attrib.get("href") or child.text or ""
                    )
            elif tag in ("description", "summary", "encoded"):
                if child.text and not values.get("description"):
                    values["description"] = child.text
            elif tag in ("title", "pubDate", "published", "updated"):
                if tag != "updated" or not values.get("postedAt"):
                    values["title" if tag == "title" else "postedAt"] = child.text or ""
        if values.get("title") and values.get("applyUrl"):
            description = values.get("description", "")

            def labelled(name):
                match = re.search(
                    r"\*\*" + re.escape(name) + r":\*\*\s*([^\r\n<]+)",
                    description,
                    re.IGNORECASE,
                )
                return match.group(1).strip(" \t|,") if match else ""

            city, country = labelled("City"), labelled("Country")
            primary = labelled("Primary Location")
            if primary and not country:
                parts = [part.strip() for part in primary.split("|") if part.strip()]
                if parts:
                    country = parts[0]
                    city = parts[-1] if len(parts) > 1 else ""
            location = ", ".join(value for value in (city, country) if value)
            if not location and primary:
                location = primary.replace(" | ", ", ")
            values.update(
                city=city,
                country=country,
                location=location,
                category=labelled("Job Category"),
            )
            jobs.append(values)
    return jobs


def oracle(text, url, source):
    """Parse Oracle Recruiting Candidate Experience's public requisition feed."""
    payload = json.loads(text)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    root = items[0] if items and isinstance(items[0], dict) else {}
    postings = root.get("requisitionList", [])
    total = root.get("TotalJobsCount")
    if not isinstance(postings, list) or not isinstance(total, int):
        raise ValueError("Invalid Oracle public careers feed")
    public_base = str(source.get("publicBaseUrl", "")).rstrip("/")
    if (not public_base.startswith("https://") or
            urlsplit(public_base).hostname != urlsplit(source["url"]).hostname):
        raise ValueError("Missing Oracle public career URL")
    found = []
    for job in postings:
        if not isinstance(job, dict):
            continue
        job_id, title = job.get("Id"), job.get("Title")
        if not job_id or not title:
            continue
        location = str(job.get("PrimaryLocation", "")).strip()
        country = str(job.get("PrimaryLocationCountry", "")).strip()
        found.append(dict(
            title=title,
            company=source.get("company", ""),
            location=location,
            city=location.split(",", 1)[0].strip(),
            country=country,
            postedAt=job.get("PostedDate"),
            expiresAt=job.get("PostingEndDate"),
            applyUrl=f"{public_base}/job/{job_id}",
        ))

    query = parse_qs(urlsplit(url).query)
    finder = str(query.get("finder", [""])[0])
    term_match = re.search(r"(?:^|,)keyword=([^,]*)$", finder)
    offset_match = re.search(r"(?:^|,)offset=(\d+)(?:,|$)", finder)
    if not term_match or not offset_match:
        raise ValueError("Invalid Oracle response URL")
    term, offset = unquote(term_match.group(1)), int(offset_match.group(1))
    terms = [str(value) for value in source.get("searchTerms", [])]
    if term not in terms or offset < 0 or offset % 25:
        raise ValueError("Unexpected Oracle search request")
    max_pages = max(1, min(4, int(source.get("maxPagesPerTerm", 2))))
    site_number = str(source.get("siteNumber", "CX"))

    def page_url(search, page_offset=0):
        parsed = urlsplit(source["url"])
        finder_value = (
            f"findReqs;siteNumber={site_number},limit=25,"
            f"offset={page_offset},keyword={search}"
        )
        params = dict(
            onlyData="true",
            expand=("requisitionList.workLocation,requisitionList.otherWorkLocations,"
                    "requisitionList.secondaryLocations"),
            finder=finder_value,
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                           urlencode(params), ""))

    links = []
    if offset + 25 < total and (offset // 25) + 1 < max_pages:
        links.append(page_url(term, offset + 25))
    if offset == 0 and term == terms[0]:
        links.extend(page_url(other) for other in terms[1:])
    return found, links


def plra(text, url):
    """Read PLRA's public careers SPA and its same-origin compiled vacancy data."""
    if not urlsplit(url).path.endswith(".js"):
        soup = BeautifulSoup(text, "html.parser")
        script = soup.select_one('script[src*="/static/js/main."][src$=".js"]')
        if not script or not script.get("src"):
            raise ValueError("PLRA careers bundle not found")
        return [], [urljoin(url, script["src"])]
    pattern = re.compile(
        r'\{id:\d+,title:\{en:"([^"]+)".*?\},link:"(https:[^"]+)",'
        r'department:\{en:"([^"]+)"',
        re.DOTALL,
    )
    found = [
        dict(title=title, category=department, location="Punjab, Pakistan",
             country="Pakistan", applyUrl=apply_url)
        for title, apply_url, department in pattern.findall(text)
    ]
    if not found:
        raise ValueError("No PLRA careers data found")
    return found, []


def nextjs_jobs(text, url, source):
    """Parse a bounded public Next.js careers page with a jobsList payload."""
    soup = BeautifulSoup(text, "html.parser")
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        raise ValueError("Next.js careers data not found")
    payload = json.loads(script.string or script.get_text())
    jobs = payload.get("props", {}).get("pageProps", {}).get("jobsList", [])
    if not isinstance(jobs, list):
        raise ValueError("Invalid Next.js careers data")
    found = []
    for record in jobs:
        if not isinstance(record, dict):
            continue
        details = record.get("acf", {}).get("job", {})
        slug = record.get("slug")
        title = details.get("title") if isinstance(details, dict) else ""
        if title and slug:
            found.append(dict(
                title=title,
                company=source.get("company", ""),
                location=details.get("code", ""),
                description=details.get("description", ""),
                postedAt=record.get("date"),
                applyUrl=urljoin(url, f"/jobs-items/{slug}/"),
            ))
    return found


def orbital_careers(text, url):
    """Parse the official Orbital Africa careers list and its shared HR portal."""
    soup = BeautifulSoup(text, "html.parser")
    found = []
    for card in soup.select(".vc_toggle_content p"):
        link = card.select_one("a[href^='https://']")
        if not link:
            continue
        title = card.get_text(" ", strip=True)
        title = re.sub(r"^\s*\d+\.\s*", "", title)
        title = re.split(r"\s+(?:Please|For) (?:click|more details)", title,
                         maxsplit=1, flags=re.IGNORECASE)[0]
        title = re.sub(r"^We(?:\ufffd|'|’)re looking for\s+(?:An?\s+)?", "",
                       title, flags=re.IGNORECASE).strip(" .+")
        if title:
            found.append(dict(title=title, location="Nairobi, Kenya",
                              country="Kenya", applyUrl=link["href"]))
    if not found:
        raise ValueError("Orbital careers list not found")
    return found


def njp(text, url, source):
    """Parse bounded searches from Pakistan's official National Job Portal."""
    soup = BeautifulSoup(text, "html.parser")
    cards = soup.select(".job-card")
    page_text = soup.get_text(" ", strip=True)
    if not cards and "No Jobs Found" not in page_text:
        raise ValueError("Invalid National Job Portal response")
    found = []
    for card in cards:
        link = card.select_one("h2 a[href]")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        company_node = card.select_one("h2 + p")
        company = company_node.get_text(" ", strip=True) if company_node else ""
        company = re.sub(r"^by\s+", "", company, flags=re.IGNORECASE)
        description_node = card.select_one("p.text-gray-400")
        found.append(dict(
            title=title,
            company=company,
            location="Pakistan",
            country="Pakistan",
            description=(description_node.get_text(" ", strip=True)
                         if description_node else ""),
            applyUrl=urljoin(url, link.get("href", "")),
        ))

    query = parse_qs(urlsplit(url).query)
    term = str(query.get("q", [""])[0])
    terms = [str(value) for value in source.get("searchTerms", [])]
    if term not in terms:
        raise ValueError("Unexpected National Job Portal search term")
    links = []
    if term == terms[0]:
        parsed = urlsplit(source["url"])
        for other in terms[1:]:
            links.append(urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                     urlencode({"q": other}), "")))
    return found, links


def kwsc(text, url):
    """Parse the official Karachi Water & Sewerage careers API."""
    payload = json.loads(text)
    openings = payload.get("data", {}).get("openings")
    if not isinstance(openings, list):
        raise ValueError("Invalid KW&SC careers response")
    found = []
    for job in openings:
        if not isinstance(job, dict) or job.get("status") != "PUBLISHED":
            continue
        title = str(job.get("title", "")).strip()
        if not title:
            continue
        found.append(dict(
            title=title,
            company="Karachi Water & Sewerage Corporation",
            location=job.get("location") or "Karachi, Pakistan",
            country="Pakistan",
            category=job.get("department") or job.get("jobType") or "",
            description=job.get("summary") or job.get("description") or "",
            postedAt=job.get("publishAt"),
            expiresAt=job.get("expireAt"),
            applyUrl="https://www.kwsc.gos.pk/careers#career-openings",
        ))
    return found


def sitemap(text):
    root = xml_root(text)
    return [
        node.text.strip()
        for node in root.iter()
        if node.tag.split("}")[-1] == "loc" and node.text
    ]


def stantec_sitemap(text, url, source):
    """Use Stantec's robots-allowed sitemap without touching blocked search feeds."""
    root = xml_root(text)
    kind = root.tag.split("}")[-1]
    if kind == "sitemapindex":
        links = [link for link in sitemap(text) if "/sitemaps/jobs_" in link]
        if not links:
            raise ValueError("Stantec jobs sitemap not found")
        return [], links[:2]
    if kind != "urlset":
        raise ValueError("Invalid Stantec sitemap")
    terms = tuple(str(term).casefold() for term in source.get("slugKeywords", []))
    found = []
    for node in root:
        values = {child.tag.split("}")[-1]: (child.text or "").strip()
                  for child in node}
        apply_url = values.get("loc", "")
        parts = [unquote(part) for part in urlsplit(apply_url).path.split("/") if part]
        if len(parts) < 4 or parts[-1] != "job":
            continue
        location_slug, title_slug = parts[-4], parts[-3]
        if terms and not any(term in title_slug.casefold() for term in terms):
            continue
        location_parts = location_slug.rsplit("-", 1)
        location = location_slug.replace("-", " ").title()
        if len(location_parts) == 2 and len(location_parts[1]) in (2, 3):
            location = f"{location_parts[0].replace('-', ' ').title()}, {location_parts[1].upper()}"
        found.append(dict(
            title=title_slug.replace("-", " ").title(),
            company=source.get("company", "Stantec"),
            location=location,
            postedAt=values.get("lastmod"),
            applyUrl=apply_url,
        ))
    return found, []


def html(text, url, selectors, fixed_apply_url=""):
    soup = BeautifulSoup(text, "html.parser")
    found = []
    for card in soup.select(selectors["job"]):

        def field(name):
            item = card.select_one(selectors[name]) if selectors.get(name) else None
            return item.get_text(" ", strip=True) if item else ""

        link = card.select_one(selectors["link"]) if selectors.get("link") else None
        apply_url = fixed_apply_url or (link.get("href") if link else "")
        if apply_url:
            found.append(
                dict(
                    title=field("title"),
                    category=field("category"),
                    location=field("location"),
                    company=field("company"),
                    postedAt=re.sub(r"^Posted\s*[-:]\s*", "", field("postedAt"), flags=re.I),
                    description=field("description"),
                    employmentType=field("employmentType"),
                    applyUrl=urljoin(url, apply_url),
                )
            )
    return found


def jibe(text, url):
    """Public iCIMS/Jibe search response; no login or applicant data."""
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Invalid public Jibe careers feed")
    found = []
    for row in payload["jobs"]:
        data = row.get("data", {}) if isinstance(row, dict) else {}
        if not isinstance(data, dict):
            continue
        slug = str(data.get("slug", ""))
        if not slug.isdigit() or not data.get("title") or data.get("applyable") is False:
            continue
        city, country = data.get("city", ""), data.get("country", "")
        found.append(dict(
            title=data["title"], city=city, country=country,
            location=", ".join(str(v) for v in (city, country) if v),
            postedAt=data.get("posted_date"),
            description=data.get("description", ""),
            applyUrl=urljoin(url, "/jobs/" + slug),
        ))
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    page = int(query.get("page", ["1"])[0])
    limit = int(query.get("limit", ["100"])[0])
    links = []
    total = payload.get("totalCount", 0)
    # Keep the public board bounded even if its API reports a corrupt total.
    if isinstance(total, int) and 1 <= page < 3 and 1 <= limit <= 100 and page * limit < total:
        query["page"] = [str(page + 1)]
        links.append(urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                 urlencode(query, doseq=True), "")))
    return found, links


def gis_career_hub(text, url):
    """Read public Next.js card data as JSON, without executing site JavaScript."""
    soup = BeautifulSoup(text, "html.parser")
    decoder = json.JSONDecoder()
    found, seen = [], set()
    for script in soup.find_all("script"):
        match = re.search(r"self\.__next_f\.push\((\[.*\])\)", script.get_text(), re.S)
        if not match:
            continue
        try:
            packet = json.loads(match[1])
        except ValueError:
            continue
        if not isinstance(packet, list) or len(packet) < 2 or not isinstance(packet[1], str):
            continue
        for marker in re.finditer(r'"job":\s*\{', packet[1]):
            try:
                job, _ = decoder.raw_decode(packet[1][marker.end() - 1:])
            except ValueError:
                continue
            slug = str(job.get("slug", ""))
            if (not re.fullmatch(r"[a-z0-9-]+", slug) or slug in seen
                    or not job.get("title")):
                continue
            seen.add(slug)
            country, city = job.get("country", ""), job.get("city", "")
            found.append(dict(
                title=job["title"], company=job.get("company_name", ""),
                country=country, city=city,
                location=job.get("location_name") or ", ".join(str(v) for v in (city, country) if v),
                description=job.get("summary", ""),
                employmentType=job.get("employment_type", ""),
                postedAt=job.get("posted_at"), expiresAt=job.get("closes_at"),
                remote=job.get("location_type") == "Remote",
                # Attribute the aggregator correctly; it owns this public job card.
                applyUrl=urljoin(url, "/jobs/" + slug),
            ))
    if not found:
        empty = False
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(script.get_text())
                empty = empty or (isinstance(value, dict) and value.get("@type") == "ItemList"
                                  and value.get("numberOfItems") == 0)
            except ValueError:
                continue
        if not empty:
            raise ValueError("GIS Career Hub public card data not found")
    return found


def dar_al_riyadh(text, url):
    """Dar's public published-opportunities endpoint, with a strict field allowlist."""
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("Invalid Dar Al Riyadh public careers feed")
    found = []
    for row in payload:
        if not isinstance(row, dict) or row.get("IsExpired") is True:
            continue
        job_id = str(row.get("Id", ""))
        if not job_id.isdigit() or not row.get("Position"):
            continue
        found.append(dict(
            title=row["Position"], location=row.get("JobLocation", ""),
            city=row.get("JobLocation", ""), postedAt=row.get("PostedDate"),
            expiresAt=row.get("ExpiryDate"), description=row.get("JobDescription", ""),
            applyUrl=urljoin(url, "/#/JobDetails/" + job_id),
        ))
    return found


def greenhouse(text):
    """Parse Greenhouse's documented public Job Board API response."""
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Invalid Greenhouse public feed")
    jobs = payload["jobs"]
    found = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        location = job.get("location", {})
        location_name = (
            location.get("name", "") if isinstance(location, dict) else ""
        )
        if job.get("title") and job.get("absolute_url"):
            found.append(
                dict(
                    title=job["title"],
                    location=location_name,
                    postedAt=job.get("updated_at"),
                    applyUrl=job["absolute_url"],
                )
            )
    return found


def lever(text):
    """Parse Lever's documented public Postings API response."""
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("Lever response must be a list")
    found = []
    for job in payload:
        if not isinstance(job, dict):
            continue
        categories = job.get("categories", {})
        if not isinstance(categories, dict):
            categories = {}
        apply_url = job.get("applyUrl") or job.get("hostedUrl")
        created = job.get("createdAt")
        posted = None
        if isinstance(created, (int, float)):
            from datetime import datetime, timezone
            posted = datetime.fromtimestamp(created / 1000, timezone.utc).isoformat()
        if job.get("text") and apply_url:
            found.append(
                dict(
                    title=job["text"],
                    location=categories.get("location", ""),
                    category=categories.get("team", ""),
                    employmentType=categories.get("commitment", ""),
                    description=job.get("descriptionPlain", ""),
                    postedAt=posted,
                    applyUrl=apply_url,
                )
            )
    return found


def jobicy(text):
    """Parse Jobicy's documented public remote-jobs response.

    The public endpoint deliberately returns the Jobicy canonical URL.  Keeping that URL
    preserves source attribution and avoids pretending that it is a direct employer link.
    """
    payload = json.loads(text)
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    found = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        title = job.get("jobTitle")
        url = job.get("url")
        if title and url:
            found.append(
                dict(
                    title=title,
                    company=job.get("companyName", ""),
                    location=job.get("jobGeo", ""),
                    category=job.get("jobIndustry", ""),
                    employmentType=job.get("jobType", ""),
                    description=job.get("jobDescription") or job.get("jobExcerpt", ""),
                    postedAt=job.get("pubDate"),
                    applyUrl=url,
                    remote=True,
                )
            )
    return found


def remotive(text):
    """Parse Remotive's public API while retaining its canonical listing URL."""
    payload = json.loads(text)
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    found = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        title = job.get("title")
        url = job.get("url")
        if title and url:
            found.append(
                dict(
                    title=title,
                    company=job.get("company_name", ""),
                    location=job.get("candidate_required_location", ""),
                    category=job.get("category", ""),
                    employmentType=job.get("job_type", ""),
                    description=job.get("description", ""),
                    postedAt=job.get("publication_date"),
                    applyUrl=url,
                    remote=True,
                )
            )
    return found


def workable(text):
    """Documented public account feed; no candidate/private API or credentials.

    Preserve distinct locations for country-targeted delivery. Never label a company's
    global jobs as Egyptian/Saudi just because its headquarters are there.
    """
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Invalid Workable public feed")
    found = []
    for job in payload["jobs"]:
        if not isinstance(job, dict) or not job.get("title") or not job.get("url"):
            continue
        locations = job.get("locations") or [job]
        if not isinstance(locations, list):
            continue
        for location in locations:
            if not isinstance(location, dict) or location.get("hidden") is True:
                continue
            country = location.get("country", "")
            city = location.get("city", "")
            found.append(dict(
                title=job["title"], company=payload.get("name", ""),
                country=country, city=city,
                location=", ".join(str(v) for v in (city, country) if v),
                postedAt=job.get("published_on"),
                applyUrl=job["url"], employmentType=job.get("employment_type", ""),
                remote=job.get("telecommuting") is True,
            ))
    return found


def workday(text, url, source):
    """Parse a bounded Workday public career-search response.

    Workday career sites expose a public job-search endpoint used by their own web UI.
    Search terms and pagination are whitelisted in source configuration so the collector
    never turns this into an unbounded crawl.
    """
    payload = json.loads(text)
    postings = payload.get("jobPostings", []) if isinstance(payload, dict) else []
    total = payload.get("total") if isinstance(payload, dict) else None
    if not isinstance(postings, list) or not isinstance(total, int):
        raise ValueError("Invalid Workday public feed")
    public_base = str(source.get("publicBaseUrl", "")).rstrip("/")
    if (not public_base.startswith("https://") or
            urlsplit(public_base).hostname != urlsplit(source["url"]).hostname):
        raise ValueError("Missing Workday public career URL")
    found = []
    for job in postings:
        if not isinstance(job, dict):
            continue
        title, path = job.get("title"), job.get("externalPath")
        from .public_ats import workday_location
        location, city, country = workday_location(job)
        if title and isinstance(path, str) and path.startswith("/job/"):
            found.append(dict(
                title=title, company=source.get("company", ""),
                location=location, city=city, country=country,
                applyUrl=public_base + path,
            ))

    query = parse_qs(urlsplit(url).query)
    term = str(query.get("search", [""])[0])
    try:
        offset = int(query.get("offset", ["0"])[0])
    except (TypeError, ValueError):
        raise ValueError("Invalid Workday response URL")
    terms = [str(value) for value in source.get("searchTerms", [])]
    if term not in terms:
        raise ValueError("Unexpected Workday search term")
    max_pages = max(1, min(4, int(source.get("maxPagesPerTerm", 2))))
    links = []

    def page_url(search, page_offset=0):
        parsed = urlsplit(source["url"])
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                           urlencode(dict(search=search, offset=page_offset)), ""))

    if offset + 20 < total and (offset // 20) + 1 < max_pages:
        links.append(page_url(term, offset + 20))
    if offset == 0 and term == terms[0]:
        links.extend(page_url(other) for other in terms[1:])
    return found, links


def smartrecruiters_html(text):
    """Parse the employer's public SmartRecruiters career page.

    We intentionally use the public career page rather than the Posting API because the API
    robots policy disallows generic crawlers. This parser is suited to bounded boards whose
    complete current openings are present in the initial page.
    """
    soup = BeautifulSoup(text, "html.parser")
    sections = soup.select("section.js-group")
    if not sections and not soup.select_one(".js-openings"):
        raise ValueError("Invalid SmartRecruiters career page")
    company_heading = soup.select_one("h1")
    company = company_heading.get_text(" ", strip=True) if company_heading else ""
    found = []
    for section in sections:
        heading = section.select_one("h3")
        location = heading.get_text(" ", strip=True) if heading else ""
        city = location.split(",", 1)[0].strip()
        for card in section.select("li.opening-job"):
            link = card.select_one("a[href]")
            title = card.select_one(".job-title")
            employment = card.select_one(".job-desc")
            if link and title:
                found.append(dict(
                    title=title.get_text(" ", strip=True), company=company,
                    city=city, location=location,
                    employmentType=(employment.get_text(" ", strip=True)
                                    if employment else ""),
                    applyUrl=link["href"],
                ))
    return found


def icims(text, source):
    """Read a bounded iCIMS sitemap, then public metadata from matching job pages."""
    if "<urlset" in text[:500].casefold():
        terms = [str(value).replace("-", " ").replace("_", " ").casefold()
                 for value in source.get("linkKeywords", [])]
        links = []
        for link in sitemap(text):
            slug = unquote(link).replace("-", " ").replace("_", " ").casefold()
            matches = not terms or any(
                re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", slug)
                for term in terms
            )
            if "/jobs/" in slug and matches:
                links.append(link)
        return [], links
    match = re.search(r"var\s+icimsSD\s*=\s*(\{.*?\});", text, re.DOTALL)
    if not match:
        raise ValueError("Invalid iCIMS public job page")
    payload = json.loads(match.group(1))
    job = payload.get("job", {})
    urls = job.get("jobUrls", []) if isinstance(job, dict) else []
    apply_url = next((item.get("url") for item in urls
                      if isinstance(item, dict) and item.get("url")), "")
    if not job.get("title") or not apply_url:
        return [], []
    location = job.get("location", "")
    return [dict(
        title=job["title"], company=payload.get("companyName", ""),
        city=str(location).split(",", 1)[0].strip(), location=location,
        applyUrl=apply_url,
    )], []


def parse(text, url, source):
    if source.get("type") in ("bamboohr", "recruitee", "personio"):
        from . import public_ats
        if source["type"] == "recruitee":
            return public_ats.recruitee(text)
        return getattr(public_ats, source["type"])(text, url)
    if source.get("type") == "jibe":
        return jibe(text, url)
    if source.get("type") == "gis_career_hub":
        return gis_career_hub(text, url), []
    if source.get("type") == "dar_al_riyadh":
        return dar_al_riyadh(text, url), []
    if source.get("type") == "workable":
        return workable(text), []
    if source.get("type") == "workday":
        return workday(text, url, source)
    if source.get("type") == "oracle":
        return oracle(text, url, source)
    if source.get("type") == "plra":
        return plra(text, url)
    if source.get("type") == "nextjs_jobs":
        return nextjs_jobs(text, url, source), []
    if source.get("type") == "stantec_sitemap":
        return stantec_sitemap(text, url, source)
    if source.get("type") == "orbital_careers":
        return orbital_careers(text, url), []
    if source.get("type") == "njp":
        return njp(text, url, source)
    if source.get("type") == "kwsc":
        return kwsc(text, url), []
    if source.get("type") == "greenhouse":
        return greenhouse(text), []
    if source.get("type") == "lever":
        return lever(text), []
    if source.get("type") == "jobicy":
        return jobicy(text), []
    if source.get("type") == "remotive":
        return remotive(text), []
    if source.get("type") == "smartrecruiters_html":
        # The public groups fragment returns HTTP 200 with an empty body when a
        # search has no vacancies. A blank full careers page remains an error.
        if urlsplit(url).path.endswith("/api/groups") and not text.strip():
            return [], []
        return smartrecruiters_html(text), []
    if source.get("type") == "icims":
        return icims(text, source)
    structured = jsonld(text, url)
    if structured:
        return structured, []
    kind = source.get("type", "auto")
    if kind in ("rss", "atom", "auto"):
        try:
            records = rss(text, url)
            if records:
                return records, []
        except ET.ParseError:
            pass
    if kind in ("sitemap", "auto"):
        try:
            links = sitemap(text)
            if links:
                return [], links
        except ET.ParseError:
            pass
    if source.get("selectors"):
        return html(text, url, source["selectors"], source.get("fixedApplyUrl", "")), []
    return [], []
