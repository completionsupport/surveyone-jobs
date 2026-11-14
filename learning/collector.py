"""Public learning catalogue. RSS discovery + official oEmbed verification; no video downloads."""
from __future__ import annotations
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
TERMS = re.compile(r"survey|total.?station|gnss|rtk|rinex|traverse|levell?ing|civil\s*3d|qgis|arcgis|autocad|coordinate|stake.?out|resection|landstar|survstar|captivate|magnet field|trimble access|\btbc\b|business center|surfer|point.?cloud|مساح|ميزان|توتال|احداث|إحداث|سيفيل|سيفل|توقيع|ترافرس|ليفل|لاند.?ستار|اوتوكاد|أتوكاد|أوتوكاد|ترمبل|ليكا|لايكا|sokkia|topcon", re.I)
TEACHING = re.compile(r"how\s+(?:to|do|can you)\b|tutorial|learn|lesson|setup|set.?up|setting|guide|workflow|training|orient|check|resection|introduction|getting started|\btips?\b|creating|import|export|processing|measur|stakeout|شرح|دورة|تعلم|تعلّم|تعليم|درس|خطوات|طريقة|كيفية|كيف |الدرس|حساب|رصد|إنشاء|انشاء|استيراد|تصدير|استخراج|الرفع|تطبيق|الربط|ضبط", re.I)
BROADCAST = re.compile(r"بث.{0,12}مباشر|livestream|started streaming|intergeo|anniversary|black friday|giveaway|عرض خاص|عيد مبارك|crack|keygen|كراك|تهكير|تفعيل.*دائم", re.I)
ALIASES = [
    (r'autocad|اوتوكاد|اوتوكاد|أوتوكاد|أتوكاد', ['AutoCAD', 'CAD', 'كاد', 'اوتوكاد']),
    (r'civil\s*3d|سيفيل|سيفل', ['Civil 3D', 'سيفيل', 'سيفل']),
    (r'qgis|arcgis|\bgis\b', ['GIS', 'نظم المعلومات الجغرافية']),
    (r'\btbc\b|business center', ['TBC', 'Trimble Business Center', 'معالجة الرصد']),
    (r'total.?station|توتال|توتل', ['Total Station', 'توتال ستيشن', 'المحطة المتكاملة']),
    (r'levell?ing|staff|ميزان|القامة|القامه', ['Leveling', 'ميزانية', 'الميزان']),
    (r'leica|ليكا|لايكا', ['Leica', 'لايكا', 'ليكا']),
    (r'topcon|توبكون|توبكن', ['Topcon', 'توبكون']),
    (r'sokkia|سوكيا', ['Sokkia', 'سوكيا']),
    (r'chcnav|landstar|\bchc\b|لاند.?ستار', ['CHCNAV', 'LandStar', 'لاند ستار']),
    (r'comnav|sino.?gnss|survey master', ['ComNav', 'SinoGNSS', 'Survey Master', 'كومناف']),
    (r'trimble|ترمبل|تريمبل', ['Trimble', 'ترمبل']),
    (r'gnss|rtk|gps|ppk|rinex|static', ['GNSS', 'GPS', 'الرصد بالأقمار الصناعية']),
]
def learning_tags(title: str, extra=()) -> list[str]:
    tags = list(extra)
    for pattern, values in ALIASES:
        if re.search(pattern, title, re.I): tags.extend(values)
    return list(dict.fromkeys(tags))[:32]
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

def relevant(title: str) -> bool:
    if re.search(r'\$\s*\d|\b(?:case study|mechanical engineers|is here|we hosted)\b|in one workflow|دورة.{0,40}من الصفر إلى الاحتراف', title, re.I):
        return False
    # A product name, "workflow", "check" or "stakeout" alone is not a lesson.
    instruction = re.search(r'how\s+(?:to|do|can you)\b|tutorial|lesson|setup|set.?up|settings?|guide|orientation|resection|getting started|\btips?\b|creating|import|export|processing|شرح|تعلم|تعلّم|تعليم|درس|خطوات|طريقة|كيفية|كيف |حساب|إنشاء|انشاء|استيراد|تصدير|استخراج|تطبيق|الربط|ضبط', title, re.I)
    return bool(TERMS.search(title) and instruction and not BROADCAST.search(title))

