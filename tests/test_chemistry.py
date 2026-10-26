import gzip
from pathlib import Path

import pytest

from kitsune_pgx.fetch.chemistry import UnsupportedChemistry, classify_fastqs


def _write_gz(path: Path, seq: str) -> None:
    with gzip.open(path, "wt") as f:
        f.write(f"@r\n{seq}\n+\n\n")


def test_classify_v3_pair(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.fastq.gz"
    r2 = tmp_path / "r2.fastq.gz"
    _write_gz(r1, "N" * 28)
    _write_gz(r2, "N" * 90)
    c = classify_fastqs([r1, r2])
    assert c.chemistry == "v3"
    assert c.umi_len == 12


def test_classify_v2_short_r2_first_read(tmp_path: Path) -> None:
    """ENA/SRA sometimes yield R2 first-read length 49 (still valid 10x v2)."""
    r1 = tmp_path / "SRR_x_1.fastq.gz"
    r2 = tmp_path / "SRR_x_2.fastq.gz"
    _write_gz(r1, "N" * 26)
    _write_gz(r2, "N" * 49)
    c = classify_fastqs([r1, r2])
    assert c.chemistry == "v2"
    assert c.umi_len == 10


def _write_multi_gz(path: Path, seqs: list[str]) -> None:
    with gzip.open(path, "wt") as f:
        for i, seq in enumerate(seqs):
            f.write(f"@r{i}\n{seq}\n+\n\n")


def test_classify_sra_three_file_v3(tmp_path: Path) -> None:
    """GSE144568-style SRA split: _1 index, _2 R1, _3 R2 (modal lengths, not first read)."""
    f1 = tmp_path / "SRR11026520_1.fastq.gz"
    f2 = tmp_path / "SRR11026520_2.fastq.gz"
    f3 = tmp_path / "SRR11026520_3.fastq.gz"
    _write_gz(f1, "N" * 8)
    _write_gz(f2, "N" * 28)
    _write_multi_gz(f3, ["N" * 14, "N" * 90, "N" * 91])
    c = classify_fastqs([f1, f2, f3])
    assert c.chemistry == "v3"
    assert c.r1_path == f2
    assert c.r2_path == f3


def test_skip_non_10x_150_pair(tmp_path: Path) -> None:
    r1 = tmp_path / "SRR_x_1.fastq.gz"
    r2 = tmp_path / "SRR_x_2.fastq.gz"
    _write_gz(r1, "N" * 150)
    _write_gz(r2, "N" * 150)
    with pytest.raises(UnsupportedChemistry):
        classify_fastqs([r1, r2])
