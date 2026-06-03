"""Mock data generator — produces statistically plausible PGA Tour data.

Generates 5 seasons × ~40 tournaments × ~156-player fields ≈ 100k+ rounds,
all from a single seed for bit-identical reproducibility (doc 02 §6).

The scoring model decomposes total SG into 4 components (sg_ott, sg_app,
sg_arg, sg_putt) sampled correlated within the long game and independently
for putting, matching real PGA Tour statistical structure. Each player's
4 rounds in a tournament share a per-tournament factor that produces the
0.2–0.3 round-to-round correlation observed in real data (doc 02 §6).

Calibration targets are verified by ``tests/calibration/`` against the
generated output:

* Mean round score: ~70.5–71.5
* Round score std dev: ~2.5–3.0
* Top player SG:Total: ~+2.0 vs field average
* Round-to-round correlation: ~0.2–0.3
* % making cut: ~50%
* SG:OTT/SG:APP correlation: ~0.3; SG:PUTT ~ independent
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

import numpy as np

from app.domain.enums import CourseType, EntryStatus, MarketKind, TournamentStatus
from app.domain.models import (
    BettingLine,
    Course,
    Player,
    Round,
    Tournament,
    TournamentEntry,
)
from app.providers.mock.courses import LOCATIONS, NAME_PREFIXES, NAME_SUFFIXES
from app.providers.mock.names import COUNTRIES, FIRST_NAMES, LAST_NAMES

if TYPE_CHECKING:
    from numpy.random import Generator


# Calibration constants (doc 02 §6) — tuned so the validation suite passes.
N_PLAYERS = 250
N_COURSES = 50
SEASONS = (2022, 2023, 2024, 2025, 2026)
TOURNAMENTS_PER_SEASON = 40
FIELD_SIZE = 156
CUT_LINE_PLAYERS = 65  # "top 65 + ties" — we use rank-65 cutoff and include ties

# Latent player-skill standard deviations across the population (strokes/round).
# Tuned so per-round SG std falls in the 2.5–3.0 target.
SKILL_STDS = {"ott": 0.45, "app": 0.65, "arg": 0.35, "putt": 0.50}

# Inter-skill correlation (long game positively correlated, putt nearly indep).
SKILL_CORR_LONG_GAME = 0.30  # ott↔app, ott↔arg, app↔arg
SKILL_CORR_PUTT = 0.0  # putt independent of long game

# Per-round noise components.
TOURNAMENT_PLAYER_FACTOR_STD = 1.25  # shared across a player's 4 rounds in a tournament
ROUND_NOISE_STD = 2.17  # independent across rounds
# These together produce round-to-round correlation ~0.25 conditional on skill.

# Tournament-wide scoring conditions shock (windy week → all players worse).
TOURNAMENT_CONDITIONS_STD = 0.40

# SG → score conversion. score_to_par = -SG_total + course_difficulty.
# Course difficulty centred so mean field score is ~71 strokes.
PAR_BASE = 71

BOOKS: tuple[str, ...] = (
    "DraftKings",
    "FanDuel",
    "BetMGM",
    "Caesars",
    "BetRivers",
    "PointsBet",
    "WynnBET",
    "Bet365",
    "Unibet",
    "PinnacleSports",
    "Circa",
)

MARKETS: tuple[MarketKind, ...] = (
    MarketKind.WIN,
    MarketKind.TOP_5,
    MarketKind.TOP_10,
    MarketKind.TOP_20,
    MarketKind.MAKE_CUT,
)
VIG = 0.06  # 6% sportsbook hold per market


@dataclass(frozen=True, slots=True)
class MockDataset:
    """Immutable snapshot of every entity the generator produces.

    All collections are in deterministic ID order — same seed yields the
    same bytes.
    """

    players: list[Player]
    courses: list[Course]
    tournaments: list[Tournament]
    entries: list[TournamentEntry]
    rounds: list[Round]
    betting_lines: list[BettingLine]
    generated_at: datetime


def generate(seed: int = 42) -> MockDataset:
    """Build the dataset from a single seed."""
    rng = np.random.default_rng(seed)

    players = _generate_players(rng)
    courses = _generate_courses(rng)
    tournaments = _generate_tournaments(rng, courses)

    # Pre-compute each player's latent SG-component skills so the same player
    # appears in many tournaments with consistent ability.
    skill_matrix = _sample_player_skills(rng, n=len(players))  # shape (N, 4)
    overall_rating = skill_matrix.sum(axis=1)  # sg_total skill per player

    entries, rounds = _generate_entries_and_rounds(
        rng,
        players=players,
        courses_by_id={c.id: c for c in courses},
        tournaments=tournaments,
        skill_matrix=skill_matrix,
        overall_rating=overall_rating,
    )

    betting_lines = _generate_betting_lines(
        rng,
        players=players,
        tournaments=tournaments,
        overall_rating=overall_rating,
        entries=entries,
    )

    return MockDataset(
        players=players,
        courses=courses,
        tournaments=tournaments,
        entries=entries,
        rounds=rounds,
        betting_lines=betting_lines,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# --- Players ----------------------------------------------------------------


def _generate_players(rng: Generator) -> list[Player]:
    countries, country_weights = zip(*COUNTRIES, strict=True)
    country_p = np.array(country_weights, dtype=float)
    country_p /= country_p.sum()

    first_idx = rng.integers(0, len(FIRST_NAMES), size=N_PLAYERS)
    last_idx = rng.integers(0, len(LAST_NAMES), size=N_PLAYERS)
    country_pick = rng.choice(np.array(countries), size=N_PLAYERS, p=country_p)

    # Ages 21–50 with a Gaussian peak around 30
    ages = np.clip(rng.normal(30, 6, N_PLAYERS), 21, 50).astype(int)
    # Approximate DoB; we anchor at season=2024 since that's mid-dataset
    dobs = [date(2024 - int(a), 6, 15) for a in ages]
    turned_pro = [int(2024 - int(a) + 21) for a in ages]  # mostly turn pro at 21

    players: list[Player] = []
    for i in range(N_PLAYERS):
        full_name = f"{FIRST_NAMES[int(first_idx[i])]} {LAST_NAMES[int(last_idx[i])]}"
        players.append(
            Player(
                id=i + 1,
                dg_id=10_000 + i,  # synthetic DG ids
                full_name=full_name,
                country=str(country_pick[i]),
                dob=dobs[i],
                turned_pro=turned_pro[i],
            )
        )
    return players


def _sample_player_skills(rng: Generator, *, n: int) -> np.ndarray:
    """Return shape (n, 4) array of (sg_ott, sg_app, sg_arg, sg_putt) skill
    means per player, sampled from a correlated MVN.
    """
    stds = np.array([SKILL_STDS["ott"], SKILL_STDS["app"], SKILL_STDS["arg"], SKILL_STDS["putt"]])
    corr = np.array(
        [
            [1.0, SKILL_CORR_LONG_GAME, SKILL_CORR_LONG_GAME, SKILL_CORR_PUTT],
            [SKILL_CORR_LONG_GAME, 1.0, SKILL_CORR_LONG_GAME, SKILL_CORR_PUTT],
            [SKILL_CORR_LONG_GAME, SKILL_CORR_LONG_GAME, 1.0, SKILL_CORR_PUTT],
            [SKILL_CORR_PUTT, SKILL_CORR_PUTT, SKILL_CORR_PUTT, 1.0],
        ]
    )
    cov = corr * np.outer(stds, stds)
    return rng.multivariate_normal(mean=np.zeros(4), cov=cov, size=n)


# --- Courses ----------------------------------------------------------------


def _generate_courses(rng: Generator) -> list[Course]:
    courses: list[Course] = []
    course_types = list(CourseType)
    for i in range(N_COURSES):
        prefix = NAME_PREFIXES[i % len(NAME_PREFIXES)]
        suffix = NAME_SUFFIXES[(i * 7) % len(NAME_SUFFIXES)]
        location = LOCATIONS[(i * 11) % len(LOCATIONS)]
        par = int(rng.choice([70, 71, 72, 72, 72, 73], 1)[0])
        yardage = int(rng.normal(7300, 200))
        yardage = max(6500, min(8000, yardage))
        course_type = course_types[int(rng.integers(0, len(course_types)))]
        courses.append(
            Course(
                id=i + 1,
                name=f"{prefix} {suffix}",
                location=location,
                par=par,
                yardage=yardage,
                course_type=course_type,
                avg_score=None,
            )
        )
    return courses


# --- Tournaments ------------------------------------------------------------


def _generate_tournaments(rng: Generator, courses: list[Course]) -> list[Tournament]:
    tournaments: list[Tournament] = []
    tournament_id = 1
    today = date(2026, 6, 3)  # reference for status calc — matches the build clock

    for season in SEASONS:
        # Roughly weekly events between mid-January and late-November
        starts = _season_schedule(season, n=TOURNAMENTS_PER_SEASON)
        for week_idx, start in enumerate(starts):
            course = courses[(tournament_id * 13) % len(courses)]
            end = start + timedelta(days=3)
            status = _status_for(start, end, today)
            tournaments.append(
                Tournament(
                    id=tournament_id,
                    course_id=course.id,
                    name=f"{course.name} {season} Open",
                    season=season,
                    start_date=start,
                    end_date=end,
                    purse=int(rng.integers(8_000_000, 25_000_000)) // 1000 * 1000,
                    field_strength=None,
                    status=status,
                )
            )
            tournament_id += 1
            _ = week_idx
    return tournaments


def _season_schedule(season: int, *, n: int) -> list[date]:
    """Roughly weekly tournament starts from mid-Jan through late November."""
    start = date(season, 1, 12)  # second Thursday of January (approx)
    return [start + timedelta(weeks=i) for i in range(n)]


def _status_for(start: date, end: date, today: date) -> TournamentStatus:
    if today < start:
        return TournamentStatus.UPCOMING
    if today <= end:
        return TournamentStatus.IN_PROGRESS
    return TournamentStatus.COMPLETED


# --- Entries + rounds (the core scoring model) ------------------------------


def _generate_entries_and_rounds(
    rng: Generator,
    *,
    players: list[Player],
    courses_by_id: dict[int, Course],
    tournaments: list[Tournament],
    skill_matrix: np.ndarray,
    overall_rating: np.ndarray,
) -> tuple[list[TournamentEntry], list[Round]]:
    entries: list[TournamentEntry] = []
    rounds: list[Round] = []
    entry_id = 1
    round_id = 1

    # Field-selection probability — skill-weighted, softmaxed.
    field_pick_logits = overall_rating * 1.5  # mild preference for better players

    for t in tournaments:
        course = courses_by_id[t.course_id]
        # Sample field for this tournament
        field_idx = _sample_field(rng, field_pick_logits, size=FIELD_SIZE)

        # Tournament-wide conditions shock
        conditions_factor = float(rng.normal(0, TOURNAMENT_CONDITIONS_STD))

        # Per-player-per-tournament factor (shared across the 4 rounds)
        player_factor = rng.normal(0.0, TOURNAMENT_PLAYER_FACTOR_STD, size=FIELD_SIZE)

        # Per-round, per-component noise. Sampled correlated within the long
        # game (so the per-round sg_ott/sg_app correlation isn't washed out
        # by independent noise) and independent for putting. Shape:
        # (FIELD_SIZE, 4 rounds, 4 components).
        noise_per_component_std = ROUND_NOISE_STD / 2.0
        noise_stds = np.full(4, noise_per_component_std)
        noise_corr = np.array(
            [
                [1.0, SKILL_CORR_LONG_GAME, SKILL_CORR_LONG_GAME, SKILL_CORR_PUTT],
                [SKILL_CORR_LONG_GAME, 1.0, SKILL_CORR_LONG_GAME, SKILL_CORR_PUTT],
                [SKILL_CORR_LONG_GAME, SKILL_CORR_LONG_GAME, 1.0, SKILL_CORR_PUTT],
                [SKILL_CORR_PUTT, SKILL_CORR_PUTT, SKILL_CORR_PUTT, 1.0],
            ]
        )
        noise_cov = noise_corr * np.outer(noise_stds, noise_stds)
        round_noise = rng.multivariate_normal(mean=np.zeros(4), cov=noise_cov, size=(FIELD_SIZE, 4))

        # SG-component skill for selected players, shape (FIELD_SIZE, 4)
        player_skills = skill_matrix[field_idx]

        # Build R1 and R2 SG totals (everyone plays these)
        # round_sg_total[i, r] = sum over components of (skill + noise) + factor + conditions
        r12_sg_components = player_skills[:, np.newaxis, :] + round_noise[:, :2, :]
        r12_sg_total = (
            r12_sg_components.sum(axis=2) + player_factor[:, np.newaxis] + conditions_factor
        )

        # Apply cut after R2: sort by combined score_to_par over the first 2 rds
        combined_score_to_par_r12 = -r12_sg_total.sum(axis=1)
        cut_order = np.argsort(combined_score_to_par_r12, kind="stable")
        made_cut_mask = np.zeros(FIELD_SIZE, dtype=bool)
        made_cut_mask[cut_order[:CUT_LINE_PLAYERS]] = True

        # Include ties at the cut line
        cut_value = combined_score_to_par_r12[cut_order[CUT_LINE_PLAYERS - 1]]
        made_cut_mask |= combined_score_to_par_r12 <= cut_value

        # R3 + R4 only for made-cut players
        r34_sg_components = player_skills[:, np.newaxis, :] + round_noise[:, 2:, :]
        r34_sg_total = (
            r34_sg_components.sum(axis=2) + player_factor[:, np.newaxis] + conditions_factor
        )

        # Compute final positions for made-cut players
        full_score_to_par = combined_score_to_par_r12 - r34_sg_total.sum(axis=1)
        # Final position only meaningful for those who made cut
        final_rank = np.full(FIELD_SIZE, -1, dtype=int)
        made_cut_idx = np.where(made_cut_mask)[0]
        order_within_made = np.argsort(full_score_to_par[made_cut_idx], kind="stable")
        for pos, mi in enumerate(made_cut_idx[order_within_made], start=1):
            final_rank[mi] = pos

        # Build entries + rounds
        for slot, pl_idx in enumerate(field_idx):
            player = players[pl_idx]
            made = bool(made_cut_mask[slot])
            status = EntryStatus.MADE_CUT if made else EntryStatus.MISSED_CUT
            # Only assign final_position to completed events for realism
            assign_finals = t.status == TournamentStatus.COMPLETED and made
            entries.append(
                TournamentEntry(
                    id=entry_id,
                    tournament_id=t.id,
                    player_id=player.id,
                    status=(
                        status if t.status == TournamentStatus.COMPLETED else EntryStatus.ACTIVE
                    ),
                    final_position=(int(final_rank[slot]) if assign_finals else None),
                    final_score_to_par=(
                        int(round(float(full_score_to_par[slot]))) if assign_finals else None
                    ),
                    official_money_cents=None,
                ),
            )

            # Emit rounds only for COMPLETED events; UPCOMING and IN_PROGRESS
            # tournaments have entries but no rounds yet. Phase 2 may add
            # partial in-progress data.
            if t.status != TournamentStatus.COMPLETED:
                entry_id += 1
                continue

            n_rounds = 4 if made else 2
            for rn in range(n_rounds):
                if rn < 2:
                    sg_components = r12_sg_components[slot, rn]  # (4,)
                    sg_total_round = float(r12_sg_total[slot, rn])
                else:
                    sg_components = r34_sg_components[slot, rn - 2]
                    sg_total_round = float(r34_sg_total[slot, rn - 2])

                # Distribute the tournament-shared shock (player_factor +
                # conditions_factor) equally across the 4 components so the
                # *stored* SG values include them. Without this the
                # round-to-round correlation in the stored data drops to the
                # skill-only contribution and misses doc 02 §6's 0.2-0.3
                # target.
                extra = (sg_total_round - float(sg_components.sum())) / 4.0
                sg_ott, sg_app, sg_arg, sg_putt = (float(x + extra) for x in sg_components)
                sg_t2g = sg_ott + sg_app + sg_arg
                sg_total = sg_t2g + sg_putt  # equals sg_total_round by construction

                score_to_par_round = -int(round(sg_total))
                score = course.par + score_to_par_round
                # Clamp into the model's CheckConstraint range
                score = max(55, min(95, score))
                score_to_par_round = score - course.par

                tee_time_dt = datetime.combine(
                    t.start_date + timedelta(days=rn),
                    time(hour=13, minute=0),
                    tzinfo=UTC,
                )

                rounds.append(
                    Round(
                        id=round_id,
                        entry_id=entry_id,
                        round_number=rn + 1,
                        score=int(score),
                        score_to_par=int(score_to_par_round),
                        tee_time=tee_time_dt,
                        sg_ott=round(sg_ott, 3),
                        sg_app=round(sg_app, 3),
                        sg_arg=round(sg_arg, 3),
                        sg_putt=round(sg_putt, 3),
                        sg_t2g=round(sg_t2g, 3),
                        sg_total=round(sg_total, 3),
                        driving_distance_avg=float(rng.normal(298, 12)),
                        fairways_hit=int(rng.integers(5, 13)),
                        gir=int(rng.integers(8, 16)),
                        putts=int(rng.integers(25, 34)),
                    )
                )
                round_id += 1

            entry_id += 1

    return entries, rounds


def _sample_field(rng: Generator, logits: np.ndarray, *, size: int) -> np.ndarray:
    """Sample ``size`` player indices without replacement, weighted by logits."""
    p = np.exp(logits - logits.max())
    p /= p.sum()
    return rng.choice(len(logits), size=size, replace=False, p=p)


# --- Betting lines ----------------------------------------------------------


def _generate_betting_lines(
    rng: Generator,
    *,
    players: list[Player],
    tournaments: list[Tournament],
    overall_rating: np.ndarray,
    entries: list[TournamentEntry],
) -> list[BettingLine]:
    """Generate betting lines for each (tournament, player, market, book).

    Implied probability is derived from the player's overall_rating relative
    to field strength, then we add ``VIG`` and book-specific noise to get
    plausible odds spreads across books.
    """
    # Index entries by tournament so we know who is in each field
    entries_by_t: dict[int, list[TournamentEntry]] = {}
    for e in entries:
        entries_by_t.setdefault(e.tournament_id, []).append(e)

    lines: list[BettingLine] = []
    line_id = 1
    captured = datetime(2026, 1, 1, tzinfo=UTC)

    for t in tournaments:
        # Live odds markets only exist for upcoming + in-progress events
        if t.status not in (TournamentStatus.UPCOMING, TournamentStatus.IN_PROGRESS):
            continue
        field_entries = entries_by_t.get(t.id, [])
        if not field_entries:
            continue
        field_player_ids = [e.player_id for e in field_entries]
        field_skills = overall_rating[np.array(field_player_ids) - 1]
        # softmax-style win probabilities
        w_logits = field_skills * 0.9
        w_probs = np.exp(w_logits - w_logits.max())
        w_probs /= w_probs.sum()

        market_factor = {
            MarketKind.WIN: 1.0,
            MarketKind.TOP_5: 5.0,
            MarketKind.TOP_10: 10.0,
            MarketKind.TOP_20: 20.0,
            MarketKind.MAKE_CUT: 80.0,
        }

        for market in MARKETS:
            base_probs = np.clip(w_probs * market_factor[market], 0.005, 0.99)
            for book in BOOKS:
                noise = rng.normal(1.0, 0.05, size=len(field_player_ids))
                book_probs = np.clip(base_probs * noise, 0.005, 0.99)
                for pi, prob in enumerate(book_probs):
                    decimal_odds = (1.0 - VIG) / float(prob)
                    if decimal_odds <= 1.01:
                        continue
                    lines.append(
                        BettingLine(
                            id=line_id,
                            tournament_id=t.id,
                            player_id=field_player_ids[pi],
                            book_name=book,
                            market=market,
                            decimal_odds=round(decimal_odds, 3),
                            implied_prob=round(float(prob), 5),
                            captured_at=captured,
                        )
                    )
                    line_id += 1
    return lines