def fetch(url: str, max_bytes: int = 2_000_000) -> bytes:
    # URLs are constructed exclusively from validated IDs; catalogue content cannot
    # supply request hosts, redirects, cookies or credentials.
    request = urllib.request.Request(url, headers={"User-Agent": "SurveyOne-Learning-Catalog/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        if urllib.parse.urlsplit(response.url).hostname not in {"www.youtube.com", "youtube.com"}:
            raise ValueError("Unexpected metadata host")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Metadata too large")
        return data

def discover(xml: bytes, source: dict, now: dt.datetime) -> list[dict]:
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("Entities are not allowed")
    root = ET.fromstring(xml)
    # YouTube's feed root omits UC, while entry channel IDs include it.
    if root.findtext("yt:channelId", namespaces=NS) not in {source["channelId"], source["channelId"][2:]}:
        raise ValueError("RSS channel mismatch")
    rows = []
    for item in root.findall("a:entry", NS)[:30]:
        if item.findtext("yt:channelId", source["channelId"], NS) != source["channelId"]:
            continue
        video = item.findtext("yt:videoId", "", NS)
        title = " ".join(item.findtext("a:title", "", NS).split())[:180]
        if not VIDEO.fullmatch(video) or not relevant(title):
            continue
        if source["language"] == "ar" and not re.search(r'[\u0600-\u06ff]', title):
            continue
        if source["language"] == "en" and (re.search(r'[\u0600-\u06ff\u0400-\u04ff\u0900-\u097f\u4e00-\u9fff]', title) or re.search(r'\b(hindi|urdu|español|português)\b', title, re.I)):
            continue
        try:
            date = dt.datetime.fromisoformat(item.findtext("a:published", "", NS).replace("Z", "+00:00"))
            if date.tzinfo is None or date > now + dt.timedelta(days=1):
                continue
        except ValueError:
            continue
        topic = source["topic"]
        if re.search(r"qgis|civil\s*3d|autocad|سيفيل", title, re.I):
            topic = "SOFTWARE"
        elif re.search(r"gnss|rtk|rinex|static|gps|ppk", title, re.I):
            topic = "GNSS"
        rows.append({"id": video, "videoId": video, "titleEn": title, "titleAr": title,
                     "summaryEn": "A practical lesson from this learning source. Original video language is shown on the card.",
                     "summaryAr": "شرح تطبيقي من هذا المصدر التعليمي. لغة الفيديو الأصلية موضّحة على البطاقة.",
                     "source": source["name"], "topic": topic, "level": "PRACTICAL",
                     "language": source["language"], "url": f"https://www.youtube.com/watch?v={video}",
                     "publishedAt": date.isoformat(), "sourceChannelId": source["channelId"],
                     "tags": learning_tags(title, source.get("tags", [])), "discovered": True})
    return rows

def verify(row: dict, now_ms: int, request=fetch) -> tuple[dict | None, str]:
    video = row.get("videoId")
    if not video:
        return row, "curated-guide"
    if not VIDEO.fullmatch(video) or row.get("url") != f"https://www.youtube.com/watch?v={video}":
        return None, "invalid-id"
    url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": row["url"], "format": "json"})
    try:
        metadata = json.loads(request(url))
        if metadata.get("type") != "video" or metadata.get("provider_name") != "YouTube" or not metadata.get("author_name"):
            raise ValueError("Invalid video metadata")
        result = dict(row, source=metadata["author_name"].strip()[:160], verifiedAtMs=now_ms)
        if row.get("discovered"):
            result["titleEn"] = result["titleAr"] = str(metadata["title"]).strip()[:180]
        return result, "verified"
    except urllib.error.HTTPError as error:
        # Removed/private/non-embeddable videos must not remain in the public feed.
        code = error.code
        error.close()
        if code in (400, 401, 403, 404, 410):
            return None, "unavailable"
    except (ValueError, OSError, TimeoutError):
        pass
    last_verified = row.get("verifiedAtMs", 0)
    if isinstance(last_verified, int) and 0 < now_ms - last_verified < 7 * 86400_000:
        return row, "temporarily-unverified"
    return None, "verification-failed"

def collect() -> None:
    now = dt.datetime.now(dt.timezone.utc); now_ms = int(now.timestamp() * 1000)
    config = json.loads((ROOT / "learning/sources.json").read_text("utf-8"))
    channels = [s for s in config["channels"] if s.get("enabled", True)]
    enabled = {s["channelId"] for s in channels}
    seeds = json.loads((ROOT / "learning/curated.json").read_text("utf-8"))
    output = ROOT / "public/learning/catalog.json"
    old = json.loads(output.read_text("utf-8")) if output.exists() else {"items": []}
    previous = {r["id"]: r for r in old["items"]}
    rows = {r["id"]: {**previous.get(r["id"], {}), **r} for r in seeds}
    diagnostics = {"generatedAtMs": now_ms, "sources": [], "verification": {}}
    def channel(source):
        if not CHANNEL.fullmatch(source["channelId"]):
            raise ValueError("Invalid channel ID")
        try:
            data = fetch("https://www.youtube.com/feeds/videos.xml?channel_id=" + source["channelId"])
            return discover(data, source, now), {"channelId": source["channelId"], "ok": True}
        except (ValueError, OSError, ET.ParseError, TimeoutError) as error:
            return [], {"channelId": source["channelId"], "ok": False, "error": type(error).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for items, status in pool.map(channel, channels):
            diagnostics["sources"].append(dict(status, matchingLessons=len(items)))
            for row in items:
                rows.setdefault(row["id"], {**previous.get(row["id"], {}), **row})
        for row in previous.values():
            if row.get("discovered") and row.get("sourceChannelId") in enabled and relevant(row["titleEn"]):
                rows.setdefault(row["id"], row)
        candidates = list(rows.values())[:600]
        checked = []
        for row, status in pool.map(lambda r: verify(r, now_ms), candidates):
            diagnostics["verification"][status] = diagnostics["verification"].get(status, 0) + 1
            if row:
                checked.append(row)
    if not any(r.get("videoId") for r in checked):
        raise RuntimeError("No verified videos; preserving the previous catalogue")
    data = {"schemaVersion": 1, "generatedAtMs": now_ms, "refreshHours": 6,
            "items": checked, "sourceCount": len(channels)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(serialized.encode('utf-8')) > 1_048_576:
        raise RuntimeError("Catalogue exceeds app download budget; previous feed preserved")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(output)
    (ROOT / "learning/last-run.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    print(json.dumps({"lessons": len(checked), "videos": sum(bool(r.get("videoId")) for r in checked), **diagnostics}))

if __name__ == "__main__":
    collect()
