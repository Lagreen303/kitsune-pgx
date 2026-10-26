from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def parse_utc_iso(ts: str) -> datetime:
    """Parse ledger/provenance timestamps (ISO 8601, UTC)."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def provenance_valid_for_align(
    prov: dict[str, Any],
    *,
    align_started_at: str,
    expected_gencode_idx: str | None = None,
) -> bool:
    """True if provenance was written for the current ALIGNING attempt."""
    finished = prov.get("finished_at")
    if not finished or not str(finished).strip():
        return False
    try:
        if parse_utc_iso(str(finished)) < parse_utc_iso(align_started_at):
            return False
    except (TypeError, ValueError):
        return False
    if expected_gencode_idx:
        idx = str(prov.get("gencode_idx") or "")
        if idx != str(expected_gencode_idx):
            return False
    return True


def provenance_from_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
