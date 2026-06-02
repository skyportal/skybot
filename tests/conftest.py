"""Shared fixtures. Integration tests are gated on env vars so the default
`pytest` run (offline unit tests) needs no SkyPortal.

Env for integration tests:
  SKYBOT_TEST_BASE   base URL of a SkyPortal (e.g. https://fritz.science or a
                     CI-spun http://localhost:5000)
  SKYBOT_TEST_TOKEN  an API token for that instance
  SKYBOT_TEST_OBJ    (optional) an existing obj_id to read in get_source tests
  SKYBOT_TEST_WRITE  (optional) "1" to enable the additive write round-trip
                     (post annotation/comment) — only set this against a
                     disposable/test instance, never production.
"""

from __future__ import annotations

import os

import pytest

from skybot import SkyPortalClient


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v else None


@pytest.fixture(scope="session")
def sp_client() -> SkyPortalClient:
    base = _env("SKYBOT_TEST_BASE")
    token = _env("SKYBOT_TEST_TOKEN")
    if not (base and token):
        pytest.skip("integration: set SKYBOT_TEST_BASE + SKYBOT_TEST_TOKEN")
    return SkyPortalClient(base, token, name="test")


@pytest.fixture(scope="session")
def test_obj() -> str:
    obj = _env("SKYBOT_TEST_OBJ")
    if not obj:
        pytest.skip("set SKYBOT_TEST_OBJ to a known source id for this test")
    return obj


@pytest.fixture(scope="session")
def writes_enabled() -> bool:
    if _env("SKYBOT_TEST_WRITE") != "1":
        pytest.skip(
            "write round-trip disabled (set SKYBOT_TEST_WRITE=1 on a "
            "disposable instance to enable)"
        )
    return True
