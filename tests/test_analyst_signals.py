"""Agent 2's signal detection.

Milestone 3 Definition of Done: "daily diagnosis correctly distinguishes
creative fatigue vs landing page issues."

The distinction is made in code here, not left to the model's judgement — the
LLM receives the named pattern and only has to explain it in Bahasa Malaysia.
"""

from __future__ import annotations

from annems.agents.analyst import AdSnapshot, detect_signals


def snap(**kwargs) -> AdSnapshot:
    base = dict(
        ref_id="ad_1",
        name="SD_FounderTrap_V01",
        spend=100.0,
        impressions=10_000,
        clicks=200,
        leads=10,
        cpl=10.0,
        ctr=2.0,
        cpm=10.0,
        cvr=5.0,
        frequency=1.3,
        ctr_vs_7d_pct=0.0,
        cpl_vs_7d_pct=0.0,
        cpm_vs_7d_pct=0.0,
        days_of_data=7,
    )
    base.update(kwargs)
    return AdSnapshot(**base)


class TestHealthy:
    def test_steady_ad_produces_no_signals(self, cfg):
        assert detect_signals(snap(), cfg) == []


class TestCreativeFatigue:
    def test_ctr_collapse_with_high_frequency_and_flat_cpm(self, cfg):
        s = snap(ctr=1.0, ctr_vs_7d_pct=-50.0, frequency=3.2, cpm_vs_7d_pct=0.0)
        signals = detect_signals(s, cfg)

        assert "corak_creative_fatigue" in signals
        assert "corak_audience_saturation" not in signals


class TestAudienceSaturation:
    def test_high_frequency_with_rising_cpm(self, cfg):
        s = snap(frequency=3.5, cpm_vs_7d_pct=35.0)
        signals = detect_signals(s, cfg)

        assert "corak_audience_saturation" in signals
        # Rising CPM is the tell that separates this from plain fatigue.
        assert "cpm_naik" in signals


class TestLandingPageProblem:
    def test_healthy_ctr_but_clicks_do_not_convert(self, cfg):
        s = snap(ctr=2.0, ctr_vs_7d_pct=-2.0, cvr=0.4, clicks=250, leads=1, cpl=100.0)
        signals = detect_signals(s, cfg)

        assert "corak_masalah_landing_page" in signals
        assert "corak_creative_fatigue" not in signals

    def test_not_flagged_when_ctr_also_collapsed(self, cfg):
        """If the ad stopped earning clicks too, the page is not the story."""
        s = snap(ctr=0.5, ctr_vs_7d_pct=-75.0, cvr=0.4, clicks=250, leads=1)
        assert "corak_masalah_landing_page" not in detect_signals(s, cfg)


class TestTrackingBreakage:
    def test_many_clicks_zero_leads_suggests_tracking(self, cfg):
        s = snap(clicks=120, leads=0, cpl=None, cvr=0.0)
        signals = detect_signals(s, cfg)

        assert "klik_ada_lead_sifar" in signals
        assert "corak_kemungkinan_tracking_rosak" in signals

    def test_a_handful_of_clicks_is_not_enough_to_claim_breakage(self, cfg):
        s = snap(clicks=25, leads=0, cpl=None, cvr=0.0)
        signals = detect_signals(s, cfg)

        assert "klik_ada_lead_sifar" in signals
        assert "corak_kemungkinan_tracking_rosak" not in signals


class TestDataSufficiency:
    def test_low_impressions_short_circuits_every_other_signal(self, cfg):
        """Too little data to say anything — so say nothing else."""
        s = snap(impressions=100, clicks=1, ctr=1.0, ctr_vs_7d_pct=-80.0, frequency=5.0)
        signals = detect_signals(s, cfg)

        assert signals == ["impressions_terlalu_rendah_untuk_ctr"]
