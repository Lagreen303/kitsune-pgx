"""10x read-role detection from FASTQ lengths (SPEC §4.1, §5)."""
from __future__ import annotations

import gzip
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChemistryCall:
    chemistry: str
    cb_len: int
    umi_len: int
    r1_path: Path
    r2_path: Path
    r1_len: int
    r2_len: int


INDEX_LENS = frozenset({8, 10})
R1_LENS = frozenset({26, 28})
_MATE_RE = re.compile(r"_([123])\.(?:fastq|fq)(?:\.gz)?$", re.IGNORECASE)


class UnsupportedChemistry(ValueError):
    """Not 10x v2/v3 (e.g. 150+150 bulk RNA) — pipeline should SKIPPED, not FAILED."""


def _maybe_non_10x_skip(measured: list[tuple[Path, int]]) -> None:
    if not measured:
        return
    lens = {str(p.name): n for p, n in measured}
    lengths = [n for _, n in measured]
    if any(n in R1_LENS for n in lengths):
        return
    if len(measured) == 2 and all(n >= 75 for n in lengths):
        raise UnsupportedChemistry(f"non-10x paired-end (no 26/28 bp R1): {lens}")
    if len(measured) >= 2 and max(lengths) >= 75 and min(lengths) >= 75:
        raise UnsupportedChemistry(f"non-10x library (no barcode read): {lens}")


def _first_read_len(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="ascii", errors="replace") as f:
        f.readline()
        seq = f.readline().strip()
    return len(seq)


def _read_length_counts(path: Path, max_reads: int = 400) -> Counter[int]:
    opener = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
    counts: Counter[int] = Counter()
    with opener(path, "rt", encoding="ascii", errors="replace") as f:
        for _ in range(max_reads):
            header = f.readline()
            if not header:
                break
            seq = f.readline().strip()
            f.readline()
            f.readline()
            if seq:
                counts[len(seq)] += 1
    return counts


def representative_read_len(path: Path) -> int:
    """Modal read length (first record is often misleading on SRA 3-file dumps)."""
    counts = _read_length_counts(path)
    if not counts:
        return _first_read_len(path)
    top_freq = counts.most_common(1)[0][1]
    tied = [ln for ln, c in counts.items() if c == top_freq]
    if any(ln in R1_LENS for ln in tied):
        return next(ln for ln in tied if ln in R1_LENS)
    if any(ln >= 50 for ln in tied):
        return max(ln for ln in tied if ln >= 50)
    return max(tied)


def _call_from_lens(r1_path: Path, r2_path: Path, r1_len: int, r2_len: int) -> ChemistryCall:
    if r2_len < 28:
        lens = {r1_path.name: r1_len, r2_path.name: r2_len}
        raise ValueError(f"Ambiguous FASTQ roles (lengths): {lens}; cDNA_len={r2_len}")
    if r1_len == 26:
        return ChemistryCall("v2", 16, 10, r1_path, r2_path, r1_len, r2_len)
    if r1_len == 28:
        return ChemistryCall("v3", 16, 12, r1_path, r2_path, r1_len, r2_len)
    raise ValueError(f"Unsupported R1 length {r1_len} (not 26 or 28)")


def _mate_index(path: Path) -> int | None:
    m = _MATE_RE.search(path.name)
    return int(m.group(1)) if m else None


def _classify_pair(measured: list[tuple[Path, int]]) -> ChemistryCall:
    r1_candidates = [p for p, n in measured if n in R1_LENS]
    if len(r1_candidates) != 1:
        _maybe_non_10x_skip(measured)
        lens = {str(p.name): n for p, n in measured}
        raise ValueError(
            f"Ambiguous FASTQ roles (lengths): {lens}; barcode_hits={len(r1_candidates)}"
        )
    r1_path = r1_candidates[0]
    r1_len = next(n for p, n in measured if p == r1_path)
    others = [(p, n) for p, n in measured if p != r1_path]
    non_index = [(p, n) for p, n in others if n not in INDEX_LENS]
    pool = non_index if non_index else others
    if len(pool) == 1:
        r2_path, r2_len = pool[0]
    else:
        r2_path, r2_len = max(pool, key=lambda item: item[1])
    return _call_from_lens(r1_path, r2_path, r1_len, r2_len)


def _classify_three_file_sra(paths: list[Path]) -> ChemistryCall | None:
    """SRA --split-files --include-technical: _1 index, _2 barcode, _3 cDNA."""
    by_mate = {_mate_index(p): p for p in paths}
    if set(by_mate) != {1, 2, 3}:
        return None
    i_len = representative_read_len(by_mate[1])
    if i_len not in INDEX_LENS and i_len > 12:
        return None
    r1_path, r2_path = by_mate[2], by_mate[3]
    r1_len = representative_read_len(r1_path)
    r2_len = representative_read_len(r2_path)
    if r1_len in R1_LENS and r2_len >= 28:
        return _call_from_lens(r1_path, r2_path, r1_len, r2_len)
    if r2_len in R1_LENS and r1_len >= 28:
        return _call_from_lens(r2_path, r1_path, r2_len, r1_len)
    return None


def classify_fastqs(paths: list[Path]) -> ChemistryCall:
    paths = [p for p in paths if p.is_file()]
    if len(paths) < 2:
        raise ValueError(f"Need at least 2 FASTQs, got {len(paths)}")

    if len(paths) == 3:
        three = _classify_three_file_sra(paths)
        if three is not None:
            return three

    measured = [(p, representative_read_len(p)) for p in paths]
    non_index = [(p, n) for p, n in measured if n not in INDEX_LENS]
    if len(non_index) >= 2:
        try:
            return _classify_pair(non_index)
        except ValueError:
            pass
    return _classify_pair(measured)
