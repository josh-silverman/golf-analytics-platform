"""Simulation service — wires catalog + features into the MC engine.

The skill signal feeding the simulation is ``sg_total_rating`` from the
feature extractor, negated into an expected strokes-to-par per round.
Positive SG total means the player gains strokes relative to the field, so
their expected score is *negative* (under par) — hence the negation.

This is the Approach C model (doc 01 §3 Decision 4): features → expected
score → MC simulation → outcome probabilities.  It produces coherent
probability sets by construction: win ≤ top-5 ≤ top-10 ≤ made-cut by
definition, unlike per-outcome classifiers that can violate these bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.simulation.engine import (
    DEFAULT_CUT_LINE,
    DEFAULT_N_ITERATIONS,
    DEFAULT_SCORE_STD,
    PlayerEntry,
    TournamentSimulation,
    simulate,
)

if TYPE_CHECKING:
    from datetime import date

    import numpy as np

    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor

# Feature key we use as the skill proxy.  SG total is the best single
# predictor of scoring outcome and is what the v1 feature set computes.
_SKILL_FEATURE = "sg_total_rating"


@dataclass(frozen=True)
class SimulationConfig:
    n_iterations: int = DEFAULT_N_ITERATIONS
    score_std: float = DEFAULT_SCORE_STD
    cut_line: int = DEFAULT_CUT_LINE


class SimulationService:
    """Orchestrates feature extraction and MC simulation for one tournament."""

    def __init__(
        self,
        *,
        catalog: CatalogService,
        extractor: FeatureExtractor,
        config: SimulationConfig | None = None,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor
        self._config = config or SimulationConfig()

    async def simulate_tournament(
        self,
        tournament_id: int,
        *,
        as_of: date,
        rng: np.random.Generator | None = None,
    ) -> TournamentSimulation | None:
        """Simulate ``tournament_id`` as of ``as_of``.

        Returns ``None`` if the tournament doesn't exist so the endpoint can
        translate to a 404 without raising from the service layer.
        """
        tournament = await self._catalog.get_tournament(tournament_id)
        if tournament is None:
            return None

        field = await self._catalog.get_tournament_field(tournament_id)
        entries: list[PlayerEntry] = []
        for entry in field:
            player = await self._catalog.get_player(entry.player_id)
            if player is None:
                continue
            extraction = await self._extractor.extract(entry.player_id, as_of)
            # sg_total_rating > 0 → gains strokes → expected score < 0 (under par)
            skill = extraction.values.get(_SKILL_FEATURE, 0.0)
            entries.append(
                PlayerEntry(
                    player_id=player.id,
                    player_name=player.full_name,
                    expected_score=-skill,
                    score_std=self._config.score_std,
                )
            )

        cfg = self._config
        outcomes = simulate(
            entries,
            n_iterations=cfg.n_iterations,
            score_std=cfg.score_std,
            cut_line=cfg.cut_line,
            rng=rng,
        )

        return TournamentSimulation(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            as_of=as_of,
            n_iterations=cfg.n_iterations,
            score_std=cfg.score_std,
            outcomes=outcomes,
        )
