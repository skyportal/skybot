"""Offline tests for skybot.gcn (no Kafka, no network)."""

from __future__ import annotations

import importlib.util

import pytest

from skybot import gcn


def test_parse_circular_json():
    msg = (
        '{"circularId": 43441, "subject": "GRB 260117A: SVOM/VT", '
        '"body": "We observed...", "eventId": "GRB 260117A", "createdOn": 123}'
    )
    c = gcn.parse_circular(msg.encode())
    assert c["circular_id"] == 43441
    assert c["subject"].startswith("GRB 260117A")
    assert c["body"] == "We observed..."
    assert c["event_id"] == "GRB 260117A"
    assert c["created_on"] == 123


def test_parse_circular_nonjson_falls_back_to_body():
    c = gcn.parse_circular(b"plain text circular")
    assert c["circular_id"] is None and c["body"] == "plain text circular"


def test_make_consumer_requires_creds():
    with pytest.raises(ValueError):
        gcn.make_consumer("", "")


@pytest.mark.skipif(
    importlib.util.find_spec("gcn_kafka") is not None,
    reason="gcn-kafka installed — the missing-dependency path can't be exercised",
)
def test_make_consumer_without_gcn_kafka_raises_helpful_error():
    with pytest.raises(RuntimeError, match="gcn-kafka not installed"):
        gcn.make_consumer("id", "secret")


class _FakeMsg:
    def __init__(self, value, err=None):
        self._value = value
        self._err = err

    def error(self):
        return self._err

    def value(self):
        return self._value


class _FakeConsumer:
    """Yields one batch then empties — enough to exercise stream_circulars."""

    def __init__(self, batches):
        self._batches = list(batches)

    def consume(self, timeout=1.0):
        return self._batches.pop(0) if self._batches else []


def test_stream_circulars_skips_errors_and_respects_limit():
    batches = [
        [
            _FakeMsg(b'{"circularId": 1, "subject": "a"}'),
            _FakeMsg(None, err="boom"),  # errored -> skipped
            _FakeMsg(b'{"circularId": 2, "subject": "b"}'),
        ],
        [_FakeMsg(b'{"circularId": 3, "subject": "c"}')],
    ]
    got = list(gcn.stream_circulars(_FakeConsumer(batches), limit=2))
    assert [c["circular_id"] for c in got] == [1, 2]
