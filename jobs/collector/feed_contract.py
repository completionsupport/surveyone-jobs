"""Lossless publication within the already-shipped Android feed/cache limits."""
import json

MAX_FEED_BYTES = 4 * 1024 * 1024
MAX_JOBS = 10000


def cache_bytes(text):
    # The Android cache stores the feed as a JSON string with URL/ETag metadata.
    # Include conservative room for response headers without deleting job facts.
    envelope = json.dumps(dict(url='https://completionsupport.github.io/surveyone-jobs/jobs/jobs.json',
                               etag='x' * 256, modified='x' * 128, feed=text),
                          ensure_ascii=False, separators=(',', ':'))
    return len(envelope.encode('utf-8'))


def encode_feed(value, max_bytes=None):
    limit = MAX_FEED_BYTES if max_bytes is None else max_bytes
    if not isinstance(value, dict):
        raise ValueError('Feed must be an object')
    jobs = value.get('jobs') if isinstance(value, dict) else None
    if (value.get('version') != 1 or not isinstance(jobs, list) or
            value.get('totalJobs') != len(jobs) or len(jobs) > MAX_JOBS):
        raise ValueError('Feed violates the published Android row contract; nothing was changed')
    pretty = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    compact = json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n'
    for text in (pretty, compact):
        if len(text.encode('utf-8')) <= limit and cache_bytes(text) <= limit:
            return text
    raise ValueError('Complete feed exceeds published Android download/cache limits; no jobs were truncated or published')


def save_feed(path, value, max_bytes=None):
    text = encode_feed(value, max_bytes=max_bytes)  # Validate before touching the current published file.
    if path.exists() and path.read_text('utf-8') == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, 'utf-8')
    temporary.replace(path)
