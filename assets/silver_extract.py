#!/usr/bin/env python3
"""Silver layer: strip chrome, normalize text, drop thin and near-duplicate pages.

Reads the Bronze manifest, never the live site.

    uv run assets/silver_extract.py --raw data/raw --out data/processed --min-chars 400
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import ftfy
import trafilatura
from bs4 import BeautifulSoup
from datasketch import MinHash, MinHashLSH

# Only structural chrome and exact Elementor/consent classes: broad `[class*=...]`
# selectors nuke this site (a wrapper class contains "cookie" and holds the page).
BOILERPLATE = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "form",
    ".elementor-location-header",
    ".elementor-location-footer",
    ".elementor-popup-modal",
    ".pum-overlay",
    ".pum-container",
)
FOOTER_LINE = re.compile(
    r"(todos los derechos reservados|prohibida su reproducci[oó]n|"
    r"pol[ií]tica de cookies|configuraci[oó]n de cookies)",
    re.I,
)

# The fallback path has no semantic model, so it needs the structural chrome gone.
FALLBACK_SELECTORS = (*BOILERPLATE, "nav", "header", "footer", ".breadcrumb")


def slugify(url: str, sha: str) -> str:
    path = urlparse(url).path.strip("/") or "home"
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:80]
    return f"{slug}-{sha[:8]}"


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.select(",".join(FALLBACK_SELECTORS)):
        tag.decompose()
    return str(soup)


def extract(html: str, url: str) -> str:
    # trafilatura is boilerplate-aware: give it the raw HTML.
    text = trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        include_comments=False,
        include_tables=True,
    )
    if text and len(text) >= 200:
        return text
    # Fallback for pages it rejects: strip structural chrome, keep the text.
    return BeautifulSoup(clean_html(html), "lxml").get_text("\n", strip=True)


def normalize(text: str) -> str:
    text = ftfy.fix_text(text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if len(line) < 3 or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]", line):
            continue
        if FOOTER_LINE.search(line):
            continue
        lines.append(line)
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def shingles(text: str, k: int = 5) -> list[bytes]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < k:
        return [" ".join(words).encode("utf-8")] if words else []
    return [" ".join(words[i : i + k]).encode("utf-8") for i in range(len(words) - k + 1)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    ap.add_argument("--min-chars", type=int, default=400)
    ap.add_argument("--threshold", type=float, default=0.85)
    args = ap.parse_args()

    rows = [
        json.loads(line)
        for line in (args.raw / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ok = [r for r in rows if r.get("status") == "ok" and r.get("path", "").endswith(".html")]
    txt_dir = args.out / "txt"
    txt_dir.mkdir(parents=True, exist_ok=True)

    lsh = MinHashLSH(threshold=args.threshold, num_perm=128)
    out_rows: list[dict] = []
    kept = thin = dups = 0

    for row in ok:
        slug = slugify(row["url"], row["sha256"])
        html = (args.raw / row["path"]).read_text(encoding="utf-8", errors="ignore")
        text = normalize(extract(html, row["url"]))
        base = {"url": row["url"], "sha256": row["sha256"], "slug": slug}

        if len(text) < args.min_chars:
            out_rows.append({**base, "chars": len(text), "dropped": "thin"})
            thin += 1
            continue

        mh = MinHash(num_perm=128)
        for sh in shingles(text):
            mh.update(sh)
        match = lsh.query(mh)
        if match:
            out_rows.append(
                {**base, "chars": len(text), "dropped": "duplicate", "duplicate_of": match[0]}
            )
            dups += 1
            continue

        lsh.insert(slug, mh)
        (txt_dir / f"{slug}.txt").write_text(text, encoding="utf-8")
        out_rows.append({**base, "chars": len(text), "dropped": None, "txt": f"txt/{slug}.txt"})
        kept += 1

    with (args.out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "bronze_ok": len(ok),
        "kept": kept,
        "thin": thin,
        "duplicates": dups,
        "out": str(args.out),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if kept == 0:
        print("no pages survived: check --min-chars and the Bronze manifest", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
