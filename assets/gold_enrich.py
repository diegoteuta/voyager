#!/usr/bin/env python3
"""Gold layer: Markdown + validated frontmatter. The only input an LLM may read.

Re-derives the content from Bronze HTML (never the live site), masks personal
data, validates metadata with pydantic and reconciles the three layers.

    uv run assets/gold_enrich.py --raw data/raw --silver data/processed --out data/gold
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import frontmatter
import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, HttpUrl, ValidationError

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?:\+57[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)(?:\d{3}[\s.-]?\d{4})"
    r"|\b01[\s-]?8000[\s-]?\d{3}[\s-]?\d{0,4}\b"
)
PUBLISHED = re.compile(r'property="article:published_time"\s+content="([^"]+)"')


class GoldMeta(BaseModel):
    source_url: HttpUrl
    title: str = Field(min_length=1)
    section: str = "home"
    published: str | None = None
    lang: str = "es"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetched_at: str
    tokens: int = Field(ge=1)
    pii_masked: int = 0


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def title_of(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    raw = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text() if soup.title else "")
    title = re.sub(r"\s*[-|]\s*Harinera del Valle.*$", "", raw or "").strip()
    return title or urlparse(url).path.strip("/") or "home"


def markdown_of(html: str, url: str) -> str:
    md = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    return (md or "").strip()


def count_tokens(text: str) -> int:
    try:
        import tiktoken  # ty: ignore[unresolved-import]  (optional dependency)

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, round(len(text) / 4))


def mask_pii(text: str) -> tuple[str, int]:
    text, emails = EMAIL.subn("[email-redacted]", text)
    text, phones = PHONE.subn("[phone-redacted]", text)
    return text, emails + phones


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--silver", type=Path, default=Path("data/processed"))
    ap.add_argument("--out", type=Path, default=Path("data/gold"))
    args = ap.parse_args()

    raw_rows = [
        json.loads(line)
        for line in (args.raw / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ok_rows = [
        r
        for r in raw_rows
        if r.get("status") == "ok" and r.get("sha256") and r.get("path", "").endswith(".html")
    ]
    # Two URLs can return byte-identical HTML: key by URL, keep sha only as evidence.
    raw_by_url = {r["url"]: r for r in ok_rows}
    raw_by_sha = {r["sha256"]: r for r in ok_rows}
    silver = [
        json.loads(line)
        for line in (args.silver / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kept = [r for r in silver if not r.get("dropped")]

    args.out.mkdir(parents=True, exist_ok=True)
    gold_rows: list[dict] = []
    written: set[str] = set()
    failures: list[str] = []

    for row in kept:
        source = raw_by_url.get(row["url"]) or raw_by_sha.get(row["sha256"])
        if not source:
            failures.append(f"sha256 not in bronze: {row['url']}")
            continue
        html = (args.raw / source["path"]).read_text(encoding="utf-8", errors="ignore")
        body = markdown_of(html, row["url"])
        if len(body) < 200:  # trafilatura markdown failed: keep silver text
            body = (args.silver / row["txt"]).read_text(encoding="utf-8", errors="ignore")
        body, masked = mask_pii(body)

        path = urlparse(row["url"]).path.strip("/")
        match = PUBLISHED.search(html)
        meta = {
            "source_url": row["url"],
            "title": title_of(html, row["url"]),
            "section": path.split("/")[0] if "/" in path else "home",
            "published": match.group(1) if match else None,
            "lang": "es",
            "sha256": row["sha256"],
            "fetched_at": source["fetched_at"],
            "tokens": count_tokens(body),
            "pii_masked": masked,
        }
        try:
            validated = GoldMeta(**meta)
        except ValidationError as exc:
            failures.append(f"invalid metadata for {row['url']}: {exc.errors()[0]['msg']}")
            continue

        record = validated.model_dump(mode="json")
        post = frontmatter.Post(body)
        post.metadata.update(record)
        filename = f"{row['slug']}.md"
        (args.out / filename).write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
        written.add(filename)
        gold_rows.append(record)

    # A page dropped in Silver must not survive in Gold as a stale file.
    if gold_rows:
        for stale in args.out.glob("*.md"):
            if stale.name != "report.md" and stale.name not in written:
                stale.unlink()

    with (args.out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for meta in gold_rows:
            fh.write(json.dumps(meta, ensure_ascii=False) + "\n")

    checks = {
        "gold_not_empty": len(gold_rows) > 0,
        "bronze_ok_equals_kept_plus_dropped": len(raw_by_url) == len(silver),
        "silver_kept_reaches_gold": len(kept) == len(gold_rows),
        "unique_source_urls": len({m["source_url"] for m in gold_rows}) == len(gold_rows),
        "every_sha_in_bronze": all(m["sha256"] in raw_by_sha for m in gold_rows),
        "tokens_positive": all(m["tokens"] > 0 for m in gold_rows),
    }
    passed = all(checks.values()) and not failures
    total_tokens = sum(m["tokens"] for m in gold_rows)

    report = [
        "# Gold reconciliation report",
        "",
        f"Generated: {utc_now()}",
        "",
        "| Layer | Count |",
        "|---|---|",
        f"| Bronze rows | {len(raw_rows)} |",
        f"| Bronze ok (html) | {len(raw_by_url)} |",
        f"| Silver kept | {len(kept)} |",
        f"| Silver dropped | {len(silver) - len(kept)} |",
        f"| Gold files | {len(gold_rows)} |",
        f"| Gold tokens | {total_tokens} |",
        "",
        "| Check | Result |",
        "|---|---|",
        *[f"| `{name}` | {'PASS' if ok else 'FAIL'} |" for name, ok in checks.items()],
    ]
    if failures:
        report += ["", "## Failures", "", *[f"- {f}" for f in failures]]
    (args.out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "gold": len(gold_rows),
                "tokens": total_tokens,
                "checks": checks,
                "failures": len(failures),
                "passed": passed,
                "report": str(args.out / "report.md"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
