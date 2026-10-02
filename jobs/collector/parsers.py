"""Parsers return metadata only. Site selectors live entirely in configuration."""

import json
import re
from urllib.parse import unquote, urljoin
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
            elif tag in ("title", "pubDate", "published", "updated"):
                if tag != "updated" or not values.get("postedAt"):
                    values["title" if tag == "title" else "postedAt"] = child.text or ""
        if values.get("title") and values.get("applyUrl"):
            jobs.append(values)
    return jobs


def sitemap(text):
    root = xml_root(text)
    return [
        node.text.strip()
        for node in root.iter()
        if node.tag.split("}")[-1] == "loc" and node.text
    ]


def html(text, url, selectors):
    soup = BeautifulSoup(text, "html.parser")
    found = []
    for card in soup.select(selectors["job"]):

        def field(name):
            item = card.select_one(selectors[name]) if selectors.get(name) else None
            return item.get_text(" ", strip=True) if item else ""

        link = card.select_one(selectors["link"])
        if link and link.get("href"):
            found.append(
                dict(
                    title=field("title"),
                    category=field("category"),
                    location=field("location"),
                    company=field("company"),
                    applyUrl=urljoin(url, link["href"]),
                )
            )
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
    if source.get("type") == "workable":
        return workable(text), []
    if source.get("type") == "greenhouse":
        return greenhouse(text), []
    if source.get("type") == "lever":
        return lever(text), []
    if source.get("type") == "jobicy":
        return jobicy(text), []
    if source.get("type") == "remotive":
        return remotive(text), []
    if source.get("type") == "smartrecruiters_html":
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
        return html(text, url, source["selectors"]), []
    return [], []
