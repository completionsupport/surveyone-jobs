import json
import re
import unicodedata
from pathlib import Path
from .countries import country_code

TAXONOMY = json.loads((Path(__file__).resolve().parents[1] / "config/job-taxonomy.json").read_text("utf-8"))


def key(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip()


def city_name(value, country):
    raw = str(value or "").strip()
    for name, aliases in TAXONOMY["cities"].get(country_code(country), {}).items():
        if key(raw) in {key(alias) for alias in aliases}:
            return name
    return raw


def category_name(value):
    raw = str(value or "").strip()
    for name, aliases in TAXONOMY["categories"].items():
        if key(raw) in {key(alias) for alias in aliases}:
            return name
    return raw


def filter_job(job):
    result = dict(job)
    if "city" in result:
        city = result["city"]
        if not city and result.get("country"):
            candidate = str(result.get("location") or "").split(",", 1)[0].strip()
            canonical = city_name(candidate, result["country"])
            # Infer only a known city, or the explicit city part of a comma-separated
            # location. Do not invent a city for All Sites, Worldwide or country-only rows.
            if canonical != candidate or canonical in TAXONOMY["cities"].get(country_code(result["country"]), {}):
                city = canonical
        result["city"] = city_name(city, result.get("country"))
    if "category" in result:
        result["category"] = category_name(result["category"])
    return result
