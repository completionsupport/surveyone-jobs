"""Pure parsers for official public surveying/geospatial vacancy indexes.

Uses only bs4 and the standard library. Fetching, robots, retry policy, clock,
expiry and publication remain with the existing collector. No side effects.
"""
import json
import re
import unicodedata
from datetime import datetime, date
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

_OVERSEAS = {'971': 'Guadeloupe', '972': 'Martinique', '973': 'French Guiana',
    '974': 'Réunion', '975': 'Saint Pierre and Miquelon', '976': 'Mayotte',
    '977': 'Saint Barthélemy', '978': 'Saint Martin', '986': 'Wallis and Futuna',
    '987': 'French Polynesia', '988': 'New Caledonia'}
_FRENCH_REGIONS = {'ile-de-france', 'auvergne-rhone-alpes', "provence-alpes-cote d'azur",
    'occitanie', 'nouvelle-aquitaine', 'bretagne', 'normandie', 'grand est',
    'hauts-de-france', 'pays de la loire', 'centre-val de loire',
    'bourgogne-franche-comte', 'corse'}
_SWEDISH_COUNTRIES = {'Sverige': 'Sweden', 'Norge': 'Norway', 'Danmark': 'Denmark',
    'Finland': 'Finland', 'Tyskland': 'Germany', 'Storbritannien': 'United Kingdom',
    'Frankrike': 'France', 'Spanien': 'Spain', 'Nederländerna': 'Netherlands'}
_CA_PROVINCES = {'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'}
_NONFIELD = re.compile(r'quantity|quanity|quntity|cargo|nursing|estate valuation|valuation surveyor|'
    r'metreur|etudes de prix|bim metreur|fastighetsmaklare|fastighetsvarder|forsakrings|'
    r'cartograph.*(?:applicati|processus|fonctionnelle)', re.I)


def _text(value):
    return str(value or '').strip() if not isinstance(value, (dict, list)) else ''


def _fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD', _text(value)).casefold()
                   if not unicodedata.combining(c))


def _field_role(title, occupation=''):
    value = _fold(title + ' ' + occupation)
    if _NONFIELD.search(value):
        return False
    return bool(re.search(r'survey|geom|geo?des|lantmat|matning|kartingenjor|kartograf|'
                          r'geodata|topograph|topograf|cartograph|gis|\bsig\b|'
                          r'remote sensing|earth observation|insar', value))


def _category_hint(title, occupation=''):
    value = _fold(title + ' ' + occupation)
    return ('GIS / Geospatial' if re.search(r'gis|\bsig\b|geodata|cartograph|kartograf|'
        r'kartingenjor|geomatic|geospatial|remote sensing|earth observation|insar', value)
        else 'Land Surveying')


def _max_pages(source, default=2):
    # The collector enforces per-run request/time limits and owns continuation state.
    ceiling = 120 if source.get('resumePagination') is True else 24
    return max(1, min(ceiling, int(source.get('maxPagesPerTerm', default))))


def _terms(source, current):
    values = source.get('searchTerms') or [current]
    if not isinstance(values, list) or not values or len(values) > 30:
        raise ValueError('Invalid bounded government search terms')
    terms = [str(v) for v in values]
    if current not in terms:
        raise ValueError('Unexpected government search term')
    return terms


