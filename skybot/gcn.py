"""GCN circular retrieval via GCN Kafka (https://gcn.nasa.gov).

Generic + reusable — not SkyPortal-specific, but it lives in `skybot` as shared
infrastructure so any bot can ingest GCN circulars without re-implementing the
Kafka plumbing. The consuming bot owns the credentials and what to DO with each
circular; this module only retrieves + parses.

`gcn-kafka` is an optional dependency, imported lazily:

    pip install "skybot[gcn]"

Usage:
    from skybot.gcn import make_consumer, stream_circulars
    consumer = make_consumer(client_id, client_secret)
    for circ in stream_circulars(consumer, limit=10):
        print(circ["circular_id"], circ["subject"])
"""

from __future__ import annotations

import json
from typing import Any, Iterator

DEFAULT_TOPIC = "gcn.circulars"


def make_consumer(
    client_id: str,
    client_secret: str,
    *,
    topics: tuple[str, ...] = (DEFAULT_TOPIC,),
    config: dict | None = None,
):
    """Build a gcn_kafka Consumer subscribed to `topics`. Credentials are passed
    in by the caller (skybot stays config-agnostic). Raises a clear error if
    gcn-kafka isn't installed or creds are missing."""
    if not (client_id and client_secret):
        raise ValueError("GCN Kafka client_id and client_secret are required")
    try:
        from gcn_kafka import Consumer
    except ImportError as e:
        raise RuntimeError(
            'gcn-kafka not installed — `pip install "skybot[gcn]"`'
        ) from e
    consumer = Consumer(
        client_id=client_id, client_secret=client_secret, **(config or {})
    )
    consumer.subscribe(list(topics))
    return consumer


def parse_circular(value: bytes | str) -> dict[str, Any]:
    """Parse a gcn.circulars Kafka message value into a flat dict. Falls back to
    raw body on non-JSON so nothing is lost."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    try:
        d = json.loads(value)
    except json.JSONDecodeError:
        return {
            "circular_id": None,
            "subject": None,
            "body": value,
            "event_id": None,
            "created_on": None,
        }
    return {
        "circular_id": d.get("circularId") or d.get("circular_id"),
        "subject": d.get("subject"),
        "body": d.get("body") or "",
        "event_id": d.get("eventId") or d.get("event_id"),
        "created_on": d.get("createdOn") or d.get("created_on"),
    }


def stream_circulars(
    consumer, *, timeout: float = 1.0, limit: int | None = None
) -> Iterator[dict[str, Any]]:
    """Yield parsed circulars from a subscribed consumer. Skips Kafka-level
    errored messages. `limit` stops after N circulars (None = run forever)."""
    n = 0
    while limit is None or n < limit:
        for message in consumer.consume(timeout=timeout):
            if message.error():
                continue
            yield parse_circular(message.value())
            n += 1
            if limit is not None and n >= limit:
                return
