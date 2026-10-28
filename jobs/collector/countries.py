"""Shared publication contract: Android country filters use ISO 3166-1 alpha-2."""
import json
import unicodedata
from pathlib import Path

NAMES = json.loads((Path(__file__).resolve().parents[1] / "config/countries.json").read_text("utf-8"))


def key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or "")).casefold() if c.isalnum())


CODES = {key(name): code for code, name in NAMES.items()}
CODES.update({"uk": "GB", "greatbritain": "GB", "usa": "US", "unitedstatesofamerica": "US",
              "uae": "AE", "are": "AE", "ksa": "SA", "sau": "SA", "egy": "EG", "turkey": "TR",
              "bosniaandherzegovina": "BA", "southkorea": "KR", "korea": "KR",
              "مصر": "EG", "السعودية": "SA", "الامارات": "AE"})


def country_code(value):
    raw = str(value or "").strip()
    return raw.upper() if raw.upper() in NAMES else CODES.get(key(raw), "")


def country_name(value):
    return NAMES.get(country_code(value), str(value or "").strip())


def internal_job(job):
    """Read an old name-based or current ISO-based feed without changing identities."""
    result = {k: v for k, v in job.items() if k not in ("countryName", "countryCode")}
    if "country" in result:
        result["country"] = country_name(result["country"])
    return result


def published_job(job):
    """Keep display names separately; filter values exactly match user posts' ISO codes."""
    result = dict(job)
    code = country_code(job.get("country"))
    if code:
        result.update(country=code, countryCode=code, countryName=NAMES[code])
    return result
