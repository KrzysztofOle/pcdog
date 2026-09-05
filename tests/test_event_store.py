"""Testy Event Store SQLite na izolowanych, tymczasowych bazach."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from pcdog_runtime import (
    DomainEvent,
    EventSource,
    EventStore,
    EventStoreError,
    EventType,
    HddActivity,
    PcDogState,
    PcState,
    PowerLedState,
    StateSnapshot,
    StateUpdate,
    UnsupportedSchemaVersionError,
)


BASE_TIME = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def snapshot(
    *,
    pc_state: PcState = PcState.OFF,
    power_led: PowerLedState = PowerLedState.OFF,
    hdd_activity: HddActivity = HddActivity.IDLE,
    timestamp: datetime = BASE_TIME,
) -> StateSnapshot:
    return StateSnapshot(
        pc_state=pc_state,
        power_led=power_led,
        power_led_reliable=True,
        hdd_activity=hdd_activity,
        hdd_activity_reliable=True,
        pcdog_state=PcDogState.HEALTHY,
        timestamp_utc=timestamp,
    )


def event(
    *,
    event_type: EventType = EventType.PC_STATE_CHANGED,
    old_value: PcState | PowerLedState | HddActivity = PcState.OFF,
    new_value: PcState | PowerLedState | HddActivity = PcState.ON,
    timestamp: datetime = BASE_TIME,
    details: dict[str, object] | None = None,
) -> DomainEvent:
    return DomainEvent(
        timestamp_utc=timestamp,
        event_type=event_type,
        source=EventSource.STATE_ENGINE,
        old_value=old_value,
        new_value=new_value,
        details=details,
    )


class FailingEventStore(EventStore):
    """Test double wymuszający wyjątek po dopisaniu eventów w transakcji."""

    def _write_current_state(
        self, state: StateSnapshot, source: EventSource
    ) -> None:
        raise RuntimeError("wymuszony błąd zapisu snapshotu")


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.database = Path(self._directory.name) / "pcdog.db"

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_creates_database_and_versioned_schema(self) -> None:
        with EventStore(self.database) as store:
            self.assertTrue(self.database.is_file())
            version = store._connection.execute(
                "SELECT version FROM schema_version"
            ).fetchone()["version"]
            self.assertEqual(version, 1)
            self.assertEqual(
                store._connection.execute("PRAGMA journal_mode").fetchone()[0], "wal"
            )
            tables = {
                row["name"]
                for row in store._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue({"events", "current_state"}.issubset(tables))

    def test_persists_single_event_and_snapshot_atomically(self) -> None:
        state = snapshot(pc_state=PcState.ON, power_led=PowerLedState.ON)
        with EventStore(self.database) as store:
            store.persist(events=[event()], snapshot=state)
            self.assertEqual(store.read_current_state(), state)
            stored = store.read_recent_events()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].event, event())

    def test_appends_events_in_id_order(self) -> None:
        first = event(timestamp=BASE_TIME)
        second = event(timestamp=BASE_TIME + timedelta(seconds=1))
        with EventStore(self.database) as store:
            store.persist(events=[first, second], snapshot=snapshot())
            stored = store.read_events()
        self.assertEqual([item.id for item in stored], [1, 2])
        self.assertEqual([item.event for item in stored], [first, second])

    def test_overwrites_current_state(self) -> None:
        first = snapshot()
        second = snapshot(
            pc_state=PcState.ON,
            power_led=PowerLedState.ON,
            timestamp=BASE_TIME + timedelta(seconds=1),
        )
        with EventStore(self.database) as store:
            store.persist(events=[], snapshot=first)
            store.persist(events=[], snapshot=second)
            self.assertEqual(store.read_current_state(), second)

    def test_current_state_recovers_after_reopen(self) -> None:
        state = snapshot(pc_state=PcState.ON, power_led=PowerLedState.ON)
        with EventStore(self.database) as store:
            store.persist(events=[event()], snapshot=state)
        with EventStore(self.database) as reopened:
            self.assertEqual(reopened.read_current_state(), state)
            self.assertEqual(len(reopened.read_events()), 1)

    def test_empty_database_has_no_current_state(self) -> None:
        with EventStore(self.database) as store:
            self.assertIsNone(store.read_current_state())
            self.assertEqual(store.read_events(), ())

    def test_rollback_leaves_no_partial_event_or_snapshot(self) -> None:
        with FailingEventStore(self.database) as store:
            with self.assertRaises(EventStoreError):
                store.persist(events=[event()], snapshot=snapshot())
            self.assertEqual(store.read_events(), ())
            self.assertIsNone(store.read_current_state())

    def test_timestamps_round_trip_as_utc(self) -> None:
        offset_timestamp = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
        with EventStore(self.database) as store:
            store.persist(
                events=[event(timestamp=offset_timestamp)],
                snapshot=snapshot(timestamp=offset_timestamp),
            )
            stored = store.read_recent_events()[0].event
            current = store.read_current_state()
        self.assertEqual(stored.timestamp_utc.tzinfo, UTC)
        self.assertEqual(stored.timestamp_utc, offset_timestamp)
        self.assertIsNotNone(current)
        self.assertEqual(current.timestamp_utc, offset_timestamp)

    def test_details_json_round_trips(self) -> None:
        details = {"reason": "debounce", "attempt": 2, "nested": {"ok": True}}
        with EventStore(self.database) as store:
            store.persist(events=[event(details=details)], snapshot=snapshot())
            stored = store.read_recent_events()[0].event
        self.assertEqual(stored.details, details)

    def test_recent_events_returns_latest_events_in_chronological_order(self) -> None:
        events = [
            event(timestamp=BASE_TIME + timedelta(seconds=index))
            for index in range(3)
        ]
        with EventStore(self.database) as store:
            store.persist(events=events, snapshot=snapshot())
            recent = store.read_recent_events(limit=2)
        self.assertEqual([item.id for item in recent], [2, 3])

    def test_events_can_be_filtered_by_id_and_timestamp(self) -> None:
        events = [
            event(timestamp=BASE_TIME + timedelta(seconds=index))
            for index in range(3)
        ]
        with EventStore(self.database) as store:
            store.persist(events=events, snapshot=snapshot())
            self.assertEqual(
                [item.id for item in store.read_events(after_id=1)], [2, 3]
            )
            self.assertEqual(
                [item.id for item in store.read_events(since_utc=events[1].timestamp_utc)],
                [2, 3],
            )

    def test_persist_update_integrates_state_engine_result(self) -> None:
        state = snapshot(pc_state=PcState.ON, power_led=PowerLedState.ON)
        update = StateUpdate(snapshot=state, events=(event(),))
        with EventStore(self.database) as store:
            store.persist_update(update)
            self.assertEqual(store.read_current_state(), state)
            self.assertEqual(len(store.read_events()), 1)

    def test_unknown_schema_version_is_rejected(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version (version) VALUES (999)")
        connection.commit()
        connection.close()
        with self.assertRaises(UnsupportedSchemaVersionError):
            EventStore(self.database)


if __name__ == "__main__":
    unittest.main()
