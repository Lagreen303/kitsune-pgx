#!/usr/bin/env python3
"""Probe NONCODE v7 site for scRNA download URLs (run from PGX/Iridis)."""
from __future__ import annotations

import re
import sys
from urllib.request import Request, urlopen

URLS = [
    "https://v7.noncode.org/download.php",
    "https://v7.noncode.org/",
    "https://v7.noncode.org/singlecell.php",
    "https://v7.noncode.org/single_cell.php",
]


def fetch(url: str, timeout: int = 60) -> str:
    req = Request(url, headers={"User-Agent": "kitsune-pgx/0.1 (research)"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main() -> None:
    for url in URLS:
        print(f"\n=== {url} ===")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"FAIL: {e}")
            continue
        print(f"length={len(html)}")
        for pat in (
            r'href=["\']([^"\']+)["\']',
            r'url\s*:\s*["\']([^"\']+)["\']',
            r'"(https?://[^"]+\.(?:zip|gz|h5|h5ad|rds|tar)[^"]*)"',
        ):
            hits = re.findall(pat, html, flags=re.I)
            interesting = [
                h
                for h in hits
                if any(
                    k in h.lower()
                    for k in (
                        "download",
                        "single",
                        "cell",
                        "gse",
                        "matrix",
                        "data",
                        ".zip",
                        ".h5",
                        "ajax",
                        "api",
                    )
                )
            ]
            if interesting:
                print(f"  pattern {pat[:30]}... ({len(interesting)} hits)")
                for h in interesting[:25]:
                    print(f"    {h}")
        if "single" in html.lower() or "GSE" in html:
            print("  (page mentions single-cell / GSE)")


if __name__ == "__main__":
    main()
