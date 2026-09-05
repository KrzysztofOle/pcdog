"""Trwały, niezależny od infrastruktury Event Store SQLite."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import (
    DomainEvent,
    EventSource,
    EventType,
    HddActivity,
    PcDogState,
    PcState,
    PowerLedState,
    StateSnapshot,
)
from .state_engine import StateUpdate


SCHEMA_VERSION = 1


class EventStoreError(RuntimeError):
    """Jawny błąd persistence, możliwy do obsłużenia przez przyszły Health."""


class UnsupportedSchemaVersionError(EventStoreError):
    """Baza ma wersję, której ten runtime nie może bezpiecznie obsłużyć."""


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """Zdarzenie odczytane z trwałego store wraz z monotonicznym identyfikatorem."""

    id: int
    event: DomainEvent


class EventStore:
    """SQLite Event Store z atomowym zapisem historii i Current State.

    Ścieżkę bazy podaje wywołujący. Runtime produkcyjny będzie mógł wskazać
    ``/var/lib/pcdog``, natomiast ten moduł nie zakłada żadnej konkretnej
    lokalizacji ani nie wykonuje działań systemowych.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
        read_only: bool = False,
    ) -> None:
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must not be negative")
        self._read_only = read_only
        if read_only:
            database_uri = f"{Path(database).resolve().as_uri()}?mode=ro"
            self._connection = sqlite3.connect(
                database_uri, uri=True, isolation_level=None
            )
        else:
            self._connection = sqlite3.connect(str(database), isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
            if read_only:
                self._connection.execute("PRAGMA query_only = ON")
                self._verify_schema()
            else:
                self._connection.execute("PRAGMA journal_mode = WAL")
                self._initialize_schema()
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def persist_update(self, update: StateUpdate) -> None:
        """Trwale zapisuje bezpośredni wynik State Engine/Input Monitora."""

        self.persist(events=update.events, snapshot=update.snapshot)

    def persist(
        self,
        *,
        events: Iterable[DomainEvent],
        snapshot: StateSnapshot,
        source: EventSource = EventSource.STATE_ENGINE,
    ) -> None:
        """Atomowo dopisuje eventy i zastępuje Current State snapshotem."""

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            for event in events:
                self._append_event(event)
            self._write_current_state(snapshot, source)
            self._connection.execute("COMMIT")
        except Exception as error:
            self._rollback_if_needed()
            if isinstance(error, EventStoreError):
                raise
            raise EventStoreError("Nie udało się atomowo zapisać stanu PcDog") from error

    def read_current_state(self) -> StateSnapshot | None:
        """Zwraca ostatni spójny snapshot albo ``None`` dla pustej bazy."""

        try:
            rows = self._connection.execute(
                "SELECT key, value, updated_at_utc, source FROM current_state"
            ).fetchall()
        except sqlite3.Error as error:
            raise EventStoreError("Nie udało się odczytać Current State") from error

        if not rows:
            return None
        values = {row["key"]: row for row in rows}
        expected_keys = {
            "pc_state",
            "power_led",
            "power_led_reliable",
            "hdd_activity",
            "hdd_activity_reliable",
            "pcdog_state",
            "timestamp_utc",
        }
        if set(values) != expected_keys:
            raise EventStoreError("Current State ma niepełny lub nieznany zestaw pól")

        try:
            timestamp = self._parse_utc(values["timestamp_utc"]["value"])
            return StateSnapshot(
                pc_state=PcState(values["pc_state"]["value"]),
                power_led=PowerLedState(values["power_led"]["value"]),
                power_led_reliable=self._parse_bool(
                    values["power_led_reliable"]["value"]
                ),
                hdd_activity=HddActivity(values["hdd_activity"]["value"]),
                hdd_activity_reliable=self._parse_bool(
                    values["hdd_activity_reliable"]["value"]
                ),
                pcdog_state=PcDogState(values["pcdog_state"]["value"]),
                timestamp_utc=timestamp,
            )
        except (TypeError, ValueError) as error:
            raise EventStoreError("Current State zawiera nieprawidłowe dane") from error

    def read_recent_events(self, limit: int = 100) -> tuple[StoredEvent, ...]:
        """Zwraca do ``limit`` najnowszych eventów, zachowując ich kolejność."""

        if limit < 0:
            raise ValueError("limit must not be negative")
        rows = self._execute_event_query(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        )
        return tuple(self._stored_event_from_row(row) for row in reversed(rows))

    def read_events(
        self,
        *,
        after_id: int | None = None,
        since_utc: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[StoredEvent, ...]:
        """Zwraca eventy po wskazanym ID i/lub od wskazanego czasu UTC."""

        if after_id is not None and after_id < 0:
            raise ValueError("after_id must not be negative")
        if limit is not None and limit < 0:
            raise ValueError("limit must not be negative")

        conditions: list[str] = []
        parameters: list[Any] = []
        if after_id is not None:
            conditions.append("id > ?")
            parameters.append(after_id)
        if since_utc is not None:
            conditions.append("timestamp_utc >= ?")
            parameters.append(self._format_utc(since_utc))

        query = "SELECT * FROM events"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id ASC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        rows = self._execute_event_query(query, tuple(parameters))
        return tuple(self._stored_event_from_row(row) for row in rows)

    def _initialize_schema(self) -> None:
        try:
            existing_tables = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "schema_version" not in existing_tables and existing_tables:
                raise UnsupportedSchemaVersionError(
                    "Istniejąca baza PcDog nie zawiera informacji o wersji schematu"
                )

            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            version_row = self._connection.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            if version_row is None:
                self._connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
                )
            elif version_row["version"] != SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"Nieobsługiwana wersja schematu: {version_row['version']}"
                )

            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    old_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    details_json TEXT
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS current_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    source TEXT NOT NULL
                )
                """
            )
        except sqlite3.Error as error:
            raise EventStoreError("Nie udało się zainicjalizować schematu SQLite") from error

    def _verify_schema(self) -> None:
        """Weryfikuje istniejący schemat bez dokonywania jakiegokolwiek zapisu."""

        try:
            tables = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            required_tables = {"schema_version", "events", "current_state"}
            if not required_tables.issubset(tables):
                raise UnsupportedSchemaVersionError(
                    "Baza nie zawiera wspieranego schematu PcDog"
                )
            versions = self._connection.execute(
                "SELECT version FROM schema_version"
            ).fetchall()
            if len(versions) != 1 or versions[0]["version"] != SCHEMA_VERSION:
                version = None if not versions else versions[0]["version"]
                raise UnsupportedSchemaVersionError(
                    f"Nieobsługiwana wersja schematu: {version}"
                )
        except sqlite3.Error as error:
            raise EventStoreError("Nie udało się zweryfikować schematu SQLite") from error

    def _append_event(self, event: DomainEvent) -> None:
        details_json = (
            None if event.details is None else json.dumps(event.details, sort_keys=True)
        )
        self._connection.execute(
            """
            INSERT INTO events (
                timestamp_utc, event_type, source, old_value, new_value, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._format_utc(event.timestamp_utc),
                event.event_type.value,
                event.source.value,
                event.old_value.value,
                event.new_value.value,
                details_json,
            ),
        )

    def _write_current_state(
        self, snapshot: StateSnapshot, source: EventSource
    ) -> None:
        updated_at_utc = self._format_utc(snapshot.timestamp_utc)
        values = {
            "pc_state": snapshot.pc_state.value,
            "power_led": snapshot.power_led.value,
            "power_led_reliable": str(snapshot.power_led_reliable).lower(),
            "hdd_activity": snapshot.hdd_activity.value,
            "hdd_activity_reliable": str(snapshot.hdd_activity_reliable).lower(),
            "pcdog_state": snapshot.pcdog_state.value,
            "timestamp_utc": updated_at_utc,
        }
        self._connection.executemany(
            """
            INSERT INTO current_state (key, value, updated_at_utc, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at_utc = excluded.updated_at_utc,
                source = excluded.source
            """,
            (
                (key, value, updated_at_utc, source.value)
                for key, value in values.items()
            ),
        )

    def _execute_event_query(
        self, query: str, parameters: tuple[Any, ...]
    ) -> list[sqlite3.Row]:
        try:
            return self._connection.execute(query, parameters).fetchall()
        except sqlite3.Error as error:
            raise EventStoreError("Nie udało się odczytać eventów") from error

    def _stored_event_from_row(self, row: sqlite3.Row) -> StoredEvent:
        try:
            event_type = EventType(row["event_type"])
            return StoredEvent(
                id=row["id"],
                event=DomainEvent(
                    timestamp_utc=self._parse_utc(row["timestamp_utc"]),
                    event_type=event_type,
                    source=EventSource(row["source"]),
                    old_value=self._event_value(event_type, row["old_value"]),
                    new_value=self._event_value(event_type, row["new_value"]),
                    details=(
                        None
                        if row["details_json"] is None
                        else json.loads(row["details_json"])
                    ),
                ),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise EventStoreError("Event Store zawiera nieprawidłowe dane") from error

    @staticmethod
    def _event_value(event_type: EventType, value: str):
        if event_type is EventType.PC_STATE_CHANGED:
            return PcState(value)
        if event_type is EventType.POWER_LED_CHANGED:
            return PowerLedState(value)
        return HddActivity(value)

    @staticmethod
    def _format_utc(timestamp: datetime) -> str:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return timestamp.astimezone(UTC).isoformat()

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("stored timestamp is not timezone-aware")
        return timestamp.astimezone(UTC)

    @staticmethod
    def _parse_bool(value: str) -> bool:
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError("stored boolean is invalid")

    def _rollback_if_needed(self) -> None:
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK")
