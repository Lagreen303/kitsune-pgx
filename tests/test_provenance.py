from kitsune_pgx.sync.provenance import parse_utc_iso, provenance_valid_for_align


def test_provenance_requires_finished_after_align_start() -> None:
    prov = {
        "finished_at": "2026-10-14T08:00:00+00:00",
        "gencode_idx": "/data/STAR_index_gencode49",
    }
    assert provenance_valid_for_align(
        prov,
        align_started_at="2026-10-14T07:00:00+00:00",
        expected_gencode_idx="/data/STAR_index_gencode49",
    )
    assert not provenance_valid_for_align(
        prov,
        align_started_at="2026-10-14T09:00:00+00:00",
        expected_gencode_idx="/data/STAR_index_gencode49",
    )


def test_provenance_rejects_legacy_without_finished_at() -> None:
    assert not provenance_valid_for_align(
        {"gencode_idx": "/data/STAR_index_gencode49"},
        align_started_at="2026-10-14T07:00:00+00:00",
        expected_gencode_idx="/data/STAR_index_gencode49",
    )


def test_provenance_gencode_idx_must_match() -> None:
    prov = {
        "finished_at": "2026-10-14T08:00:00+00:00",
        "gencode_idx": "/data/STAR_index",
    }
    assert not provenance_valid_for_align(
        prov,
        align_started_at="2026-10-14T07:00:00+00:00",
        expected_gencode_idx="/data/STAR_index_gencode49",
    )


def test_parse_utc_iso_z_suffix() -> None:
    assert parse_utc_iso("2026-10-14T08:00:00Z").isoformat() == "2026-10-14T08:00:00+00:00"
