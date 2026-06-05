"""Feature engineering foundation — doc 02 §3.

The single most important property of a feature pipeline is identical
computation in training and inference. We enforce that here by having one
place where features are defined, called from both paths.

Every feature is a pure function from ``FeatureContext`` to a float, with
a declared dependency on upstream features. The ``FeatureRegistry``
topologically orders them; the ``FeatureSet`` produces a deterministic hash
that goes into ``model_versions.feature_set_hash`` so we can answer
"is this prediction stale because the feature definitions changed?" with
a single column comparison.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from app.domain.models import Round


@dataclass(frozen=True)
class DatedRound:
    """A round with the calendar date it was played.

    ``Round`` itself doesn't carry the played date — the date lives on the
    round's tournament entry's tournament. The registry resolves that lookup
    once and hands features a flat sequence of ``DatedRound`` so the feature
    code stays purely numerical.
    """

    round: Round
    played_on: date


@dataclass(frozen=True)
class FeatureContext:
    """Everything a feature needs to produce a value for one (player, date).

    Features must only read from this context — never from globals, a
    database connection, or the network. That discipline is what makes the
    training/inference computations bit-identical.
    """

    player_id: int
    as_of_date: date
    rounds: tuple[DatedRound, ...]


class Feature(ABC):
    """A pure function from ``FeatureContext`` to a numeric value.

    Subclasses set the three class attributes (``name``, ``version``,
    ``depends_on``) and implement ``compute``. ``version`` is bumped any
    time the implementation changes so old predictions can be detected as
    stale via the feature-set hash.
    """

    name: str
    version: int
    depends_on: tuple[str, ...] = ()

    @abstractmethod
    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        """Return the feature value for this ``(player_id, as_of_date)``."""

    @property
    def signature(self) -> str:
        """Stable string identifier used in the ``FeatureSet`` hash."""
        return f"{self.name}@v{self.version}"

    def __hash__(self) -> int:
        return hash(self.signature)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Feature):
            return NotImplemented
        return self.signature == other.signature


class FeatureSet:
    """A named, versioned composition of features with a deterministic hash."""

    def __init__(self, name: str, features: Iterable[Feature]) -> None:
        self.name = name
        # Sort by feature name so the hash is stable regardless of insertion
        # order. Two FeatureSets with the same features in different orders
        # must produce the same hash.
        self.features: tuple[Feature, ...] = tuple(
            sorted(features, key=lambda f: f.name)
        )

    @property
    def hash(self) -> str:
        """SHA-256 hex digest of the sorted feature signatures."""
        payload = json.dumps([f.signature for f in self.features]).encode()
        return hashlib.sha256(payload).hexdigest()


class FeatureRegistry:
    """Topologically orders features and runs them on a ``FeatureContext``.

    Construction performs the topological sort once and caches it. Cycles
    and missing dependencies raise ``ValueError`` at construction time, not
    at compute time — fail fast.
    """

    def __init__(self, features: Iterable[Feature]) -> None:
        self.features: dict[str, Feature] = {f.name: f for f in features}
        self._order: tuple[str, ...] = self._topological_sort()

    @property
    def order(self) -> tuple[str, ...]:
        return self._order

    def _topological_sort(self) -> tuple[str, ...]:
        """Kahn's algorithm — detects cycles by counting unresolved nodes."""
        in_degree: dict[str, int] = dict.fromkeys(self.features, 0)
        for feature in self.features.values():
            for dep in feature.depends_on:
                if dep not in self.features:
                    raise ValueError(
                        f"Feature {feature.name!r} depends on {dep!r}, which is"
                        f" not registered. Add it to the FeatureSet."
                    )
                in_degree[feature.name] += 1

        ready = [name for name, count in in_degree.items() if count == 0]
        order: list[str] = []
        while ready:
            name = ready.pop(0)
            order.append(name)
            for other in self.features.values():
                if name in other.depends_on:
                    in_degree[other.name] -= 1
                    if in_degree[other.name] == 0:
                        ready.append(other.name)

        if len(order) < len(self.features):
            unresolved = [n for n in self.features if n not in order]
            raise ValueError(
                f"Cyclic feature dependency detected among: {unresolved}"
            )
        return tuple(order)

    def compute(self, context: FeatureContext) -> dict[str, float]:
        """Run every feature once and return ``{name: value}``."""
        values: dict[str, float] = {}
        for name in self._order:
            feature = self.features[name]
            deps = {d: values[d] for d in feature.depends_on}
            values[name] = feature.compute(context, deps)
        return values
