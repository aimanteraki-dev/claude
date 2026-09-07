"""Morning report formatting.

The report is the one artefact Ibu reads every day. A missing number must show
as a dash, never as RM0.00 — a false zero is worse than an honest gap.
"""

from __future__ import annotations

from annems.agents.analyst import DataPack
from annems.agents.reporter import build_daily_report, delta_arrow, num, pct, rm

from .conftest import TODAY


def pack(**overrides) -> DataPack:
    base = dict(
        tarikh=TODAY.isoformat(),
        semalam={
            "spend_rm": 320.50, "impressions": 41_200, "clicks": 610, "leads": 12,
            "cpl_rm": 26.71, "ctr_pct": 1.48, "cpm_rm": 7.78, "cpc_rm": 0.53,
            "cvr_pct": 1.97, "cpql_rm": None, "qualified_leads": 0, "hari": 1,
        },
        tiga_hari={}, empat_belas_hari={},
        tujuh_hari={
            "spend_rm": 2100.0, "impressions": 280_000, "clicks": 4100, "leads": 84,
            "cpl_rm": 25.0, "ctr_pct": 1.46, "cpm_rm": 7.5, "cpc_rm": 0.51,
            "cvr_pct": 2.05, "cpql_rm": 87.5, "qualified_leads": 24, "hari": 7,
        },
        cpql_7d=87.5,
        qualified_leads_7d=24,
        ads=[],
        ads_terbaik=[{"nama": "SD_FounderTrap_V01", "ref_id": "1", "spend_rm": 120.0,
                      "leads": 7, "cpl_rm": 17.14, "ctr_pct": 1.9}],
        ads_terlemah=[{"nama": "SD_CEOShift_V03", "ref_id": "2", "spend_rm": 140.0,
                       "leads": 1, "cpl_rm": 140.0, "ctr_pct": 0.7}],
        data_cukup=True,
        nota_kualiti_data=[],
    )
    base.update(overrides)
    return DataPack(**base)


class TestFormatters:
    def test_currency(self):
        assert rm(1234.5) == "RM1,234.50"

    def test_missing_currency_is_a_dash_not_zero(self):
        assert rm(None) == "—"

    def test_percent_and_counts(self):
        assert pct(1.48) == "1.48%"
        assert pct(None) == "—"
        assert num(41_200) == "41,200"
        assert num(None) == "—"

    def test_delta_arrows(self):
        assert "▲" in delta_arrow(12.0)
        assert "▼" in delta_arrow(-12.0)
        assert delta_arrow(None) == ""


class TestDailyReport:
    def test_contains_every_headline_number(self):
        out = build_daily_report(TODAY, "Diagnosis ringkas.", pack())

        assert "RM320.50" in out          # spend
        assert "RM26.71" in out           # CPL
        assert "RM87.50" in out           # CPQL — the metric that matters
        assert "1.48%" in out             # CTR
        assert "SD_FounderTrap_V01" in out
        assert "SD_CEOShift_V03" in out
        assert "Diagnosis ringkas." in out

    def test_missing_cpql_renders_as_a_dash(self):
        out = build_daily_report(TODAY, "…", pack(cpql_7d=None, qualified_leads_7d=0))
        assert "*CPQL: —*" in out
        assert "RM0.00" not in out.split("*Diagnosis*")[0]

    def test_data_quality_notes_are_surfaced(self):
        note = "Hanya 2 lead dalam 7 hari — CPL belum stabil."
        out = build_daily_report(TODAY, "…", pack(nota_kualiti_data=[note]))
        assert "Nota data" in out
        assert note in out

    def test_report_is_written_in_malay(self):
        out = build_daily_report(TODAY, "…", pack())
        for word in ("LAPORAN PAGI", "Semalam", "Lead", "Diagnosis"):
            assert word in out

    def test_survives_an_empty_day(self):
        empty = {k: (0 if isinstance(v, (int, float)) else None)
                 for k, v in pack().semalam.items()}
        empty.update({"cpl_rm": None, "ctr_pct": None})
        out = build_daily_report(TODAY, "Tiada data.", pack(semalam=empty, ads_terbaik=[],
                                                            ads_terlemah=[]))
        assert "LAPORAN PAGI" in out
        assert "Tiada data." in out
