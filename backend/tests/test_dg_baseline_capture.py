"""Pinning DataGolf's own probabilities onto the captured board (A4a).

Storage only — nothing grades this column yet (that is A4b). What these tests
protect is the property that makes the column possible at all: the baseline
has to be recorded at capture, because DataGolf's pre-tournament feed keeps
moving and, for a finished event, returns numbers informed by the finish. A
baseline fetched at grading time would not be a prediction, so a board
captured without one can never carry the column.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.services.board_archive import (
    BoardSnapshot,
    BoardSnapshotOutcome,
    FileBoardArchive,
    _from_dict,
    _to_json,
    snapshot_from_predictions,
)
from tests.test_prediction_service import _path_a_service, _StubCatalog, _StubExtractor

_DG = {
    11: {
        "win_prob": 0.30,
        "top_5_prob": 0.5,
        "top_10_prob": 0.6,
        "top_20_prob": 0.8,
        "make_cut_prob": 0.95,
    },
    12: {
        "win_prob": 0.02,
        "top_5_prob": 0.1,
        "top_10_prob": 0.2,
        "top_20_prob": 0.4,
        "make_cut_prob": 0.7,
    },
}


async def test_predictions_carry_datagolf_raw_probabilities() -> None:
    result = await _path_a_service(_DG).predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert result.dg_baseline == _DG
    # One row per covered player, matching the coverage count exactly.
    assert len(result.dg_baseline or {}) == result.dg_direct_count


async def test_baseline_is_datagolf_raw_not_the_served_board() -> None:
    """The stored numbers must be what DataGolf published, before
    ``coherent_outcomes`` and ``normalize_field`` reshape them. If they were
    taken after normalization the baseline would be partly our own pipeline,
    and beating it would prove nothing about beating DataGolf.
    """
    result = await _path_a_service(_DG).predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert (result.dg_baseline or {})[11]["win_prob"] == 0.30
    served = next(o for o in result.outcomes if o.player_id == 11)
    # Field normalization rescales win probabilities to sum to one, so the
    # served number has moved off DataGolf's raw one.
    assert served.win_prob != pytest.approx(0.30)
    assert sum(o.win_prob for o in result.outcomes) == pytest.approx(1.0)


async def test_uncovered_path_a_board_records_an_empty_baseline_not_none() -> None:
    """Path A running with zero DataGolf coverage is a materially different
    board from one where Path A was never configured, and the two must stay
    distinguishable — the same reason ``dg_direct_count`` exists."""
    degraded = await _path_a_service({}).predict_tournament(1, as_of=date(2026, 5, 30))
    assert degraded is not None
    assert degraded.dg_baseline == {}

    from app.ml.base import ConstantModel
    from app.services.predictions import PredictionService

    stacked = PredictionService(
        catalog=_StubCatalog(),  # type: ignore[arg-type]
        extractor=_StubExtractor(),  # type: ignore[arg-type]
        model=ConstantModel(
            {
                "win_prob": 0.01,
                "top_5_prob": 0.05,
                "top_10_prob": 0.1,
                "top_20_prob": 0.2,
                "make_cut_prob": 0.6,
            }
        ),
        model_name="golf_v1",
        model_version_id="stacked",
    )
    result = await stacked.predict_tournament(1, as_of=date(2026, 5, 30))
    assert result is not None
    assert result.dg_baseline is None


async def test_capture_pins_the_baseline_onto_the_snapshot(tmp_path) -> None:
    preds = await _path_a_service(_DG).predict_tournament(1, as_of=date(2026, 5, 30))
    assert preds is not None
    snapshot = snapshot_from_predictions(
        preds,
        tournament_start_date=date(2026, 6, 1),
        model_trained_through=date(2026, 5, 1),
    )
    assert snapshot.dg_baseline is not None
    # Sorted by player id, so an unchanged archive still exports identically.
    assert [row.player_id for row in snapshot.dg_baseline] == [11, 12]
    assert snapshot.dg_baseline[0].win_prob == 0.30

    archive = FileBoardArchive(tmp_path)
    assert await archive.persist(snapshot) is True
    assert (await archive.list_all())[0].dg_baseline == snapshot.dg_baseline


def test_absent_and_empty_baselines_stay_distinguishable_through_storage() -> None:
    """A pre-A4a snapshot (no key at all) must reload as ``None``, not ``()``.
    Reading an empty tuple as "DataGolf covered nobody" when the truth is
    "we did not record it" would be a false claim about the record.
    """

    def _snap(**kwargs: object) -> BoardSnapshot:
        return BoardSnapshot(
            tournament_id=1,
            tournament_name="The Demo",
            tournament_start_date="2026-06-01",
            model_name="golf_v1",
            model_version_id="path_a@v2",
            feature_set_hash="deadbeef",
            model_trained_through="2026-05-01",
            as_of="2026-05-31",
            captured_at="2026-05-31T12:00:00+00:00",
            outcomes=(BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),),
            **kwargs,  # type: ignore[arg-type]
        )

    legacy = json.loads(_to_json(_snap()))
    legacy.pop("dg_baseline")  # a snapshot written before the field existed
    assert _from_dict(legacy).dg_baseline is None

    covered_nobody = _snap(dg_baseline=())
    assert _from_dict(json.loads(_to_json(covered_nobody))).dg_baseline == ()

    populated = _snap(dg_baseline=(BoardSnapshotOutcome(11, 0.3, 0.5, 0.6, 0.8, 0.95),))
    assert _from_dict(json.loads(_to_json(populated))) == populated
