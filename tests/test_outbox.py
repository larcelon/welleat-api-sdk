"""Tests de l'outbox : politique, stockage au format camera-soft, rejeu et compteur du jour."""

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from welleat_api_sdk import ApiError, NetworkError, ResponseFormatError, ServerError
from welleat_api_sdk.models import Detection, FramePayload
from welleat_api_sdk.outbox import (
    DailyTrayCounter,
    FileOutboxStore,
    Outbox,
    OutboxEntry,
    OutboxPolicy,
    SyncDailyTrayCounter,
    SyncOutbox,
)
from welleat_api_sdk.outbox.store import as_json_value
from welleat_api_sdk.request import JsonValue

PARIS = timezone(timedelta(hours=2))
POLICY = OutboxPolicy()


class Clock:
    """Horloge réglable, en heure de Paris."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, delta: timedelta) -> None:
        self.moment += delta


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PARIS)


class Sender:
    """Envoi simulé : échoue tant que `failures` contient des erreurs."""

    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = failures or []
        self.sent: list[dict[str, JsonValue]] = []

    def __call__(self, payload: dict[str, JsonValue]) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(payload)

    async def send(self, payload: dict[str, JsonValue]) -> None:
        self(payload)


# --- Politique -------------------------------------------------------------------------


def test_reschedule_records_status_and_delay() -> None:
    entry = OutboxEntry("e", {"a": 1})
    first = POLICY.reschedule(entry, at(14, 9), ServerError(503, "busy"))
    assert first.retries == 1
    assert first.next_attempt_at == at(14, 9, 20)
    assert first.first_failed_at == at(14, 9)
    assert first.last_status == 503
    second = POLICY.reschedule(first, at(14, 10), NetworkError("timeout"))
    assert second.retries == 2
    assert second.first_failed_at == at(14, 9)
    assert second.last_status is None
    assert second.last_error == "timeout"


def test_due_expired_and_blackout() -> None:
    today = OutboxEntry("t", {}, next_attempt_at=at(14, 9), first_failed_at=at(14, 8))
    yesterday = OutboxEntry("y", {}, next_attempt_at=at(13, 9), first_failed_at=at(13, 8))
    fresh = OutboxEntry("f", {})
    assert not POLICY.is_due(today, at(14, 8, 59))
    assert POLICY.is_due(today, at(14, 9))
    assert POLICY.is_due(fresh, at(14, 12))
    assert POLICY.is_due(yesterday, at(14, 10, 29))
    assert not POLICY.is_due(yesterday, at(14, 10, 30))
    assert not POLICY.is_due(yesterday, at(14, 14, 59))
    assert POLICY.is_due(yesterday, at(14, 15))
    assert POLICY.is_due(today, at(14, 11))
    assert not POLICY.is_expired(yesterday, at(20, 8))
    assert POLICY.is_expired(yesterday, at(20, 8, 1))
    assert not POLICY.is_expired(fresh, at(30, 0))


def test_blackout_uses_the_local_day_of_the_clock() -> None:
    # 23:30 UTC le 13 = 01:30 à Paris le 14 : l'entrée est du jour, pas de la veille.
    entry = OutboxEntry("e", {}, first_failed_at=datetime(2026, 10, 13, 23, 30, tzinfo=UTC))
    assert not POLICY.in_blackout(entry, at(14, 11))


# --- Stockage --------------------------------------------------------------------------


def test_store_round_trip_writes_camera_soft_schema(tmp_path: Path) -> None:
    store = FileOutboxStore(tmp_path / "outbox")
    entry = OutboxEntry(
        "abc",
        {"image": "data:...", "detections": [{"bbox": [1, 2.5, 3, 4]}]},
        retries=2,
        next_attempt_at=at(14, 9),
        first_failed_at=at(14, 8),
        last_error="HTTP 500 : boom",
        last_status=500,
    )
    store.save(entry)
    raw = json.loads((tmp_path / "outbox" / "abc.json").read_text())
    assert raw == {
        "schema_version": 2,
        "payload": {"image": "data:...", "detections": [{"bbox": [1, 2.5, 3, 4]}]},
        "retries": 2,
        "next_attempt_at": at(14, 9).timestamp(),
        "first_failed_at": at(14, 8).timestamp(),
        "last_error": "HTTP 500 : boom",
        "last_status": 500,
        "privacy_verified": True,
    }
    assert store.load() == [entry]
    assert [p.name for p in (tmp_path / "outbox").iterdir()] == ["abc.json"]


def test_store_reads_hand_written_entries(tmp_path: Path) -> None:
    (tmp_path / "old.json").write_text(
        json.dumps({
            "schema_version": 2,
            "payload": {"cameraId": "c"},
            "retries": 1,
            "next_attempt_at": "2026-10-14T07:00:00",
            "first_failed_at": 1791900000,
            "last_error": None,
            "last_status": None,
            "privacy_verified": True,
        })
    )
    (tmp_path / "minimal.json").write_text(
        '{"schema_version": 2, "payload": {}, "privacy_verified": true}'
    )
    entries = FileOutboxStore(tmp_path).load()
    assert [e.entry_id for e in entries] == ["minimal", "old"]
    old = entries[1]
    assert old.next_attempt_at == datetime(2026, 10, 14, 7, tzinfo=UTC)
    assert old.first_failed_at == datetime.fromtimestamp(1791900000, UTC)
    assert entries[0] == OutboxEntry("minimal", {})


@pytest.mark.parametrize(
    "content",
    [
        "{pas du json",
        "[]",
        '{"schema_version": 1, "payload": {}, "privacy_verified": true}',
        '{"schema_version": 2, "payload": [], "privacy_verified": true}',
        '{"schema_version": 2, "payload": {}, "retries": true, "privacy_verified": true}',
        '{"schema_version": 2, "payload": {}, "next_attempt_at": "hier", "privacy_verified": true}',
        '{"schema_version": 2, "payload": {}, "first_failed_at": [], "privacy_verified": true}',
    ],
)
def test_invalid_files_are_quarantined(tmp_path: Path, content: str) -> None:
    (tmp_path / "bad.json").write_text(content)
    assert FileOutboxStore(tmp_path).load() == []
    assert [p.name for p in tmp_path.iterdir()] == ["bad.json.invalid"]


@pytest.mark.parametrize("flag", ["false", '"yes"', None])
def test_unverified_privacy_is_quarantined(tmp_path: Path, flag: str | None) -> None:
    field = "" if flag is None else f', "privacy_verified": {flag}'
    (tmp_path / "p.json").write_text(f'{{"schema_version": 2, "payload": {{}}{field}}}')
    assert FileOutboxStore(tmp_path).load() == []
    assert [p.name for p in tmp_path.iterdir()] == ["p.json.privacy_blocked"]


def test_non_json_payload_values_are_rejected() -> None:
    with pytest.raises(ResponseFormatError):
        as_json_value({"x": {1, 2}}, "payload")


# --- Rejeu -----------------------------------------------------------------------------


def test_sync_deliver_queues_failures_and_retries_them(tmp_path: Path) -> None:
    clock = Clock(at(14, 9))
    outbox = SyncOutbox(tmp_path, now=clock)
    sender = Sender([ApiError(400, '{"error": "bad"}'), ServerError(502, "gw")])

    assert not outbox.deliver({"n": 1}, sender)
    [entry] = outbox.pending()
    assert (entry.retries, entry.last_status, entry.payload) == (1, 400, {"n": 1})

    assert outbox.retry_due(sender) == 0
    clock.advance(timedelta(minutes=20))
    assert outbox.retry_due(sender) == 0
    [entry] = outbox.pending()
    assert (entry.retries, entry.last_status) == (2, 502)
    assert entry.next_attempt_at == at(14, 9, 40)

    clock.advance(timedelta(minutes=20))
    assert outbox.retry_due(sender) == 1
    assert outbox.pending() == []
    assert sender.sent == [{"n": 1}]


def test_one_retry_every_ten_fresh_deliveries(tmp_path: Path) -> None:
    clock = Clock(at(14, 9))
    outbox = SyncOutbox(tmp_path, now=clock)
    sender = Sender([NetworkError("down"), NetworkError("down")])
    outbox.deliver({"old": 1}, sender)
    clock.advance(timedelta(seconds=1))
    outbox.deliver({"old": 2}, sender)
    clock.advance(timedelta(hours=1))

    for n in range(9):
        assert outbox.deliver({"fresh": n}, sender)
    assert len(outbox.pending()) == 2
    outbox.deliver({"fresh": 9}, sender)
    assert len(outbox.pending()) == 1
    assert sender.sent[-1] == {"old": 1}


def test_expired_entries_are_purged_without_sending(tmp_path: Path) -> None:
    clock = Clock(at(1, 9))
    outbox = SyncOutbox(tmp_path, now=clock)
    sender = Sender([NetworkError("down")])
    outbox.deliver({"n": 1}, sender)
    clock.advance(timedelta(days=7, seconds=1))
    assert outbox.retry_due(sender) == 0
    assert sender.sent == []
    assert list(tmp_path.iterdir()) == []


def test_retry_order_limit_and_blackout(tmp_path: Path) -> None:
    clock = Clock(at(13, 9))
    outbox = SyncOutbox(tmp_path, now=clock)
    sender = Sender([NetworkError("x")] * 3)
    outbox.deliver({"day": 13}, sender)
    clock.moment = at(14, 9)
    outbox.deliver({"day": 14, "n": 1}, sender)
    clock.advance(timedelta(minutes=1))
    outbox.deliver({"day": 14, "n": 2}, sender)

    clock.moment = at(14, 11)
    assert outbox.retry_due(sender, limit=1) == 1
    assert outbox.retry_due(sender) == 1
    assert sender.sent == [{"day": 14, "n": 1}, {"day": 14, "n": 2}]
    clock.moment = at(14, 15)
    assert outbox.retry_due(sender) == 1
    assert sender.sent[-1] == {"day": 13}


def test_async_outbox_mirrors_sync_outbox(tmp_path: Path) -> None:
    clock = Clock(at(14, 9))
    outbox = Outbox(tmp_path, OutboxPolicy(fresh_before_retry=1), now=clock)
    sender = Sender([ServerError(500, "boom"), ServerError(500, "boom")])

    async def scenario() -> None:
        assert not await outbox.deliver({"n": 1}, sender.send)
        clock.advance(timedelta(minutes=20))
        assert await outbox.retry_due(sender.send) == 0
        clock.advance(timedelta(minutes=20))
        assert await outbox.deliver({"n": 2}, sender.send)

    asyncio.run(scenario())
    assert sender.sent == [{"n": 2}, {"n": 1}]
    assert outbox.pending() == []


def test_non_welleat_errors_propagate(tmp_path: Path) -> None:
    def broken(_payload: dict[str, JsonValue]) -> None:
        raise KeyError("bug")

    with pytest.raises(KeyError):
        SyncOutbox(tmp_path).deliver({"n": 1}, broken)
    assert list(tmp_path.iterdir()) == []


# --- Compteur du jour ------------------------------------------------------------------


def test_tray_counter_keeps_only_today(tmp_path: Path) -> None:
    clock = Clock(at(14, 9))
    counter = SyncDailyTrayCounter(tmp_path / "counts.json", now=clock)
    assert counter.pending() == 0
    counter.add()
    counter.add(2)
    assert json.loads((tmp_path / "counts.json").read_text()) == {"date": "2026-10-14", "count": 3}
    clock.moment = at(15, 0, 1)
    assert counter.pending() == 0
    assert not (tmp_path / "counts.json").exists()


def test_tray_counter_flush_stops_at_first_failure(tmp_path: Path) -> None:
    clock = Clock(at(14, 9))
    counter = SyncDailyTrayCounter(tmp_path / "counts.json", now=clock)
    counter.add(3)
    calls: list[int] = []

    def send() -> None:
        calls.append(1)
        if len(calls) == 2:
            raise ServerError(500, "boom")

    assert counter.flush(send) == 1
    assert counter.pending() == 2
    assert counter.flush(send) == 2
    assert counter.pending() == 0


def test_async_tray_counter(tmp_path: Path) -> None:
    counter = DailyTrayCounter(tmp_path / "c.json", now=Clock(at(14, 9)))
    counter.add(2)
    sent: list[int] = []

    async def send() -> None:
        sent.append(1)

    async def failing() -> None:
        raise NetworkError("down")

    assert asyncio.run(counter.flush(failing)) == 0
    assert asyncio.run(counter.flush(send)) == 2
    assert counter.pending() == 0


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        '{"date": "hier", "count": 1}',
        '{"count": 1}',
        '{"date": "2026-10-14", "count": -1}',
    ],
)
def test_tray_counter_quarantines_invalid_files(tmp_path: Path, content: str) -> None:
    (tmp_path / "c.json").write_text(content)
    counter = SyncDailyTrayCounter(tmp_path / "c.json", now=Clock(at(14, 9)))
    assert counter.pending() == 0
    assert [p.name for p in tmp_path.iterdir()] == ["c.json.invalid"]


# --- Rejeu de sendFrame ----------------------------------------------------------------


def test_frame_payload_round_trips_through_json() -> None:
    frame = FramePayload(
        "data:image/jpeg;base64,xx",
        "f.jpg",
        (Detection("tray", 0.9, (1, 2, 3, 4), 3), Detection("cup", 0.5, (0, 0, 1, 1))),
        tray_id="-1",
    )
    assert FramePayload.from_json(json.loads(json.dumps(frame.to_json()))) == frame
    assert FramePayload.from_json({"image": "i", "image_name": "n"}) == FramePayload("i", "n")


@pytest.mark.parametrize(
    "detection",
    [
        {"label": "tray", "confidence": 0.9, "bbox": [1, 2, 3]},
        {"label": "tray", "confidence": 0.9, "bbox": [1, 2, 3, 4], "track_id": True},
        {"label": "tray", "confidence": 0.9, "bbox": [1, 2, 3, 4], "track_id": 1.5},
        {"label": "", "confidence": 0.9, "bbox": [1, 2, 3, 4]},
    ],
)
def test_invalid_detections_are_rejected(detection: dict[str, object]) -> None:
    with pytest.raises(ResponseFormatError):
        FramePayload.from_json({"image": "i", "image_name": "n", "detections": [detection]})
