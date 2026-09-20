"""Parsers return metadata only. Site selectors live entirely in configuration."""

import json
from urllib.parse import urljoin
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
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
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


def parse(text, url, source):
    if source.get("type") == "greenhouse":
        return greenhouse(text), []
    if source.get("type") == "lever":
        return lever(text), []
    if source.get("type") == "jobicy":
        return jobicy(text), []
    if source.get("type") == "remotive":
        return remotive(text), []
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
