"""Tagging Log importer — the discipline gate for Phase 2's Learning Memory.

A typo'd concept splits one angle's history into two and teaches the system
something false. These tests exist so that never happens quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from annems.tagging_log import (
    EXAMPLE_MARKER,
    read_rows,
    to_creative_row,
    validate,
)

WORKBOOK = Path(__file__).resolve().parents[1] / "docs" / "Creative_Tagging_Log_Annems.xlsx"


def good_row(**overrides) -> dict:
    row = {
        "tarikh_mula": "2026-09-14",
        "nama_ad": "SD_FounderTrap_V01",
        "kempen": "Sesi Diagnosis Sept",
        "konsep": "Founder Trap",
        "angle": "Semua keputusan tunggu founder",
        "format": "Static 4:5",
        "awareness": "Problem Aware",
        "status": "Aktif",
        "tarikh_tamat": "",
        "keputusan": "",
        "catatan": "",
    }
    row.update(overrides)
    return row


class TestValidation:
    def test_accepts_a_well_formed_row(self):
        assert validate(good_row(), 2) is None

    def test_rejects_an_unknown_concept(self):
        error = validate(good_row(konsep="Founder Trapp"), 5)
        assert error is not None and "Baris 5" in error

    def test_rejects_an_unknown_format(self):
        assert validate(good_row(format="Reel"), 3) is not None

    def test_rejects_an_unknown_awareness_level(self):
        assert validate(good_row(awareness="Warm"), 3) is not None

    def test_rejects_a_row_with_no_ad_name(self):
        """Without the Meta ad name there is nothing to join performance to."""
        assert validate(good_row(nama_ad=""), 4) is not None

    def test_rejects_a_row_with_no_angle(self):
        assert validate(good_row(angle=""), 4) is not None


class TestMapping:
    def test_maps_to_the_creatives_schema(self):
        payload = to_creative_row(good_row())
        assert payload["concept"] == "Founder Trap"
        assert payload["meta_ad_name"] == "SD_FounderTrap_V01"
        assert payload["created_by"] == "tagging_log_import"

    def test_blank_optional_fields_get_sane_defaults(self):
        payload = to_creative_row(good_row(format="", awareness=""))
        assert payload["format"] == "Static 4:5"
        assert payload["awareness_level"] == "Problem Aware"


@pytest.mark.skipif(not WORKBOOK.exists(), reason="workbook not present")
class TestRealWorkbook:
    def test_reads_the_shipped_workbook(self):
        rows = read_rows(WORKBOOK)
        assert rows, "expected at least the seeded example row"
        assert set(rows[0]) >= {"nama_ad", "konsep", "angle", "format", "awareness"}

    def test_the_seeded_example_row_is_recognisable(self):
        """The importer must skip Ibu's example row, not import it as real data."""
        rows = read_rows(WORKBOOK)
        assert any(EXAMPLE_MARKER in r.get("catatan", "").lower() for r in rows)

    def test_every_real_row_in_the_workbook_validates(self):
        """Guards against the spreadsheet drifting from config/brand.yaml."""
        rows = read_rows(WORKBOOK)
        real = [
            r for r in rows
            if any(r.values()) and EXAMPLE_MARKER not in r.get("catatan", "").lower()
        ]
        errors = [e for i, r in enumerate(real, start=2) if (e := validate(r, i))]
        assert not errors, "\n".join(errors)
