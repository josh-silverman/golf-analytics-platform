"""Tests for the forward out-of-sample prediction-board archive + grader."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Tournament, TournamentEntry
from app.services.board_archive import (
    BoardSnapshot,
    BoardSnapshotOutcome,
    FileBoardArchive,
    RedisBoardArchive,
    _from_dict,
    _to_json,
)
from app.services.forward_track_record import compute_forward_track_record


class FakeRedis:
    """In-memory stand-in for the async Redis client the archive uses.

    Implements only the handful of ops ``RedisBoardArchive`` touches, with SET NX
    semantics (returns ``True`` on a fresh key, ``None`` when it already exists —
    matching redis-py) so the immutability guarantee is exercised for real.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False) -> bool | None:
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def scan_iter(self, match: str = "*"):  # noqa: ANN201 — async generator
        prefix = match.rstrip("*")
        for key in list(self._store):
            if key.startswith(prefix):
                yield key

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._store.get(k) for k in keys]


def _snapshot(
    *,
    tournament_id: int = 1,
    version: str = "path_a@v2",
    trained_through: str | None = "2026-05-01",
    start_date: str = "2026-06-01",
    outcomes: tuple[BoardSnapshotOutcome, ...] = (),
    source: str = "captured",
    dg_direct_count: int | None = None,
) -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=tournament_id,
        tournament_name="The Demo",
        tournament_start_date=start_date,
        model_name="golf_v1",
        model_version_id=version,
        feature_set_hash="deadbeef",
        model_trained_through=trained_through,
        as_of="2026-05-31",
        captured_at="2026-05-31T12:00:00+00:00",
        outcomes=outcomes,
        source=source,
        dg_direct_count=dg_direct_count,
    )


