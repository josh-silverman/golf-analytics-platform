"""Tests for the training data builder + label derivation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Page, Player, Tournament, TournamentEntry
from app.features.feature_sets import v1_baseline
from app.ml.training import (
    LABEL_KEYS,
    TrainingData,
    TrainingDataBuilder,
    TrainingExample,
    labels_from_entry,
)

_FS_HASH = v1_baseline().hash


# ---------------------------------------------------------------------------
# labels_from_entry
# ---------------------------------------------------------------------------


def _entry(
    *,
    eid: int = 1,
    tid: int = 1,
    pid: int = 1,
    status: EntryStatus = EntryStatus.MADE_CUT,
    final_position: int | None = None,
) -> TournamentEntry:
    return TournamentEntry(
        id=eid,
        tournament_id=tid,
        player_id=pid,
        status=status,
        final_position=final_position,
        final_score_to_par=None,
        official_money_cents=None,
    )


def test_labels_for_winner() -> None:
    labels = labels_from_entry(_entry(status=EntryStatus.MADE_CUT, final_position=1))
    assert labels == {"win": 1, "top_5": 1, "top_10": 1, "top_20": 1, "made_cut": 1}


def test_labels_for_top_5_finisher() -> None:
    labels = labels_from_entry(_entry(status=EntryStatus.MADE_CUT, final_position=5))
    assert labels["win"] == 0
    assert labels["top_5"] == 1
    assert labels["top_10"] == 1
    assert labels["top_20"] == 1


def test_labels_for_mid_pack_finisher() -> None:
    labels = labels_from_entry(_entry(status=EntryStatus.MADE_CUT, final_position=42))
    assert labels == {"win": 0, "top_5": 0, "top_10": 0, "top_20": 0, "made_cut": 1}


def test_labels_for_missed_cut() -> None:
    labels = labels_from_entry(_entry(status=EntryStatus.MISSED_CUT, final_position=None))
    assert labels == {"win": 0, "top_5": 0, "top_10": 0, "top_20": 0, "made_cut": 0}


def test_labels_for_withdrew() -> None:
    labels = labels_from_entry(_entry(status=EntryStatus.WITHDREW, final_position=None))
    # Withdrew counts as "did not make cut" for the made_cut label.
    assert labels["made_cut"] == 0
    assert labels["win"] == 0


def test_label_keys_constant_matches_returned_keys() -> None:
    labels = labels_from_entry(_entry(status=EntryStatus.MADE_CUT, final_position=10))
    assert set(labels.keys()) == set(LABEL_KEYS)


# ---------------------------------------------------------------------------
# TrainingDataBuilder
# ---------------------------------------------------------------------------


def _tournament(
    tid: int, start: date, end: date, status: TournamentStatus = TournamentStatus.COMPLETED
) -> Tournament:
    return Tournament(
        id=tid,
        course_id=1,
        name=f"Tournament {tid}",
        season=2026,
        start_date=start,
        end_date=end,
        purse=10_000_000,
        field_strength=None,
        status=status,
    )


def _player(pid: int) -> Player:
    return Player(
        id=pid, dg_id=None, full_name=f"Player {pid}",
        country="USA", dob=None, turned_pro=2020,
    )


@dataclass
class _ExtractionStub:
    values: dict[str, float]


class _StubCatalog:
    """Returns the given tournaments and fields; no pagination beyond one page."""

    def __init__(
        self,
        *,
        tournaments: list[Tournament],
        fields: dict[int, list[TournamentEntry]],
    ) -> None:
        self._tournaments = tournaments
        self._fields = fields

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 200,
    ) -> Page[Tournament]:
        items = [
            t for t in self._tournaments
            if status is None or t.status == status
        ]
        return Page(items=items, next_cursor=None, total=len(items))

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        return list(self._fields.get(tournament_id, []))


class _StubExtractor:
    """Returns the same feature values for every call so we can verify shape."""

    def __init__(self) -> None:
        self.feature_set = v1_baseline()
        self.calls: list[tuple[int, date]] = []

    async def extract(self, player_id: int, as_of: date) -> _ExtractionStub:
        self.calls.append((player_id, as_of))
        return _ExtractionStub(values={"sg_total_rating": 1.0})

    async def extract_field(
        self, player_ids: list[int], as_of: date, *, event: object | None = None
    ) -> dict[int, _ExtractionStub]:
        return {pid: await self.extract(pid, as_of) for pid in dict.fromkeys(player_ids)}


def _make_builder(
    *,
    tournaments: list[Tournament],
    fields: dict[int, list[TournamentEntry]],
) -> tuple[TrainingDataBuilder, _StubExtractor]:
    catalog = _StubCatalog(tournaments=tournaments, fields=fields)
    extractor = _StubExtractor()
    builder = TrainingDataBuilder(
        catalog=catalog,  # type: ignore[arg-type]
        extractor=extractor,  # type: ignore[arg-type]
    )
    return builder, extractor


async def test_build_returns_one_example_per_eligible_entry() -> None:
    t1 = _tournament(1, date(2026, 1, 10), date(2026, 1, 13))
    t2 = _tournament(2, date(2026, 2, 14), date(2026, 2, 17))
    fields = {
        1: [
            _entry(eid=1, tid=1, pid=10, status=EntryStatus.MADE_CUT, final_position=1),
            _entry(eid=2, tid=1, pid=11, status=EntryStatus.MISSED_CUT),
        ],
        2: [
            _entry(eid=3, tid=2, pid=10, status=EntryStatus.MADE_CUT, final_position=15),
        ],
    }
    builder, _ = _make_builder(tournaments=[t1, t2], fields=fields)

    data = await builder.build(through=date(2026, 3, 1))
    assert isinstance(data, TrainingData)
    assert len(data) == 3
    assert data.feature_set_hash == _FS_HASH
    assert data.through_date == date(2026, 3, 1)


async def test_build_uses_day_before_tournament_as_of() -> None:
    """No leakage: features must be computed strictly before the tournament."""
    t = _tournament(1, date(2026, 6, 10), date(2026, 6, 13))
    fields = {
        1: [_entry(eid=1, tid=1, pid=10, status=EntryStatus.MADE_CUT, final_position=5)],
    }
    builder, extractor = _make_builder(tournaments=[t], fields=fields)

    await builder.build(through=date(2026, 7, 1))
    assert extractor.calls == [(10, date(2026, 6, 10) - timedelta(days=1))]


async def test_build_skips_tournaments_ending_after_through() -> None:
    """A tournament ending after the cutoff must not produce examples."""
    early = _tournament(1, date(2026, 1, 10), date(2026, 1, 13))
    late = _tournament(2, date(2026, 8, 1), date(2026, 8, 4))
    fields = {
        1: [_entry(eid=1, tid=1, pid=10, status=EntryStatus.MADE_CUT, final_position=1)],
        2: [_entry(eid=2, tid=2, pid=11, status=EntryStatus.MADE_CUT, final_position=1)],
    }
    builder, _ = _make_builder(tournaments=[early, late], fields=fields)
    data = await builder.build(through=date(2026, 6, 1))
    assert len(data) == 1
    assert data.examples[0].tournament_id == 1


async def test_build_skips_active_entries() -> None:
    """ACTIVE = tournament still in progress — no final position yet."""
    t = _tournament(1, date(2026, 6, 10), date(2026, 6, 13))
    fields = {
        1: [
            _entry(eid=1, tid=1, pid=10, status=EntryStatus.ACTIVE),
            _entry(eid=2, tid=1, pid=11, status=EntryStatus.MADE_CUT, final_position=10),
        ],
    }
    builder, _ = _make_builder(tournaments=[t], fields=fields)
    data = await builder.build(through=date(2026, 7, 1))
    assert len(data) == 1
    assert data.examples[0].player_id == 11


async def test_build_skips_made_cut_entries_without_final_position() -> None:
    """Inconsistent entry: status says made cut but no position — fail loud,
    skip the example rather than fabricate a label."""
    t = _tournament(1, date(2026, 6, 10), date(2026, 6, 13))
    fields = {
        1: [
            _entry(eid=1, tid=1, pid=10, status=EntryStatus.MADE_CUT, final_position=None),
            _entry(eid=2, tid=1, pid=11, status=EntryStatus.MADE_CUT, final_position=12),
        ],
    }
    builder, _ = _make_builder(tournaments=[t], fields=fields)
    data = await builder.build(through=date(2026, 7, 1))
    assert len(data) == 1
    assert data.examples[0].player_id == 11


async def test_build_returns_empty_when_no_completed_tournaments() -> None:
    upcoming = _tournament(
        1, date(2026, 6, 10), date(2026, 6, 13),
        status=TournamentStatus.UPCOMING,
    )
    builder, _ = _make_builder(tournaments=[upcoming], fields={})
    data = await builder.build(through=date(2026, 7, 1))
    assert len(data) == 0
    # Feature-set hash is still recorded so the (empty) dataset has provenance.
    assert data.feature_set_hash == _FS_HASH


async def test_examples_carry_full_features_and_labels() -> None:
    t = _tournament(1, date(2026, 1, 10), date(2026, 1, 13))
    fields = {
        1: [_entry(eid=1, tid=1, pid=10, status=EntryStatus.MADE_CUT, final_position=1)],
    }
    builder, _ = _make_builder(tournaments=[t], fields=fields)
    data = await builder.build(through=date(2026, 6, 1))
    example = data.examples[0]
    assert isinstance(example, TrainingExample)
    assert example.features == {"sg_total_rating": 1.0}
    assert example.labels["win"] == 1
    assert example.labels["top_5"] == 1
    assert example.labels["made_cut"] == 1
    assert example.player_id == 10
    assert example.tournament_id == 1


@pytest.mark.parametrize("through_date", [date(2025, 1, 1), date(2026, 6, 4)])
async def test_through_date_recorded_in_output(through_date: date) -> None:
    builder, _ = _make_builder(tournaments=[], fields={})
    data = await builder.build(through=through_date)
    assert data.through_date == through_date