def _date_only(value):
    raw = _text(value)
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def parse_jobtech(body, url, source):
    """Official Swedish JobSearch current index, CC0, no registration/API key."""
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get('hits'), list):
        raise ValueError('Invalid JobTech public response')
    total = payload.get('total', {}).get('value') if isinstance(payload.get('total'), dict) else None
    if not isinstance(total, int) or total < 0:
        raise ValueError('Invalid JobTech result count')
    parsed = urlsplit(url)
    if parsed.hostname != 'jobsearch.api.jobtechdev.se' or parsed.path != '/search':
        raise ValueError('Unexpected JobTech endpoint')
    query = parse_qs(parsed.query)
    term = query.get('q', [''])[0]
    terms = _terms(source, term)
    limit, offset = int(query.get('limit', ['100'])[0]), int(query.get('offset', ['0'])[0])
    if limit < 1 or limit > 100 or offset < 0 or offset % limit:
        raise ValueError('Invalid JobTech pagination')
    result = []
    for hit in payload['hits']:
        if not isinstance(hit, dict) or hit.get('removed') is True:
            continue
        title = _text(hit.get('headline'))
        occupation = _text((hit.get('occupation') or {}).get('label'))
        if not title or not _field_role(title, occupation):
            continue
        # A broad official occupation label alone does not make a generic title
        # a field/GIS vacancy. Require actual profession evidence in its advert.
        description = _text((hit.get('description') or {}).get('text'))
        if not _field_role(title) and not _field_role(description):
            continue
        address = hit.get('workplace_address') or {}
        if not isinstance(address, dict):
            address = {}
        country = _SWEDISH_COUNTRIES.get(_text(address.get('country')), '')
        # country_code199 is an Arbetsförmedlingen taxonomy identifier, NOT ISO.
        if address.get('country_concept_id') == 'i46j_HmG_v64':
            country = 'Sweden'
        city = _text(address.get('city') or address.get('municipality'))
        link = _text(hit.get('webpage_url'))
        if not re.fullmatch(r'https://arbetsformedlingen\.se/platsbanken/annonser/[0-9]+', link):
            continue
        published_raw = _text(hit.get('publication_date'))
        deadline_raw = _text(hit.get('application_deadline') or hit.get('last_publication_date'))
        closing_date = _date_only(deadline_raw)
        hint = _category_hint(title, occupation)
        result.append(dict(title=title,
            company=_text((hit.get('employer') or {}).get('name')) or 'Employer not disclosed',
            city=city, country=country, location=', '.join(x for x in (city, country) if x),
            category=(hint + ' | ' + occupation), canonicalCategory=hint,
            postedAt=_date_only(published_raw),
            # Preserve the unzoned source value separately. Expire early at the start
            # of its declared closing day rather than invent a precise timezone.
            expiresAt=closing_date + 'T00:00:00Z' if closing_date else None,
            description=description,
            employmentType=_text((hit.get('employment_type') or {}).get('label')),
            applyUrl=link, providerJobId=_text(hit.get('id')),
            originalPublishedTimestamp=published_raw,
            originalApplicationDeadline=deadline_raw,
            sourceTimestampsHaveNoOffset=bool(deadline_raw and not re.search(r'(?:Z|[+-][0-9]{2}:[0-9]{2})$', deadline_raw))))

    def page(search, start=0):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                          urlencode(dict(q=search, limit=limit, offset=start)), ''))
    links = []
    if offset + limit < total and offset // limit + 1 < _max_pages(source):
        links.append(page(term, offset + limit))
    if offset == 0 and term == terms[0]:
        links.extend(page(other) for other in terms[1:])
    return result, links


def _french_location(value):
    value = _text(value)
    match = re.match(r'^(\d{2,3}|2[AB])\s*-\s*(.+)$', value)
    if match:
        department, city = match.groups()
        if department in _OVERSEAS:
            return city.strip(), _OVERSEAS[department], value
        if department in ('2A', '2B') or department.isdigit() and 1 <= int(department) <= 95:
            return city.strip(), 'France', value
        # Department99 represents abroad, not metropolitan France.
        countries = {'suisse': 'Switzerland', 'belgique': 'Belgium', 'luxembourg': 'Luxembourg',
                     'allemagne': 'Germany', 'espagne': 'Spain', 'royaume-uni': 'United Kingdom'}
        return '', countries.get(_fold(city), ''), value
    return '', 'France' if _fold(value) in _FRENCH_REGIONS else '', value


