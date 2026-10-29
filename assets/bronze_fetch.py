#!/usr/bin/env python3
"""Bronze layer: fetch HV URLs exactly as served and keep an append-only manifest.

Nothing is cleaned here. Every attempt is recorded, including dead links, so the
manifest doubles as evidence of what the site actually answered.

    uv run assets/bronze_fetch.py --contact you@example.com --out data/raw
    uv run assets/bronze_fetch.py --contact you@example.com --max 20 --delay 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

SITE = "https://www.hv.com.co"
SITEMAP_INDEX = f"{SITE}/sitemap_index.xml"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SKIP_EXT = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".webm",
    ".zip",
)
# Forms and personal-data intake pages: never part of a knowledge corpus.
DEFAULT_EXCLUDE = (
    "/envia-tu-hoja-de-vida/",
    "/contacto/",
    "/linea-etica/",
    "/facturacion-electronica",
)
SOFT_404 = re.compile(r"<title>\s*404|>404<|p[aá]gina no encontrada", re.I)


class RobotsPolicy:
    """RFC 9309 matcher with `*` and `$` support.

    `urllib.robotparser` treats `*` literally, so it silently allows
    `Disallow: /*?` and blocks `Allow: /wp-content/uploads/*`. HV uses both.
    """

    def __init__(self, text: str) -> None:
        self.groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] | None = None
        rules: list[tuple[bool, str]] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                if agents is None or rules:
                    agents, rules = [], []
                    self.groups.append((agents, rules))
                agents.append(value.lower())
            elif field in ("allow", "disallow") and agents is not None:
                rules.append((field == "allow", value))

    @staticmethod
    def _match_len(pattern: str, target: str) -> int:
        if not pattern:
            return 0
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        regex = "^" + regex + ("$" if anchored else "")
        return len(body) if re.match(regex, target) else -1

    def allows(self, ua: str, url: str) -> bool:
        token = ua.split("/")[0].strip().lower()
        chosen: str | None = None
        for agents, _ in self.groups:
            for agent in agents:
                matches = agent == "*" or agent in token
                if matches and (chosen is None or len(agent) > len(chosen)):
                    chosen = agent
        if chosen is None:
            return True

        parsed = urlparse(url)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query

        best_len, allowed = -1, True
        for agents, rules in self.groups:
            if chosen not in agents:
                continue
            for allow, pattern in rules:
                hit = self._match_len(pattern, target)
                if hit > best_len or (hit == best_len and hit >= 0 and allow):
                    best_len, allowed = hit, allow
        return allowed


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_ua(contact: str) -> str:
    return f"proyecto-ta-corpus/0.1 (+academic corpus; contact: {contact})"


def load_robots(session: requests.Session, ua: str, out: Path) -> RobotsPolicy:
    url = f"{SITE}/robots.txt"
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    (out / "robots.txt").write_text(
        f"# snapshot {utc_now()}\n# fetched with {ua}\n\n{resp.text}", encoding="utf-8"
    )
    return RobotsPolicy(resp.text)


def sitemap_locs(
    session: requests.Session,
    robots: RobotsPolicy,
    ua: str,
    url: str,
    seen: set[str],
    depth: int = 0,
) -> list[str]:
    if url in seen or depth > 3:
        return []
    seen.add(url)
    if not robots.allows(ua, url):
        print(f"skip sitemap (robots): {url}", file=sys.stderr)
        return []
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    locs = [n.text.strip() for n in root.findall(".//sm:loc", NS) if n.text and n.text.strip()]
    pages: list[str] = []
    for loc in locs:
        if loc.endswith(".xml"):
            pages.extend(sitemap_locs(session, robots, ua, loc, seen, depth + 1))
        else:
            pages.append(loc)
    return pages


def collect(
    session: requests.Session,
    robots: RobotsPolicy,
    ua: str,
    sitemaps: list[str],
    exclude: tuple[str, ...],
    include_pdfs: bool,
) -> tuple[list[str], dict[str, int], list[str]]:
    seen: set[str] = set()
    urls: list[str] = []
    for sitemap in sitemaps:
        urls.extend(sitemap_locs(session, robots, ua, sitemap, seen))

    host = urlparse(SITE).netloc
    allowed: list[str] = []
    blocked_examples: list[str] = []
    reasons = {"blocked": 0, "query": 0, "asset": 0, "excluded": 0, "pdf": 0, "foreign": 0}
    for url in dict.fromkeys(urls):
        parsed = urlparse(url)
        if parsed.netloc != host:
            reasons["foreign"] += 1
        elif "?" in url:
            reasons["query"] += 1  # robots: Disallow: /*?
        elif parsed.path.lower().endswith(SKIP_EXT):
            reasons["asset"] += 1
        elif any(part in url for part in exclude):
            reasons["excluded"] += 1
        elif parsed.path.lower().endswith(".pdf") and not include_pdfs:
            reasons["pdf"] += 1
        elif not robots.allows(ua, url):
            reasons["blocked"] += 1
            if len(blocked_examples) < 5:
                blocked_examples.append(url)
        else:
            allowed.append(url)
    return allowed, reasons, blocked_examples


def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/raw"))
    ap.add_argument("--contact", required=True, help="real email or URL that identifies you")
    ap.add_argument("--sitemaps", nargs="*", default=[SITEMAP_INDEX])
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--max", type=int, default=0, help="stop after N pages (0 = all)")
    ap.add_argument("--include-pdfs", action="store_true", help="download PDFs too")
    ap.add_argument("--exclude", nargs="*", default=list(DEFAULT_EXCLUDE))
    args = ap.parse_args()

    if args.delay < 1.5:
        print("refusing delay < 1.5s: be polite", file=sys.stderr)
        return 2

    ua = build_ua(args.contact)
    out: Path = args.out
    html_dir = out / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.jsonl"

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CO,es;q=0.9",
        }
    )

    robots = load_robots(session, ua, out)
    print(f"robots: {SITE}/robots.txt archived")

    urls, reasons, blocked_examples = collect(
        session, robots, ua, args.sitemaps, tuple(args.exclude), args.include_pdfs
    )
    print(f"collected {len(urls)} allowed URLs; filtered {reasons}")
    if args.max:
        urls = urls[: args.max]

    cache: dict[str, dict] = {}
    for row in read_manifest(manifest_path):
        if row.get("status") == "ok":
            cache[row["url"]] = row

    stats: dict[str, int] = {}
    stopped: str | None = None
    with manifest_path.open("a", encoding="utf-8") as fh:
        for i, url in enumerate(urls, 1):
            headers = {}
            prev = cache.get(url)
            if prev and prev.get("etag"):
                headers["If-None-Match"] = prev["etag"]
            if prev and prev.get("last_modified"):
                headers["If-Modified-Since"] = prev["last_modified"]

            row: dict = {"url": url, "fetched_at": utc_now()}
            try:
                resp = session.get(url, headers=headers, timeout=args.timeout)
                row["http"] = resp.status_code
                row["content_type"] = resp.headers.get("Content-Type", "")
                if resp.status_code == 304:
                    row["status"] = "unchanged"
                elif resp.status_code == 429:
                    wait = resp.headers.get("Retry-After", "60")
                    row["status"] = "rate_limited"
                    stopped = f"429 on {url}; Retry-After={wait}. Run stopped."
                elif resp.status_code != 200:
                    row["status"] = f"http_{resp.status_code}"
                else:
                    body = resp.content
                    sha = hashlib.sha256(body).hexdigest()
                    row.update(
                        sha256=sha,
                        bytes=len(body),
                        etag=resp.headers.get("ETag"),
                        last_modified=resp.headers.get("Last-Modified"),
                    )
                    is_html = "html" in row["content_type"].lower()
                    if is_html and SOFT_404.search(body[:20000].decode("utf-8", "ignore")):
                        row["status"] = "soft404"
                    else:
                        row["status"] = "ok"
                        ext = ".pdf" if not is_html else ".html"
                        rel = Path("html") / sha[:2] / f"{sha}{ext}"
                        target = out / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            target.write_bytes(body)
                        row["path"] = rel.as_posix()
            except requests.RequestException as exc:
                row["status"] = "error"
                row["error"] = exc.__class__.__name__
            finally:
                stats[row["status"]] = stats.get(row["status"], 0) + 1
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()

            print(f"[{i}/{len(urls)}] {row['status']:<12} {url}")
            if stopped:
                print(stopped, file=sys.stderr)
                break
            time.sleep(args.delay)

    summary = {
        "urls": len(urls),
        "statuses": stats,
        "filtered": reasons,
        "blocked_examples": blocked_examples,
        "robots_ua": ua,
        "manifest": str(manifest_path),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
