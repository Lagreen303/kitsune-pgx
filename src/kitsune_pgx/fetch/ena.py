"""ENA filereport download (primary fetch path)."""
from __future__ import annotations

import csv
import hashlib
import io
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FILEREPORT = "https://www.ebi.ac.uk/ena/portal/api/filereport"


@dataclass(frozen=True)
class EnaFile:
    url: str
    md5: str
    nbytes: int


def _http_get(url: str, timeout: int = 300, *, retries: int = 5) -> bytes:
    req = Request(url, headers={"User-Agent": "kitsune-pgx/0.1"})
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504) or attempt >= retries - 1:
                raise
        except URLError as e:
            last = e
            if attempt >= retries - 1:
                raise
        time.sleep(min(120, 15 * (2**attempt)))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last


def filereport_rows(srr: str) -> list[dict[str, str]]:
    qs = urlencode(
        {
            "accession": srr,
            "result": "read_run",
            "fields": "run_accession,fastq_ftp,fastq_md5,fastq_bytes,read_count,submitted_ftp,submitted_format",
            "format": "tsv",
        }
    )
    text = _http_get(f"{FILEREPORT}?{qs}").decode()
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return []
    return list(csv.DictReader(lines, delimiter="\t"))


def parse_ena_fastqs(row: dict[str, str]) -> list[EnaFile]:
    ftps = (row.get("fastq_ftp") or "").strip()
    md5s = (row.get("fastq_md5") or "").strip().split(";")
    sizes = (row.get("fastq_bytes") or "").strip().split(";")
    if not ftps or ftps == "NA":
        return []
    urls = ftps.split(";")
    out: list[EnaFile] = []
    for i, rel in enumerate(urls):
        rel = rel.strip()
        if not rel:
            continue
        md5 = md5s[i].strip() if i < len(md5s) else ""
        try:
            nbytes = int(sizes[i]) if i < len(sizes) and sizes[i].strip() else 0
        except ValueError:
            nbytes = 0
        out.append(EnaFile(url=f"https://{rel}", md5=md5, nbytes=nbytes))
    return out


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_url(url: str, dest: Path, *, retries: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: subprocess.CalledProcessError | None = None
    for attempt in range(retries):
        try:
            subprocess.run(
                [
                    "wget",
                    "-q",
                    "--timeout=120",
                    "--tries=1",
                    "-O",
                    str(dest),
                    url,
                ],
                check=True,
                capture_output=True,
            )
            if dest.stat().st_size > 0:
                return
            dest.unlink(missing_ok=True)
            raise ValueError(f"empty download from {url}")
        except (subprocess.CalledProcessError, ValueError) as e:
            last_err = e if isinstance(e, subprocess.CalledProcessError) else None
            dest.unlink(missing_ok=True)
            if attempt < retries - 1:
                time.sleep(45 * (attempt + 1))
    raise RuntimeError(f"wget failed after {retries} attempts: {url}") from last_err


def fetch_ena_fastqs(srr: str, dest_dir: Path, *, verify_md5: bool = True) -> tuple[list[Path], int]:
    rows = filereport_rows(srr)
    if not rows:
        raise FileNotFoundError(f"ENA filereport empty for {srr}")
    files = parse_ena_fastqs(rows[0])
    if not files:
        raise FileNotFoundError(f"ENA has no fastq_ftp for {srr}")
    paths: list[Path] = []
    total = 0
    for i, ef in enumerate(files):
        name = ef.url.rsplit("/", 1)[-1]
        dest = dest_dir / name
        if not dest.is_file() or dest.stat().st_size == 0:
            download_url(ef.url, dest)
        if verify_md5 and ef.md5:
            got = _md5_file(dest)
            if got.lower() != ef.md5.lower():
                dest.unlink(missing_ok=True)
                raise ValueError(f"MD5 mismatch for {dest.name}: expected {ef.md5}, got {got}")
        paths.append(dest)
        total += dest.stat().st_size
    return paths, total