def parse_france_travail(body, url, source):
    """First-party public vacancy cards. Relative dates remain explicitly unknown."""
    parsed = urlsplit(url)
    if parsed.hostname != 'candidat.francetravail.fr' or parsed.path != '/offres/recherche':
        raise ValueError('Unexpected France Travail endpoint')
    query = parse_qs(parsed.query)
    if query.get('offresPartenaires', ['false'])[0] != 'false':
        raise ValueError('Only first-party France Travail cards are configured')
    term = query.get('motsCles', [''])[0]
    terms = _terms(source, term)
    span = re.fullmatch(r'(\d+)-(\d+)', query.get('range', ['0-19'])[0])
    if not span or int(span[1]) % 20 or int(span[2]) != int(span[1]) + 19:
        raise ValueError('Invalid France Travail range')
    offset = int(span[1])
    soup = BeautifulSoup(body, 'html.parser')
    heading = soup.select_one('h1')
    count_match = re.search(r'([\d\s]+)\s+offres?', heading.get_text(' ', strip=True) if heading else '')
    cards = soup.select('li.result[data-id-offre]')
    if not count_match and not cards and not soup.select_one('.result-list, #resultatRechercheZone'):
        raise ValueError('Invalid France Travail public results page')
    total = int(re.sub(r'\s+', '', count_match[1])) if count_match else len(cards)
    result = []
    for card in cards:
        ident = _text(card.get('data-id-offre'))
        title_node = card.select_one('.media-heading-title')
        title = title_node.get_text(' ', strip=True) if title_node else ''
        if not re.fullmatch(r'[A-Za-z0-9]{5,16}', ident) or not title or not _field_role(title):
            continue
        folded = _fold(title)
        if re.search(r'secretaire|ressources humaines|assistant.{0,15}(?:administrati|commercial)|'
                     r'comptable|responsable administrati', folded):
            continue
        description_node = card.select_one('.description')
        excerpt = description_node.get_text(' ', strip=True) if description_node else ''
        if not re.search(r'geometre|topograph|geomatic|geospatial|information geographique|\bsig\b|\bgis\b|cartograph', folded):
            continue
        if 'cartograph' in folded and not re.search(r'geometre|topograph|geomatic|geospatial|\bsig\b|\bgis\b', folded):
            if not re.search(r'geograph|geospat|qgis|arcgis|donnees spatiales|geomatic|topograph', _fold(title + ' ' + excerpt)):
                continue
        # Bare SIG is insufficient. A named GIS profession is an anchor; utility
        # network/FTTH/water-inspection context is another. Generic finance/ERP
        # process-mapping titles do not inherit GIS relevance from the query.
        if re.search(r'\bsig\b', folded) and not re.search(r'geomatic|geometre|topograph|cartograph|geospatial|information geographique', folded):
            professional_sig = bool(re.search(r'(?:technicien|dessinateur|ingenieur|expert|developpeur).{0,90}\bsig\b', folded))
            utility_context = bool(re.search(r'eau potable|assainissement|fibre optique|ftth|fttx|reseaux enterres|inspections televisees', _fold(title + ' ' + excerpt)))
            geographic_context = bool(re.search(r'geograph|geospat|qgis|arcgis|donnees spatiales|geomatic|topograph', _fold(excerpt)))
            financial_context = bool(re.search(r'finance|comptab|gestion commerciale|ressources humaines|\berp\b', _fold(title + ' ' + excerpt)))
            if not (geographic_context or utility_context or professional_sig and not financial_context):
                continue
        sub = card.select_one('.subtext')
        location_node = sub.select_one('span') if sub else None
        place = location_node.get_text(' ', strip=True) if location_node else ''
        company = sub.get_text(' ', strip=True) if sub else ''
        company = company.replace(place, '').strip(' \u00a0-') if place else company
        company = company or 'Employeur non précisé'
        city, country, location = _french_location(place)
        contract_node, date_node = card.select_one('.contrat'), card.select_one('.date')
        contract = contract_node.get_text(' ', strip=True) if contract_node else ''
        relative_date = date_node.get_text(' ', strip=True) if date_node else ''
        hint = _category_hint(title)
        result.append(dict(title=title, company=company, city=city, country=country, location=location,
            category=hint, canonicalCategory=hint, postedAt=None, expiresAt=None,
            description='; '.join(('Employer: ' + company, 'Workplace: ' + location,
                'Contract: ' + contract, 'Source publication label: ' + relative_date,
                'Read the complete official advert and application instructions using the source link.')),
            employmentType=contract, applyUrl='https://candidat.francetravail.fr/offres/recherche/detail/' + ident,
            providerJobId=ident, originalPublicationText=relative_date, postedDateUnknown=True))

    def page(search, start=0):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(dict(
            motsCles=search, offresPartenaires='false', range=f'{start}-{start + 19}', tri=1)), ''))
    links = []
    if offset + 20 < total and offset // 20 + 1 < _max_pages(source, 15):
        links.append(page(term, offset + 20))
    if offset == 0 and term == terms[0]:
        links.extend(page(other) for other in terms[1:])
    return result, links


def _canadian_link(value, base):
    url = urljoin(base, _text(value))
    url = re.sub(r';jsessionid=[^?/#]+', '', url, flags=re.I)
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.jobbank.gc.ca' or not re.fullmatch(r'/jobsearch/jobposting/\d+', parsed.path):
        return ''
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def _canadian_location(place):
    match = re.match(r'^(.*?)\s*\(([A-Z]{2})\)', place)
    return (match[1].strip(), 'Canada') if match and match[2] in _CA_PROVINCES else ('', '')


def _canadian_role(title, noc):
    return bool(re.search(r'survey|geomatic|gis|geospatial|cartograph|mapping|topograph', title, re.I)) and not _NONFIELD.search(_fold(title))


