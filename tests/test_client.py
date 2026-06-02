"""Offline tests for SkyPortalClient — a fake session captures requests and
returns canned SkyPortal envelopes, so no network is touched."""

from __future__ import annotations


import pytest

from skybot import SkyPortalClient, SkyPortalError


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if self._payload is _NO_JSON:
            raise ValueError("no json")
        return self._payload


_NO_JSON = object()


class FakeSession:
    """Records calls; returns queued responses (or a default success)."""

    def __init__(self):
        self.headers = {}
        self.calls = []
        self.queue = []

    def push(self, payload, status=200):
        self.queue.append(_Resp(payload, status))

    def request(self, method, url, params=None, json=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json}
        )
        if self.queue:
            return self.queue.pop(0)
        return _Resp({"status": "success", "data": {}})


def _client(session):
    return SkyPortalClient(
        "https://example.test", "tok", name="t", rate_delay_s=0.0, session=session
    )


def test_auth_header_and_base():
    s = FakeSession()
    c = _client(s)
    assert s.headers["Authorization"] == "token tok"
    assert c.api_base == "https://example.test/api"


def test_requires_base_and_token():
    with pytest.raises(ValueError):
        SkyPortalClient("", "tok")
    with pytest.raises(ValueError):
        SkyPortalClient("https://x", "")


def test_get_user_profile_unwraps_data():
    s = FakeSession()
    s.push({"status": "success", "data": {"username": "bot"}})
    assert _client(s).get_user_profile() == {"username": "bot"}


def test_error_status_raises():
    s = FakeSession()
    s.push({"status": "error", "message": "nope"}, status=400)
    with pytest.raises(SkyPortalError):
        _client(s).get_user_profile()


def test_non_json_raises():
    s = FakeSession()
    s.push(_NO_JSON, status=200)
    with pytest.raises(SkyPortalError):
        _client(s).get_user_profile()


def test_candidates_paginate():
    s = FakeSession()
    s.push(
        {
            "status": "success",
            "data": {"candidates": [{"id": "A"}, {"id": "B"}], "totalMatches": 3},
        }
    )
    s.push(
        {"status": "success", "data": {"candidates": [{"id": "C"}], "totalMatches": 3}}
    )
    out = _client(s).get_candidates(
        filter_ids=[1, 2], saved_status="notSavedToAnySelected"
    )
    assert [c["id"] for c in out] == ["A", "B", "C"]
    # filterIDs joined, savedStatus passed
    p0 = s.calls[0]["params"]
    assert p0["filterIDs"] == "1,2" and p0["savedStatus"] == "notSavedToAnySelected"


def test_submit_classification_body():
    s = FakeSession()
    s.push({"status": "success", "data": {"id": 9}})
    _client(s).submit_classification(
        obj_id="GCN-1",
        classification="Ic-BL",
        taxonomy_id=7,
        probability=0.9,
        origin="icarebot",
    )
    body = s.calls[0]["json"]
    assert body == {
        "obj_id": "GCN-1",
        "classification": "Ic-BL",
        "taxonomy_id": 7,
        "probability": 0.9,
        "origin": "icarebot",
    }
    assert s.calls[0]["url"].endswith("/api/classification")


def test_post_annotation_and_redshift():
    s = FakeSession()
    s.push({"status": "success", "data": {}})
    _client(s).post_annotation("GCN-1", {"gcn_z": 0.07}, origin="circex")
    assert s.calls[0]["json"] == {"origin": "circex", "data": {"gcn_z": 0.07}}
    assert s.calls[0]["url"].endswith("/api/sources/GCN-1/annotations")

    s.push({"status": "success", "data": {}})
    _client(s).set_redshift("GCN-1", 0.071, redshift_error=0.002)
    assert s.calls[1]["method"] == "PATCH"
    assert s.calls[1]["json"] == {"redshift": 0.071, "redshift_error": 0.002}


def test_source_exists():
    s = FakeSession()
    s.push({"status": "success", "data": {"id": "X"}})
    assert _client(s).source_exists("X") is True
    s.push({"status": "error"}, status=404)
    assert _client(s).source_exists("Y") is False


def test_post_photometry_per_row_and_overrides():
    s = FakeSession()
    s.push({"status": "success", "data": {"ids": [1]}})
    s.push({"status": "success", "data": {"ids": [2]}})
    rows = [
        {
            "mjd": 61058.0,
            "filter": "gaia::grp",
            "mag": 22.98,
            "magerr": 0.25,
            "limiting_mag": 23.0,
            "instrument_id": 114,
            "origin": "GCN",
            "altdata": {"note": "GCN43441"},
        },
        {
            "mjd": 61057.8,
            "filter": "sdssg",
            "limiting_mag": 19.7,
            "altdata": {"note": "GCN43440, upper limit"},
        },  # uses default instrument_id
    ]
    _client(s).post_photometry(
        "GCN-1", rows, instrument_id=91, origin="SVOM", group_ids=[3]
    )
    b0, b1 = s.calls[0]["json"], s.calls[1]["json"]
    assert s.calls[0]["url"].endswith("/api/photometry")
    assert b0["instrument_id"] == 114 and b0["origin"] == "GCN" and b0["magsys"] == "ab"
    assert b0["altdata"] == {"note": "GCN43441"} and b0["group_ids"] == [3]
    assert b1["instrument_id"] == 91 and b1["origin"] == "SVOM"  # fell back to defaults
    assert "mag" not in b1 and b1["limiting_mag"] == 19.7  # upper limit only


def test_post_photometry_requires_instrument():
    s = FakeSession()
    with pytest.raises(ValueError):
        _client(s).post_photometry(
            "GCN-1", [{"mjd": 1.0, "filter": "sdssg", "limiting_mag": 20.0}]
        )


def test_retry_on_503_then_success():
    s = FakeSession()
    s.push({"status": "error"}, status=503)
    s.push({"status": "success", "data": {"username": "bot"}})
    assert _client(s).get_user_profile() == {"username": "bot"}
    assert len(s.calls) == 2