async def test_persist_is_immutable_first_capture(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    assert await archive.persist(_snapshot()) is True
    assert await archive.has(1, "path_a@v2")
    # A second capture for the same (tournament, version) must NOT overwrite.
    second = _snapshot(start_date="2099-01-01")
    assert await archive.persist(second) is False
    loaded = await archive.list_all()
    assert len(loaded) == 1
    assert loaded[0].tournament_start_date == "2026-06-01"  # the first capture


async def test_roundtrip_preserves_outcomes(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    snap = _snapshot(
        outcomes=(
            BoardSnapshotOutcome(10, 0.1, 0.2, 0.3, 0.4, 0.9),
            BoardSnapshotOutcome(11, 0.02, 0.1, 0.2, 0.3, 0.7),
        )
    )
    await archive.persist(snap)
    (loaded,) = await archive.list_all()
    assert len(loaded.outcomes) == 2
    assert loaded.outcomes[0].player_id == 10
    assert loaded.outcomes[0].make_cut_prob == pytest.approx(0.9)
    assert loaded.source == "captured"  # default provenance round-trips


async def test_redis_backend_is_immutable_and_roundtrips() -> None:
    archive = RedisBoardArchive(FakeRedis())  # type: ignore[arg-type]
    snap = _snapshot(
        outcomes=(BoardSnapshotOutcome(10, 0.1, 0.2, 0.3, 0.4, 0.9),),
    )
    assert await archive.persist(snap) is True
    assert await archive.has(1, "path_a@v2") is True
    # SET NX blocks the overwrite, exactly like the filesystem existence check.
    assert await archive.persist(_snapshot(start_date="2099-01-01")) is False
    (loaded,) = await archive.list_all()
    assert loaded.tournament_start_date == "2026-06-01"
    assert loaded.outcomes[0].player_id == 10


async def test_backfilled_source_round_trips(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    await archive.persist(_snapshot(source="backfilled"))
    (loaded,) = await archive.list_all()
    assert loaded.source == "backfilled"


def test_is_out_of_sample_requires_trained_before_event() -> None:
    start = date(2026, 6, 1)
    assert _snapshot(trained_through="2026-05-31").is_out_of_sample(start) is True
    assert _snapshot(trained_through="2026-06-01").is_out_of_sample(start) is False  # not strict
    assert _snapshot(trained_through="2026-07-01").is_out_of_sample(start) is False
    assert _snapshot(trained_through=None).is_out_of_sample(start) is False  # uncertifiable


class _GradeCatalog:
    """Catalog stub for grading: one completed tournament + graded field."""

    def __init__(self, *, start_date: date, status: TournamentStatus, no_cut: bool = False) -> None:
        self._no_cut = no_cut
        self._t = Tournament(
            id=1,
            course_id=1,
            name="The Demo",
            season=2026,
            start_date=start_date,
            end_date=start_date,
            purse=None,
            field_strength=None,
            status=status,
        )
        # Player 10 won (pos 1), 11 made cut (pos 30), 12 missed cut.
        self._field = [
            TournamentEntry(
                id=1,
                tournament_id=1,
                player_id=10,
                status=EntryStatus.MADE_CUT,
                final_position=1,
                final_score_to_par=None,
                official_money_cents=None,
            ),
            TournamentEntry(
                id=2,
                tournament_id=1,
                player_id=11,
                status=EntryStatus.MADE_CUT,
                final_position=30,
                final_score_to_par=None,
                official_money_cents=None,
            ),
            TournamentEntry(
                id=3,
                tournament_id=1,
                player_id=12,
                status=EntryStatus.MISSED_CUT,
                final_position=None,
                final_score_to_par=None,
                official_money_cents=None,
            ),
        ]

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return self._t if tournament_id == 1 else None

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        if tournament_id != 1:
            return []
        if not self._no_cut:
            return list(self._field)
        # A playoff-style event: everyone plays all four rounds, nobody is cut.
        return [
            TournamentEntry(
                id=e.id,
                tournament_id=e.tournament_id,
                player_id=e.player_id,
                status=EntryStatus.MADE_CUT,
                final_position=e.final_position if e.final_position is not None else 40,
                final_score_to_par=None,
                official_money_cents=None,
            )
            for e in self._field
        ]


async def test_forward_grader_skips_in_sample_boards(tmp_path) -> None:
    """A board whose model trained after the event start is excluded."""
    archive = FileBoardArchive(tmp_path)
    await archive.persist(_snapshot(trained_through="2026-07-01"))  # trained AFTER start
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is None  # nothing qualified as out-of-sample


async def test_forward_grader_grades_out_of_sample_board(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    await archive.persist(
        _snapshot(
            trained_through="2026-05-01",  # strictly before the 06-01 start → OOS
            outcomes=(
                BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),  # winner, high
                BoardSnapshotOutcome(11, 0.02, 0.1, 0.3, 0.6, 0.85),  # made cut
                BoardSnapshotOutcome(12, 0.01, 0.05, 0.1, 0.2, 0.40),  # missed cut
            ),
        )
    )
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is not None
    assert result.events == 1
    assert result.players_graded == 3
    assert result.events_to_meaningful > 0  # one event is far from meaningful
    mc = next(m for m in result.markets if m.market == "make_cut_prob")
    assert mc.n == 3
    assert 0.0 <= mc.base_rate <= 1.0


async def test_forward_grader_ignores_incomplete_events(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    await archive.persist(_snapshot(trained_through="2026-05-01"))
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.UPCOMING)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is None


# ---------------------------------------------------------------------------
# Serving-regime provenance
#
# ``model_version_id`` is stamped "path_a@<id>" whenever Path A is *configured*,
# before any DataGolf call is made. A board where DataGolf returned nothing
# (the caching-wrapper bug fixed 2026-07-29, an outage, an uncovered event)
# therefore carries an identical label to a real Path A board while being a
# completely different product. ``dg_direct_count`` is what tells them apart.
# ---------------------------------------------------------------------------

_THREE = (
    BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),
    BoardSnapshotOutcome(11, 0.02, 0.1, 0.3, 0.6, 0.85),
    BoardSnapshotOutcome(12, 0.01, 0.05, 0.1, 0.2, 0.40),
)


async def test_dg_direct_count_round_trips(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    await archive.persist(_snapshot(outcomes=_THREE, dg_direct_count=3))
    (loaded,) = await archive.list_all()
    assert loaded.dg_direct_count == 3
    assert loaded.dg_direct_share == 1.0


def test_dg_direct_share_is_none_when_unrecorded() -> None:
    """Boards captured before the field existed must not be assumed covered."""
    assert _snapshot(outcomes=_THREE).dg_direct_share is None


def test_dg_direct_share_is_zero_for_a_fully_cold_started_board() -> None:
    """The exact shape of the bug: Path A configured, DataGolf contributed nothing."""
    snap = _snapshot(outcomes=_THREE, dg_direct_count=0, version="path_a@d69cf2a7323f")
    assert snap.dg_direct_share == 0.0
    # Indistinguishable from a healthy board by version id alone.
    assert snap.model_version_id == "path_a@d69cf2a7323f"


def test_snapshot_from_dict_tolerates_unknown_future_keys() -> None:
    """A snapshot written by a newer build must still load, not be dropped."""
    data = json.loads(_to_json(_snapshot(outcomes=_THREE, dg_direct_count=2)))
    data["some_field_added_later"] = "whatever"
    loaded = _from_dict(data)
    assert loaded.dg_direct_count == 2
    assert loaded.tournament_id == 1


def test_snapshot_from_dict_defaults_missing_dg_direct_count() -> None:
    """Legacy snapshots (no coverage recorded) load with None, not 0."""
    data = json.loads(_to_json(_snapshot(outcomes=_THREE)))
    data.pop("dg_direct_count", None)
    assert _from_dict(data).dg_direct_count is None


async def test_forward_grader_splits_events_by_serving_regime(tmp_path) -> None:
    """The aggregate must expose how many graded boards were really Path A."""
    archive = FileBoardArchive(tmp_path)
    # Healthy Path A board.
    await archive.persist(
        _snapshot(tournament_id=1, version="a", outcomes=_THREE, dg_direct_count=3)
    )
    # Path A configured but DataGolf contributed nothing → cold-start only.
    await archive.persist(
        _snapshot(tournament_id=1, version="b", outcomes=_THREE, dg_direct_count=0)
    )
    # Captured before coverage was recorded → regime genuinely unknown.
    await archive.persist(
        _snapshot(tournament_id=1, version="c", outcomes=_THREE, dg_direct_count=None)
    )
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is not None
    assert result.events == 3
    assert result.events_path_a == 1
    assert result.events_cold_start_only == 1
    assert result.events_regime_unknown == 1


# ---------------------------------------------------------------------------
# No-cut events must not be graded on the make-cut market
#
# The FedExCup playoff events and several limited-field events play four rounds
# with no 36-hole cut. DataGolf reports make_cut = 1.0 there and every player is
# graded as having made it, so the market is a free perfect prediction on
# something that never happened. Pooling those rows inflates the make-cut skill
# score, which is the market this product claims as its strongest.
# ---------------------------------------------------------------------------


async def test_no_cut_event_is_excluded_from_the_make_cut_market(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    await archive.persist(_snapshot(outcomes=_THREE, dg_direct_count=3))
    catalog = _GradeCatalog(
        start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED, no_cut=True
    )
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is not None
    # The event still grades on the finish-position markets.
    assert result.events == 1
    graded = {m.market for m in result.markets}
    assert "top_20_prob" in graded
    # ...but contributes nothing to make-cut.
    assert "make_cut_prob" not in graded


async def test_event_with_a_real_cut_still_grades_make_cut(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    await archive.persist(_snapshot(outcomes=_THREE, dg_direct_count=3))
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is not None
    assert "make_cut_prob" in {m.market for m in result.markets}


async def test_no_cut_event_does_not_inflate_pooled_make_cut_skill(tmp_path) -> None:
    """The point of the exclusion: the number must not move when one is added."""
    real = FileBoardArchive(tmp_path / "real")
    (tmp_path / "real").mkdir()
    await real.persist(_snapshot(tournament_id=1, version="a", outcomes=_THREE))
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    before = await compute_forward_track_record(archive=real, catalog=catalog)  # type: ignore[arg-type]

    mixed = FileBoardArchive(tmp_path / "mixed")
    (tmp_path / "mixed").mkdir()
    await mixed.persist(_snapshot(tournament_id=1, version="a", outcomes=_THREE))
    await mixed.persist(_snapshot(tournament_id=1, version="b", outcomes=_THREE))

    class _Mixed(_GradeCatalog):
        """Second board lands on a no-cut event."""

        def __init__(self) -> None:
            super().__init__(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
            self._calls = 0

        async def get_tournament_field(self, tournament_id: int):  # noqa: ANN201
            self._calls += 1
            if self._calls > 1:  # the second board grades against a no-cut field
                self._no_cut = True
            return await super().get_tournament_field(tournament_id)

    after = await compute_forward_track_record(archive=mixed, catalog=_Mixed())  # type: ignore[arg-type]
    assert before is not None and after is not None
    mc_before = next(m for m in before.markets if m.market == "make_cut_prob")
    mc_after = next(m for m in after.markets if m.market == "make_cut_prob")
    # Same graded make-cut sample as before: the no-cut event added nothing.
    assert mc_after.n == mc_before.n
    assert mc_after.brier_skill == pytest.approx(mc_before.brier_skill)