def parse_canada_jobbank(body, url, source):
    """Official native-only Atom feed plus its optional current-card bootstrap."""
    parsed = urlsplit(url)
    if parsed.hostname != 'www.jobbank.gc.ca' or not parsed.path.startswith('/jobsearch/'):
        raise ValueError('Unexpected Canadian Job Bank endpoint')
    query = parse_qs(parsed.query)
    if query.get('fsrc', [''])[0] != '16':
        raise ValueError('Only verified employer-direct Canadian jobs are configured')
    noc = query.get('fn21', [''])[0]
    nocs = [str(value) for value in source.get('occupationCodes', ['21203', '22213', '22214'])]
    if noc not in nocs or noc not in ('21203', '22213', '22214'):
        raise ValueError('Unexpected Canadian surveying/geomatics occupation')
    result = []
    xml = body.lstrip().startswith(('<?xml', '<feed', '<rss'))
    if xml:
        if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():
            raise ValueError('XML entities are unsupported')
        root = ET.fromstring(body)
        if root.tag.split('}')[-1] not in ('feed', 'rss'):
            raise ValueError('Invalid Canadian Atom/RSS document')
        entries = root.findall('{*}entry') if root.tag.split('}')[-1] == 'feed' else root.findall('./channel/item')
        for entry in entries:
            def field(name):
                node = entry.find('{*}' + name)
                return node.text or '' if node is not None else ''
            title = BeautifulSoup(field('title'), 'html.parser').get_text(' ', strip=True)
            if not _canadian_role(title, noc):
                continue
            excerpt = BeautifulSoup(field('summary') or field('description'), 'html.parser')
            labels = {}
            for label in excerpt.select('strong'):
                pieces = []
                for sibling in label.next_siblings:
                    if getattr(sibling, 'name', None) == 'br':
                        break
                    pieces.append(str(sibling))
                labels[label.get_text(' ', strip=True).strip(':')] = BeautifulSoup(''.join(pieces), 'html.parser').get_text(' ', strip=True)
            raw_link = next((item.get('href') for item in entry.findall('{*}link') if item.get('rel') == 'alternate'), '') or field('link')
            link = _canadian_link(raw_link, url)
            if not link:
                continue
            place = labels.get('Location', '')
            city, country = _canadian_location(place)
            hint = 'GIS / Geospatial' if noc == '22214' else 'Land Surveying'
            result.append(dict(title=title, company=labels.get('Employer') or 'Employer not disclosed',
                city=city, country=country, location=place,
                category=hint + (' | Survey Technician' if noc == '22213' else ''), canonicalCategory=hint,
                postedAt=field('published') or field('pubDate') or field('updated') or None,
                description=excerpt.get_text(' ', strip=True), applyUrl=link,
                providerJobId=labels.get('Job number', ''), occupationCode=noc,
                originalSourceDate=field('published') or field('pubDate') or field('updated'),
                sourceDateType='Atom published or provided updated timestamp; no new date invented'))
    else:
        soup = BeautifulSoup(body, 'html.parser')
        cards = soup.select('a.resultJobItem')
        if not cards and not soup.select_one('.results-list-content, .results-jobs, #jobSearchForm'):
            raise ValueError('Invalid Canadian public job-results page')
        for card in cards:
            title_node = card.select_one('.noctitle')
            title = title_node.get_text(' ', strip=True) if title_node else ''
            if not _canadian_role(title, noc):
                continue
            publisher = card.select_one('.source .wb-inv')
            if publisher and publisher.get_text(' ', strip=True) != 'Job Bank':
                continue
            def field(selector):
                node = card.select_one(selector)
                return node.get_text(' ', strip=True) if node else ''
            link = _canadian_link(card.get('href'), url)
            if not link:
                continue
            company = field('.business') or 'Employer not disclosed'
            place = re.sub(r'^Location\s*', '', field('.location'))
            city, country = _canadian_location(place)
            try:
                posted = datetime.strptime(field('.date'), '%B %d, %Y').date().isoformat()
            except ValueError:
                posted = None
            hint = 'GIS / Geospatial' if noc == '22214' else 'Land Surveying'
            result.append(dict(title=title, company=company, city=city, country=country, location=place,
                category=hint + (' | Survey Technician' if noc == '22213' else ''), canonicalCategory=hint,
                postedAt=posted, description='; '.join(('Employer: ' + company, 'Workplace: ' + place, field('.salary'))),
                applyUrl=link, occupationCode=noc, sourceDateType='Original employer posting date shown on official current card'))

    links = []
    if xml and noc == nocs[0]:
        for other in nocs[1:]:
            links.append('https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed?' + urlencode(
                dict(fn21=other, fsrc=16, sort='D', rows=100, fage=30)))
        for bootstrap in source.get('initialBootstrapUrls', [])[:3]:
            target = urlsplit(str(bootstrap))
            q = parse_qs(target.query)
            if (target.scheme != 'https' or target.hostname != parsed.hostname or target.path != '/jobsearch/jobsearch'
                    or q.get('fsrc') != ['16'] or q.get('fn21', [''])[0] not in nocs):
                raise ValueError('Unexpected Canadian bootstrap URL')
            links.append(str(bootstrap))
    return result, links
