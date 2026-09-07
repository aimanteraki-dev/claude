"""AGENT 3 alert rules, driven by simulated threshold breaches.

This is the Milestone 3 Definition of Done: "Alerts fire correctly on threshold
breaches (test with simulated data)."

`evaluate_rules` is pure, so every case below is a real end-to-end exercise of
the decision logic — no mocks, no network, no database.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from annems.agents.monitor import Alert, evaluate_rules, within_active_hours
from annems.config import MYT

from .conftest import TODAY, make_history, make_row


def rules_for(row, history=None, cfg=None, names=None):
    history = history if history is not None else make_history(7, TODAY)
    return evaluate_rules([row], history + [row], cfg, names or {}, TODAY)


def fired(alerts: list[Alert]) -> set[str]:
    return {a.rule for a in alerts}


class TestHealthyDay:
    def test_steady_performance_raises_nothing(self, cfg):
        """No false alarms on a normal day — a noisy bot gets muted and ignored."""
        today = make_row(TODAY)
        assert rules_for(today, cfg=cfg) == []


class TestSpendNoLeads:
    def test_fires_above_threshold_with_zero_leads(self, cfg):
        today = make_row(TODAY, spend=150.0, leads=0)
        assert "spend_no_leads" in fired(rules_for(today, cfg=cfg))

    def test_does_not_fire_below_threshold(self, cfg):
        today = make_row(TODAY, spend=80.0, leads=0)
        assert "spend_no_leads" not in fired(rules_for(today, cfg=cfg))

    def test_does_not_fire_when_leads_exist(self, cfg):
        today = make_row(TODAY, spend=500.0, leads=1)
        assert "spend_no_leads" not in fired(rules_for(today, cfg=cfg))

    def test_diagnosis_distinguishes_landing_page_from_creative(self, cfg):
        """Clicks but no leads points downstream; no clicks points at the ad."""
        many_clicks = make_row(TODAY, spend=150.0, clicks=200, leads=0)
        few_clicks = make_row(TODAY, spend=150.0, clicks=3, impressions=9_000, leads=0)

        a = next(x for x in rules_for(many_clicks, cfg=cfg) if x.rule == "spend_no_leads")
        b = next(x for x in rules_for(few_clicks, cfg=cfg) if x.rule == "spend_no_leads")

        assert "landing page" in a.diagnosis.lower()
        assert "creative" in b.diagnosis.lower()


class TestCPLSpike:
    def test_fires_above_multiple_of_baseline(self, cfg):
        # Baseline CPL is RM10; today is RM20, i.e. 2x > the 1.5x threshold.
        today = make_row(TODAY, spend=200.0, leads=10)
        assert "cpl_spike" in fired(rules_for(today, cfg=cfg))

    def test_does_not_fire_just_under_the_multiple(self, cfg):
        today = make_row(TODAY, spend=140.0, leads=10)  # CPL 14 < 15
        assert "cpl_spike" not in fired(rules_for(today, cfg=cfg))

    def test_suppressed_when_baseline_too_young(self, cfg):
        """Two days of history is not a baseline — refuse to judge."""
        short_history = make_history(2, TODAY)
        today = make_row(TODAY, spend=500.0, leads=10)  # CPL 50 vs 10
        assert "cpl_spike" not in fired(rules_for(today, short_history, cfg))

    def test_suppressed_below_min_spend(self, cfg):
        today = make_row(TODAY, spend=20.0, leads=1)  # CPL 20, but only RM20 spent
        assert "cpl_spike" not in fired(rules_for(today, cfg=cfg))


class TestCTRDrop:
    def test_fires_on_a_thirty_percent_collapse(self, cfg):
        # Baseline CTR 2.0%; today 1.0% = -50%.
        today = make_row(TODAY, clicks=100)
        assert "ctr_drop" in fired(rules_for(today, cfg=cfg))

    def test_does_not_fire_on_a_mild_dip(self, cfg):
        today = make_row(TODAY, clicks=180)  # 1.8% = -10%
        assert "ctr_drop" not in fired(rules_for(today, cfg=cfg))

    def test_suppressed_below_min_impressions(self, cfg):
        today = make_row(TODAY, impressions=500, clicks=2)
        assert "ctr_drop" not in fired(rules_for(today, cfg=cfg))

    def test_names_creative_fatigue(self, cfg):
        today = make_row(TODAY, clicks=100)
        alert = next(a for a in rules_for(today, cfg=cfg) if a.rule == "ctr_drop")
        assert "fatigue" in alert.diagnosis.lower()


class TestFrequency:
    def test_fires_on_saturation(self, cfg):
        today = make_row(TODAY, frequency=3.4)
        assert "frequency_high" in fired(rules_for(today, cfg=cfg))

    def test_quiet_at_healthy_frequency(self, cfg):
        today = make_row(TODAY, frequency=1.8)
        assert "frequency_high" not in fired(rules_for(today, cfg=cfg))

    def test_recommends_audience_change_not_creative(self, cfg):
        today = make_row(TODAY, frequency=4.0)
        alert = next(a for a in rules_for(today, cfg=cfg) if a.rule == "frequency_high")
        assert "audience" in alert.recommendation.lower()


class TestAlertFormat:
    """CLAUDE.md Agent 3: 'NEVER just performance declined.'"""

    @pytest.mark.parametrize(
        "row_kwargs",
        [
            {"spend": 150.0, "leads": 0},
            {"spend": 200.0, "leads": 10},
            {"clicks": 100},
            {"frequency": 4.0},
        ],
    )
    def test_every_alert_carries_numbers_diagnosis_and_recommendation(self, cfg, row_kwargs):
        alerts = rules_for(make_row(TODAY, **row_kwargs), cfg=cfg)
        assert alerts, "expected at least one alert for this breach"
        for a in alerts:
            assert a.facts, f"{a.rule} has no numbers"
            assert any(ch.isdigit() for ch in " ".join(map(str, a.facts.values())))
            assert len(a.diagnosis) > 20, f"{a.rule} diagnosis too thin"
            assert len(a.recommendation) > 20, f"{a.rule} has no real recommendation"

    def test_text_includes_the_ad_name_when_known(self, cfg):
        alerts = rules_for(
            make_row(TODAY, spend=150.0, leads=0),
            cfg=cfg,
            names={"ad_1": "SD_FounderTrap_V01"},
        )
        assert "SD_FounderTrap_V01" in alerts[0].to_text()


class TestMultipleAdsAndRefs:
    def test_only_the_breaching_ad_alerts(self, cfg):
        healthy = make_row(TODAY, ref_id="ad_ok")
        broken = make_row(TODAY, ref_id="ad_bad", spend=150.0, leads=0)
        history = make_history(7, TODAY, ref_id="ad_ok") + make_history(
            7, TODAY, ref_id="ad_bad"
        )

        alerts = evaluate_rules([healthy, broken], history, cfg, {}, TODAY)
        assert {a.ref_id for a in alerts} == {"ad_bad"}


class TestActiveHours:
    def test_inside_and_outside_serving_hours(self, cfg):
        from datetime import datetime

        assert within_active_hours(datetime(2026, 9, 7, 10, 0, tzinfo=MYT), cfg)
        assert not within_active_hours(datetime(2026, 9, 7, 3, 0, tzinfo=MYT), cfg)
