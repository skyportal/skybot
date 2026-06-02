"""Integration tests against a real SkyPortal — opt-in via env (see conftest).

Run:
    SKYBOT_TEST_BASE=https://fritz.science SKYBOT_TEST_TOKEN=... \
        pytest -m integration -q

Read-only by default; the write round-trip additionally needs
SKYBOT_TEST_WRITE=1 + SKYBOT_TEST_OBJ and should target a disposable instance.
"""

from __future__ import annotations

import uuid

import pytest

from skybot import SkyPortalError

pytestmark = pytest.mark.integration


# ── read-only: prove auth + envelope handling against a live instance ─────────
def test_authenticated(sp_client):
    # get_user_profile returns success (raises SkyPortalError otherwise). Some
    # scoped/bot tokens return an empty profile, so assert the call succeeds and
    # yields a dict rather than asserting a username.
    prof = sp_client.get_user_profile()
    assert isinstance(prof, dict)


def test_list_groups(sp_client):
    groups = sp_client.list_groups()
    assert isinstance(groups, list)


def test_list_taxonomies(sp_client):
    tax = sp_client.list_taxonomies()
    assert isinstance(tax, list)
    for t in tax:
        assert "id" in t


def test_list_instruments(sp_client):
    insts = sp_client.list_instruments()
    assert isinstance(insts, list)


def test_get_source(sp_client, test_obj):
    src = sp_client.get_source(test_obj, include_classifications=True)
    assert src.get("id") == test_obj
    assert sp_client.source_exists(test_obj) is True


def test_source_missing_is_false(sp_client):
    assert sp_client.source_exists(f"nope-{uuid.uuid4().hex[:8]}") is False


def test_bad_path_raises(sp_client):
    with pytest.raises(SkyPortalError):
        sp_client._call("GET", "this/endpoint/does/not/exist")


# ── additive write round-trip (opt-in; disposable instance only) ──────────────
def test_annotation_round_trip(sp_client, test_obj, writes_enabled):
    origin = f"skybot-itest-{uuid.uuid4().hex[:8]}"
    marker = uuid.uuid4().hex
    sp_client.post_annotation(test_obj, {"skybot_test": marker}, origin=origin)
    anns = sp_client.get_annotations(test_obj)
    mine = [a for a in anns if a.get("origin") == origin]
    assert mine, f"posted annotation origin={origin} not found on readback"
    assert mine[0].get("data", {}).get("skybot_test") == marker


def test_comment_round_trip(sp_client, test_obj, writes_enabled):
    marker = uuid.uuid4().hex
    sp_client.post_comment(test_obj, f"skybot integration test {marker}")
    texts = [c.get("text", "") for c in sp_client.get_comments(test_obj)]
    assert any(marker in t for t in texts), "posted comment not found on readback"
