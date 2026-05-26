import pytest

from bilinc.cloud.entitlements import entitlements_for_plan


def test_cloud_free_entitlements_match_private_beta_contract():
    entitlements = entitlements_for_plan("cloud_free")

    assert entitlements.max_projects == 1
    assert entitlements.max_api_keys == 1
    assert entitlements.allowed_recall_profiles == ("fast", "balanced")


def test_unknown_plan_fails_closed():
    with pytest.raises(ValueError):
        entitlements_for_plan("unknown")
