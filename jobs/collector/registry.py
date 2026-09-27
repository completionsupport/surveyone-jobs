"""A source is a career board, not every filter, country or page on that board."""
from urllib.parse import urlsplit
from .model import normalize_url


def source_key(source):
    url = urlsplit(normalize_url(source["url"]))
    # Existing public ATS endpoints identify one employer in the path. Query filters and
    # pagination never turn the same employer into another independently counted source.
    return url.hostname + url.path.rstrip("/").casefold()


def enabled_sources(config):
    sources, keys, names = [], set(), set()
    for source in config.get("sources", []):
        if not source.get("enabled"):
            continue
        key = source_key(source)
        name = source.get("name", "").strip()
        if not name or key in keys or name.casefold() in names:
            raise ValueError("Missing name or duplicate source board")
        keys.add(key)
        names.add(name.casefold())
        sources.append(source)
    return sources


def rotated_sources(sources, cursor):
    if not sources:
        return []
    keys = [source_key(s) for s in sources]
    start = keys.index(cursor) + 1 if cursor in keys else 0
    return sources[start:] + sources[:start]
