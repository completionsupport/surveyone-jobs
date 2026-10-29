"""Public employer feeds. No authenticated recruitment or candidate endpoints."""
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .countries import country_name
from .model import BeautifulText, infer_country


US_STATES = set(('Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia '
                 'Hawaii Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts '
                 'Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada Ohio Oklahoma Oregon '
                 'Pennsylvania Tennessee Texas Utah Vermont Virginia Washington Wisconsin Wyoming').casefold().split())
US_STATES.update(x.casefold() for x in ('District of Columbia', 'New Hampshire', 'New Jersey', 'New Mexico',
                                      'New York', 'North Carolina', 'North Dakota', 'Rhode Island',
                                      'South Carolina', 'South Dakota', 'West Virginia'))
CA_PROVINCES = {x.casefold() for x in ('Alberta', 'British Columbia', 'Manitoba', 'New Brunswick',
    'Newfoundland and Labrador', 'Nova Scotia', 'Ontario', 'Prince Edward Island', 'Quebec',
    'Québec', 'Saskatchewan', 'Northwest Territories', 'Nunavut', 'Yukon')}


def text(value):
    return str(value or '').strip() if not isinstance(value, (dict, list)) else ''


def location_values(value):
    city, state = text(value.get('city')), text(value.get('state') or value.get('province'))
    if re.fullmatch(r'[.\-\s]*', city):
        city = ''
    country = text(value.get('country_code') or value.get('country'))
    if not country:
        if state.casefold() in CA_PROVINCES:
            country = 'CA'
        elif state.casefold() in US_STATES:
            country = 'US'
    country = country_name(country) if country else ''
    return city, country, ', '.join(x for x in (city, state, country) if x)


def workday_location(job):
    """Use actual published location labels, never a requisition ID as a city."""
    value = text(job.get('locationsText'))
    multiple = bool(re.fullmatch(r'\d+\s+locations?', value, re.I))
    identifier = bool(re.fullmatch(r'(?:JR|REQ|R)[-_]?\d+(?:-\d+)?', value, re.I))
    fallback = not value or multiple or identifier
    if fallback:
        # The public posting path explicitly identifies its primary location.
        # This avoids tenant-specific bulletFields, which often contain job IDs.
        match = re.search(r'/job/([^/]+)/', text(job.get('externalPath')))
        value = unquote(match.group(1)).replace('-', ' ') if match else ''
        if re.fullmatch(r'(?:JR|REQ|R)[-_ ]?\d+(?:[- ]\d+)?', value, re.I):
            value = ''
        if not value:
            bullets = job.get('bulletFields')
            first = text(bullets[0]) if isinstance(bullets, list) and bullets else ''
            if first and not re.fullmatch(r'(?:JR|REQ|R)[-_]?\d+(?:-\d+)?', first, re.I) and infer_country(first):
                value = first
    country = infer_country(value)
    state = value.casefold()
    if not country and (state in US_STATES or state in CA_PROVINCES):
        country = 'United States' if state in US_STATES else 'Canada'
    # CA can mean California or Canada. A leading CA country plus an actual
    # Canadian province code is strong evidence; a lone CA prefix is not.
    if re.match(r'^CA[ -]+(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)[ -]+', value, re.I):
        country = 'Canada'
    city = value.split('-', 1)[-1].strip()
    if (fallback or state in US_STATES or state in CA_PROVINCES or
        re.search(r'\b(?:worldwide|remote|multiple|locations?|office|level|house|hub|building|archives)\b', value, re.I)):
        city = ''
    return value, city, country


def bamboohr(body, url):
    payload = json.loads(body)
    rows = payload.get('result') if isinstance(payload, dict) else None
    meta = payload.get('meta') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not isinstance(meta, dict) or not isinstance(meta.get('totalCount'), int):
        raise ValueError('Invalid public BambooHR careers list')
    if meta['totalCount'] > len(rows):
        raise ValueError('Incomplete public BambooHR careers list')
    found = []
    for job in rows:
        if not isinstance(job, dict) or not text(job.get('jobOpeningName')):
            continue
        job_id = text(job.get('id'))
        if not re.fullmatch(r'\d+', job_id):
            continue
        location = job.get('location') or {}
        ats = job.get('atsLocation') or {}
        if not isinstance(location, dict) or not isinstance(ats, dict):
            continue
        city, country, display = location_values({**location,
            **{key: value for key, value in ats.items() if value}})
        found.append(dict(title=job['jobOpeningName'], city=city, country=country, location=display,
            category=text(job.get('departmentLabel')), employmentType=text(job.get('employmentStatusLabel')),
            applyUrl=urljoin(url, '/careers/' + job_id), remote=job.get('isRemote') is True))
    return found, []


def recruitee(body):
    payload = json.loads(body)
    rows = payload.get('offers') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError('Invalid public Recruitee offers feed')
    found = []
    for job in rows:
        if not isinstance(job, dict) or job.get('status', 'published') != 'published' or job.get('kind', 'job') != 'job':
            continue
        title, link = text(job.get('title')), text(job.get('careers_url'))
        if not title or not link:
            continue
        locations = job.get('locations') or [job]
        if not isinstance(locations, list):
            continue
        for place in locations:
            if not isinstance(place, dict):
                continue
            city, country, display = location_values({**place,
                'state': place.get('state') or place.get('state_name')})
            posted = text(job.get('published_at'))
            if posted.endswith(' UTC'):
                posted = posted[:-4] + '+00:00'
            found.append(dict(title=title, company=text(job.get('company_name')),
                location=display, city=city, country=country,
                postedAt=posted or None, expiresAt=job.get('close_at'),
                description=BeautifulText(job.get('description') or job.get('sharing_description'))[:4000],
                employmentType=text(job.get('employment_type_code')),
                applyUrl=link, remote=job.get('remote') is True))
    return found, []


def personio(body, url):
    if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():
        raise ValueError('XML entities are unsupported')
    root = ET.fromstring(body)
    if root.tag not in ('workzag-jobs', 'positions'):
        raise ValueError('Invalid public Personio position feed')
    found = []
    parsed = urlsplit(url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
    for job in root.findall('position'):
        values = {child.tag: (child.text or '').strip() for child in job}
        job_id, title = values.get('id', ''), values.get('name', '')
        if not re.fullmatch(r'\d+', job_id) or not title:
            continue
        office = values.get('office', '')
        # Office names alone do not prove a country, and internal createdAt is
        # not a publication date. Never substitute the employer headquarters.
        description = ' '.join(BeautifulText(child.text or '') for child in job.findall('jobDescriptions/jobDescription/value'))
        found.append(dict(title=title, company=values.get('subcompany', ''), location=office, city=office,
            country=values.get('country', ''), category=values.get('department', ''),
            description=description[:4000], employmentType=values.get('schedule') or values.get('employmentType', ''),
            applyUrl=origin + '/job/' + job_id + '?language=en'))
    return found, []
