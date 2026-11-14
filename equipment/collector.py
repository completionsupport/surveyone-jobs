"""Refresh genuine supplier product pages; discover new products from reviewed sources.

Only HTTPS allowlisted suppliers are fetched. Product-specific structured offers determine
availability; a successful HTTP response alone never renews a listing. No photos are rehosted.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

AGENT = 'SurveyOneEquipmentBot/1.0 (+https://surveyone.app)'
MAX_BYTES = 5_000_000
AVAILABLE = {'instock', 'limitedavailability', 'preorder', 'presale', 'backorder', 'onlineonly'}
UNAVAILABLE = {'outofstock', 'soldout', 'discontinued', 'instoreonly'}
_locks: dict[str, threading.Lock] = {}
_robot_cache: dict[str, RobotFileParser | None] = {}
_guard = threading.Lock()

def canonical(url: str) -> str:
    p = urlsplit(url)
    path = re.sub(r'^/collections/[^/]+/products/', '/products/', p.path)
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in {'gclid','fbclid'}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ''))

def allowed(url: str, hosts: list[str]) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None,443): return False
        return not any(not ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM))
    except (ValueError, OSError): return False

def _download(url: str, hosts: list[str]) -> tuple[str,str]:
    for _ in range(5):
        if not allowed(url,hosts): raise ValueError('URL outside source allowlist')
        with requests.get(url, headers={'User-Agent': AGENT}, timeout=(10,20), allow_redirects=False, stream=True) as r:
            if r.is_redirect:
                url = urljoin(url,r.headers['Location']); continue
            r.raise_for_status()
            chunks=[]; size=0
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES: raise ValueError('Supplier response too large')
                chunks.append(chunk)
            encoding=r.encoding if r.encoding and r.encoding.lower()!='iso-8859-1' else 'utf-8'
            return b''.join(chunks).decode(encoding,errors='replace'),url
    raise ValueError('Too many supplier redirects')

def fetch(url: str, source: dict) -> tuple[str,str]:
    host=urlsplit(url).hostname
    with _guard: lock=_locks.setdefault(host,threading.Lock())
    with lock:
        if host not in _robot_cache:
            try:
                raw,_=_download(f'https://{host}/robots.txt',source['allowedHosts'])
                rp=RobotFileParser();rp.parse(raw.splitlines());_robot_cache[host]=rp
            except requests.HTTPError as e:
                if e.response.status_code==404: _robot_cache[host]=None
                else: raise
        rp=_robot_cache[host]
        if rp and not rp.can_fetch(AGENT,url): raise ValueError('Disallowed by supplier robots.txt')
        time.sleep(max(.25, min(10, rp.crawl_delay(AGENT) or 0)) if rp else .25)
        return _download(url,source['allowedHosts'])

def text(value) -> str:
    return ' '.join(BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True).split())

def walk(value):
    if isinstance(value,dict):
        yield value
        for child in value.values(): yield from walk(child)
    elif isinstance(value,list):
        for child in value: yield from walk(child)

def category(title: str, kind: str = '') -> str | None:
    s=(title+' '+kind).lower()
    # Accessories first: a battery for a total station must not become a total station.
    if re.search(r'prism|tripod|tribrach|battery|batteries|charger|cable|pole|staff|bracket|adapter|adaptor|case|bipod|trip[eé]|prisma|bateria|cargador|reflector|tablet|controller|antenn|accessor|\brod\b|حامل|بطاري|عاكس|اكسسو',s): return 'ACCESSORIES'
    if re.search(r'total.?station|estaci[oó]n.?total|stazione.?totale|tachym|tacheom|teodol|theodoli|محطة متكاملة|توتال',s): return 'TOTAL_STATION'
    if re.search(r'gnss|\brtk\b|\bgps\b|receptor|receiver|geodetic',s): return 'GNSS'
    if re.search(r'laser.?scan|\blidar\b|\bslam\b|3d.?scan',s): return 'LASER_SCANNER'
    if re.search(r'\blevel\b|nivell|nivel|n[ií]vel|laser rot|automatic.?level|ميزان',s): return 'LEVEL'
    if re.search(r'survey|geodes|geomat|topogr|geospatial|distance.?meter|laser.?meter|مساح',s): return 'OTHER'
    return None

def product(html: str, url: str) -> dict | None:
    soup=BeautifulSoup(html,'html.parser')
    candidates=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try: items=walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError): continue
        for item in items:
            types=item.get('@type',[]);types=[types] if isinstance(types,str) else types if isinstance(types,list) else []
            if 'Product' in types: candidates.append(item)
    # Avoid related-product cards: prefer the canonical product, otherwise require one product only.
    exact=[p for p in candidates if isinstance(p.get('url'),str) and canonical(urljoin(url,p['url'])) == canonical(url)]
    p=exact[0] if exact else candidates[0] if len(candidates)==1 else None
    if not p: return None
    name=text(p.get('name'))
    if len(name)<3: return None
    offers=p.get('offers',[]);offers=offers if isinstance(offers,list) else [offers]
    expanded=[]
    for offer in offers:
        nested=offer.get('offers') if isinstance(offer,dict) else None
        expanded.extend(nested if isinstance(nested,list) else [offer])
    offers=[o for o in expanded if isinstance(o,dict)]
    available=[o for o in offers if str(o.get('availability','')).rsplit('/',1)[-1].lower() in AVAILABLE]
    unavailable=bool(offers) and all(str(o.get('availability','')).rsplit('/',1)[-1].lower() in UNAVAILABLE for o in offers)
    if not available and not unavailable: return {'title':name,'availability':'UNKNOWN'}
    image=p.get('image','')
    if isinstance(image,list): image=image[0] if image else ''
    if isinstance(image,dict): image=image.get('url') or image.get('contentUrl') or ''
    if not isinstance(image,str): image=''
    brand=p.get('brand','');brand=brand.get('name','') if isinstance(brand,dict) else brand
    price=None;currency=''
    if len(available)==1:
        offer=available[0];currency=str(offer.get('priceCurrency','')).upper()
        try:
            number=Decimal(str(offer.get('price')))*100
            if number.is_finite() and number==number.to_integral_value() and 0<number<=100_000_000_000 and re.fullmatch('[A-Z]{3}',currency):price=int(number)
        except InvalidOperation: pass
    return {'title':name[:140], 'description':text(p.get('description'))[:2400], 'make':text(brand)[:60],
            'model':text(p.get('model'))[:80], 'imageUrl':urljoin(url,image) if image else '',
            'priceMinor':price,'currency':currency if re.fullmatch('[A-Z]{3}',currency) else '',
            'availability':'AVAILABLE' if available else 'UNAVAILABLE', 'sourceUrl':canonical(url),
            'condition':'USED' if 'UsedCondition' in str(p.get('itemCondition','')) else ''}

def discover(source: dict) -> list[str]:
    links=[]
    for seed in source.get('seedUrls',[source['websiteUrl']])[:3]:
        try:
            html,final=fetch(seed,source);soup=BeautifulSoup(html,'html.parser')
            for a in soup.select('a[href]'):
                href=canonical(urljoin(final,a['href']))
                if urlsplit(href).hostname not in source['allowedHosts']:continue
                if re.search(r'/(?:products?|produits|produkt|producto|shop)/[^/?]+',urlsplit(href).path) and not re.search(r'/(?:category|tag|cart|account|collections)/',href): links.append(href)
        except (requests.RequestException,ValueError): continue
    return list(dict.fromkeys(links))[:100]

def collect(source: dict, existing: list[dict], discovery: bool) -> list[dict]:
    old_by_url={canonical(x['sourceUrl']):x for x in existing}
    urls=list(old_by_url)
    if discovery:
        candidates=[u for u in discover(source) if u not in old_by_url]
        if candidates:
            offset=(int(time.time()/1800000)//4*12)%len(candidates)
            urls+=(candidates[offset:]+candidates[:offset])[:12]
    results=[]; failures=0
    for url in urls:
        old=old_by_url.get(url)
        try:
            html,final=fetch(url,source);failures=0;p=product(html,final)
            if p is None: results.append({'sourceId':source['id'],'sourceUrl':url,'id':old.get('id') if old else None,'expectedRevision':old.get('revision') if old else None,'outcome':'UNSUPPORTED_PRODUCT'});continue
            if p['availability']!='AVAILABLE':
                results.append({'sourceId':source['id'],'sourceUrl':url,'id':old.get('id') if old else None,
                    'expectedRevision':old.get('revision') if old else None,'outcome':p['availability']});continue
            cat=old.get('category') if old else category(p['title'],p['description'])
            if not cat:continue
            description=old.get('description') if old else (p['description'] or f"{p['title']}. Equipment offered by {source['name']}. Contact the supplier for current availability and delivery.")
            image=p['imageUrl'] if source.get('imageReuseAllowed') and urlsplit(p['imageUrl']).hostname in source.get('imageHosts',[]) else ''
            listing={**(old or {}),**p,'sourceId':source['id'],'sourceUrl':url,'category':cat,
                'make':p['make'] or (old or {}).get('make',''), 'model':p['model'] or (old or {}).get('model',''),
                'countryCode':old.get('countryCode') if old else source['countryCode'],
                'city':old.get('city') if old else source['city'],'description':description,
                'title':old.get('title') if old else p['title'], 'listingType':old.get('listingType','SALE') if old else 'SALE',
                'imageUrl':image, 'imageRightsConfirmed':bool(image),'rentPeriod':old.get('rentPeriod','') if old else ''}
            results.append({'listing':listing,'id':old.get('id') if old else None,'expectedRevision':old.get('revision') if old else None,
                'outcome':'VERIFIED','verifiedAtMs':int(time.time()*1000),'evidence':{'url':final,'availability':p['availability'],'title':p['title']}})
        except (requests.RequestException,ValueError,OSError) as e:
            results.append({'sourceId':source['id'],'sourceUrl':url,'id':old.get('id') if old else None,'expectedRevision':old.get('revision') if old else None,'outcome':'FETCH_FAILED','errorType':type(e).__name__})
            failures+=1
            if failures>=3:break  # One unavailable supplier must not consume the entire run.
    return results

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot',default='equipment/snapshot.json');parser.add_argument('--output',default='equipment/plan.json');parser.add_argument('--no-discovery',action='store_true')
    args=parser.parse_args();snapshot=json.loads(Path(args.snapshot).read_text('utf8'));results=[]
    def run(s):return collect(s,[x for x in snapshot['listings'] if x['sourceId']==s['id']],not args.no_discovery and s.get('discover',True))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(run,s):s for s in snapshot['sources']}
        for f in concurrent.futures.as_completed(futures):
            items=f.result();results.extend(items);print(json.dumps({'source':futures[f]['name'],'checked':len(items),'verified':sum(x['outcome']=='VERIFIED' for x in items)}),flush=True)
    Path(args.output).write_text(json.dumps({'createdAtMs':int(time.time()*1000),'items':results},ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'checked':len(results),'verified':sum(x['outcome']=='VERIFIED' for x in results)}))

if __name__=='__main__':main()
