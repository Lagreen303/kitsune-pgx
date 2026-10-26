import importlib.util
from pathlib import Path

_mod = importlib.util.spec_from_file_location(
    "noncode_v7_download",
    Path(__file__).resolve().parents[1] / "scripts" / "noncode_v7_download.py",
)
_noncode = importlib.util.module_from_spec(_mod)
assert _mod.loader
_mod.loader.exec_module(_noncode)
is_pbmc_tissue = _noncode.is_pbmc_tissue
is_healthy_disease = _noncode.is_healthy_disease


def test_pbmc_tissue_variants() -> None:
    assert is_pbmc_tissue("Peripheral Blood Mononuclear Cell")
    assert is_pbmc_tissue("Peripheral blood mononuclear cell(PBMC)")
    assert is_pbmc_tissue("PBMC")
    assert is_pbmc_tissue("Rectum; PBMC; ileum")
    assert is_pbmc_tissue("Needle Biopsy (kidney); PBMC")
    assert is_pbmc_tissue("PBMCs; FNAs")
    assert is_pbmc_tissue("Peripheral blood (pDCs)")
    assert not is_pbmc_tissue("Peripheral nerves")
    assert not is_pbmc_tissue("Peripheral blood")  # not PBMC-specific alone


def test_healthy_disease() -> None:
    assert is_healthy_disease("Healthy")
    assert is_healthy_disease("Health_adult")
    assert not is_healthy_disease("Acute myeloid leukemia")
