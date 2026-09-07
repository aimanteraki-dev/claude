"""GHL stage mapping — CPQL is only as honest as this mapping."""

from __future__ import annotations

from annems.collectors.ghl import CANONICAL_STAGES, extract_ad_id, normalise_stage, stage_lookup


class TestStageMapping:
    def test_every_configured_stage_maps_to_a_canonical_one(self):
        assert set(stage_lookup().values()) <= set(CANONICAL_STAGES)

    def test_maps_known_names_case_insensitively(self):
        assert normalise_stage("Qualified") == "qualified"
        assert normalise_stage("  APPOINTMENT  ") == "appointment"
        assert normalise_stage("Closed Won") == "closed_won"

    def test_maps_malay_stage_names(self):
        assert normalise_stage("Temujanji") == "appointment"
        assert normalise_stage("Layak") == "qualified"

    def test_unknown_stage_falls_back_to_new(self):
        """Unknown stages must not be counted as qualified — that inflates CPQL
        downwards and makes bad ads look good."""
        assert normalise_stage("Some New Stage Ibu Added") == "new"

    def test_missing_stage_is_new(self):
        assert normalise_stage(None) == "new"
        assert normalise_stage("") == "new"


class TestAttribution:
    def test_reads_ad_id_from_attribution_source(self):
        contact = {"attributionSource": {"adId": "120210000000012345"}}
        assert extract_ad_id(contact) == "120210000000012345"

    def test_reads_ad_id_from_the_opportunity_when_contact_lacks_it(self):
        opp = {"attributionSource": {"fbAdId": "999"}}
        assert extract_ad_id({}, opp) == "999"

    def test_falls_back_to_numeric_utm_content(self):
        contact = {"attributionSource": {"utmContent": "120210000000012345"}}
        assert extract_ad_id(contact) == "120210000000012345"

    def test_ignores_non_numeric_utm_content(self):
        contact = {"attributionSource": {"utmContent": "founder-trap-v1"}}
        assert extract_ad_id(contact) is None

    def test_returns_none_rather_than_guessing(self):
        assert extract_ad_id({}) is None
        assert extract_ad_id({"attributionSource": {}}) is None
