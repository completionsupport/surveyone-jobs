"""Bounded, sequential, robots-aware access; no challenge or authentication bypass."""

import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
import requests
from .model import normalize_url


class Fetcher:
    def __init__(self, source, max_requests=12, max_bytes=2000000):
        self.source, self.remaining, self.max_bytes = source, max_requests, max_bytes
        self.hosts = set(source.get("allowedHosts", [])) | {
            urlsplit(source["url"]).hostname
        }
        self.robots, self.last = {}, 0.0
        self.session = requests.Session()
        self.session.trust_env = False
        self.agent = "SurveyOneJobs/1.0 (+public career metadata; robots respected)"

    def validate(self, url):
        url = normalize_url(url)
        parsed = urlsplit(url)
        host = parsed.hostname
        if host not in self.hosts or parsed.port not in (None, 443):
            raise ValueError("Unapproved host")
        if host in (
            "linkedin.com",
            "www.linkedin.com",
            "indeed.com",
            "www.indeed.com",
        ) or host.endswith((".linkedin.com", ".indeed.com")):
            raise ValueError("Disallowed source")
        for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(item[4][0]).is_global:
                raise ValueError("Non-public address")
        return url

    def request(self, url, robots=False, retry=True):
        url = self.validate(url)
        if self.remaining <= 0:
            raise ValueError("Source request budget reached")
        if not robots and not self.allowed(url):
            raise ValueError("Robots disallows access")
        if self.remaining <= 0:
            raise ValueError("Source request budget reached")
        time.sleep(max(0, 1.5 - (time.monotonic() - self.last)))
        self.remaining -= 1
        self.last = time.monotonic()
        try:
            response = self.session.get(
                url,
                timeout=(10, 20),
                stream=True,
                allow_redirects=False,
                headers={"User-Agent": self.agent},
            )
        except (requests.Timeout, requests.ConnectionError):
            if retry and self.remaining > 0:
                return self.request(url, robots=robots, retry=False)
            raise
        try:
            if response.is_redirect:
                target = urljoin(url, response.headers.get("Location", ""))
                return self.request(target, robots=robots, retry=False)
            if response.status_code in (404, 410):
                return response.status_code, ""
            response.raise_for_status()  # includes 403/429: stop; never evade/retry a ban
            chunks, size = [], 0
            for chunk in response.iter_content(32768):
                size += len(chunk)
                if size > self.max_bytes:
                    raise ValueError("Response too large")
                chunks.append(chunk)
            return response.status_code, b"".join(chunks).decode(
                "utf-8", errors="replace"
            )
        finally:
            response.close()

    def allowed(self, url):
        origin = "https://" + urlsplit(url).netloc
        if origin not in self.robots:
            status, body = self.request(origin + "/robots.txt", robots=True)
            parser = RobotFileParser()
            if status in (404, 410):
                parser.parse(["User-agent: *", "Allow: /"])
            else:
                parser.parse(body.splitlines())
            self.robots[origin] = parser
        parser = self.robots[origin]
        delay = parser.crawl_delay(self.agent) or parser.crawl_delay("*") or 0
        time.sleep(max(0, delay - (time.monotonic() - self.last)))
        return parser.can_fetch(self.agent, url)
