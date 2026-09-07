"""Metric Engine tests. If these pass, no agent can quote a wrong number."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from annems.metrics import (
    MetricRow,
    aggregate,
    compute_baseline,
    compute_cpql,
    compute_derived,
    count_qualified,
    moving_average,
    pct_change,
    rank_ads,
    safe_div,
)

from .conftest import TODAY, make_history, make_row


class TestSafeDivision:
    def test_normal_division(self):
        assert safe_div(10, 4) == 2.5

    def test_zero_denominator_is_none_not_zero(self):
        # The whole point: a missing metric must never masquerade as 0.
        assert safe_div(10, 0) is None

    def test_none_operands(self):
        assert safe_div(None, 5) is None
        assert safe_div(5, None) is None


class TestDerivedMetrics:
    def test_all_five_metrics(self):
        row = compute_derived(
            MetricRow(date=TODAY, level="ad", ref_id="a", spend=200.0,
                      impressions=10_000, clicks=250, leads=10)
        )
        assert row.ctr == 2.5              # 250/10000*100
        assert row.cpm == 20.0             # 200/10000*1000
        assert row.cpc == 0.8              # 200/250
        assert row.cpl == 20.0             # 200/10
        assert row.cvr == 4.0              # 10/250*100

    def test_zero_leads_gives_none_cpl(self):
        row = compute_derived(
            MetricRow(date=TODAY, level="ad", ref_id="a", spend=150.0,
                      impressions=5_000, clicks=100, leads=0)
        )
        assert row.cpl is None
        assert row.cvr == 0.0  # 0 leads / 100 clicks is a real zero, not missing

    def test_zero_impressions_gives_none_ctr_and_cpm(self):
        row = compute_derived(
            MetricRow(date=TODAY, level="ad", ref_id="a", spend=0.0,
                      impressions=0, clicks=0, leads=0)
        )
        assert row.ctr is None
        assert row.cpm is None
        assert row.cpc is None

    def test_idempotent(self):
        row = make_row(TODAY)
        first = (row.ctr, row.cpl, row.cpm)
        compute_derived(row)
        assert (row.ctr, row.cpl, row.cpm) == first


class TestCPQL:
    def test_cpql(self):
        assert compute_cpql(1000.0, 8) == 125.0

    def test_no_qualified_leads_is_none(self):
        assert compute_cpql(1000.0, 0) is None

    def test_count_qualified_includes_later_stages(self):
        stages = ["new", "qualified", "appointment", "closed_won", "closed_lost", "new"]
        assert count_qualified(stages) == 3

    def test_count_qualified_is_case_insensitive(self):
        assert count_qualified(["Qualified", " APPOINTMENT "]) == 2


class TestMovingAverage:
    def test_mean_of_present_values(self):
        assert moving_average([2, 4, 6]) == 4

    def test_missing_days_are_skipped_not_zeroed(self):
        # An ad that ran 2 of 5 days averages those 2 days.
        assert moving_average([10, None, None, 20, None]) == 15

    def test_all_missing_is_none(self):
        assert moving_average([None, None]) is None
        assert moving_average([]) is None


class TestPctChange:
    def test_increase(self):
        assert pct_change(150, 100) == 50.0

    def test_decrease(self):
        assert pct_change(70, 100) == -30.0

    def test_zero_baseline_is_none(self):
        assert pct_change(50, 0) is None


class TestBaselines:
    def test_baseline_excludes_the_day_being_measured(self):
        """Today's spike must not dilute the baseline it is compared against."""
        history = make_history(days=7, end=TODAY)
        today = make_row(TODAY, clicks=20)  # CTR collapses today
        b = compute_baseline(history + [today], "ctr", TODAY, "ad", "ad_1")

        assert b.avg_7d == pytest.approx(2.0)   # the steady historical CTR
        assert b.value == pytest.approx(0.2)
        assert b.delta_pct == pytest.approx(-90.0)

    def test_days_of_data_counts_only_prior_days(self):
        history = make_history(days=3, end=TODAY)
        b = compute_baseline(history, "ctr", TODAY, "ad", "ad_1")
        assert b.days_of_data == 3

    def test_no_history_yields_none_baseline(self):
        b = compute_baseline([make_row(TODAY)], "cpl", TODAY, "ad", "ad_1")
        assert b.avg_7d is None
        assert b.delta_pct is None
        assert b.days_of_data == 0

    def test_other_refs_do_not_leak_into_a_baseline(self):
        mine = make_history(7, TODAY, ref_id="ad_1")
        theirs = make_history(7, TODAY, ref_id="ad_2", clicks=1000)
        b = compute_baseline(mine + theirs, "ctr", TODAY, "ad", "ad_1")
        assert b.avg_7d == pytest.approx(2.0)

    def test_unknown_metric_rejected(self):
        with pytest.raises(ValueError):
            compute_baseline([], "roas", TODAY, "ad", "ad_1")


class TestAggregate:
    def test_derived_metrics_come_from_summed_raw_numbers(self):
        """A RM500 ad must outweigh a RM5 ad — never average the averages."""
        big = make_row(TODAY, ref_id="big", spend=500.0, impressions=50_000,
                       clicks=1000, leads=50)
        tiny = make_row(TODAY, ref_id="tiny", spend=5.0, impressions=100,
                        clicks=50, leads=1)

        t = aggregate([big, tiny])

        assert t.spend == 505.0
        assert t.leads == 51
        assert t.cpl == pytest.approx(505 / 51, abs=0.01)
        # Naive averaging of the two CTRs would give 26%; the honest figure is ~2.1%.
        assert t.ctr == pytest.approx(1050 / 50_100 * 100, abs=0.01)

    def test_cpql_included_when_qualified_supplied(self):
        t = aggregate([make_row(TODAY, spend=400.0)], qualified_leads=4)
        assert t.cpql == 100.0

    def test_empty_input(self):
        t = aggregate([])
        assert t.spend == 0
        assert t.cpl is None


class TestRankAds:
    def test_lowest_cpl_first(self):
        good = make_row(TODAY, ref_id="good", spend=100.0, leads=10)   # CPL 10
        bad = make_row(TODAY, ref_id="bad", spend=100.0, leads=2)      # CPL 50
        assert [r.ref_id for r in rank_ads([bad, good], "cpl")] == ["good", "bad"]

    def test_rows_without_the_metric_are_dropped(self):
        no_leads = make_row(TODAY, ref_id="none", leads=0)
        ok = make_row(TODAY, ref_id="ok", leads=5)
        assert [r.ref_id for r in rank_ads([no_leads, ok], "cpl")] == ["ok"]

    def test_min_spend_filters_out_noise(self):
        """One lucky lead on RM8 of spend is not a winner."""
        lucky = make_row(TODAY, ref_id="lucky", spend=8.0, leads=1)     # CPL 8
        real = make_row(TODAY, ref_id="real", spend=300.0, leads=20)    # CPL 15
        ranked = rank_ads([lucky, real], "cpl", min_spend=50.0)
        assert [r.ref_id for r in ranked] == ["real"]
