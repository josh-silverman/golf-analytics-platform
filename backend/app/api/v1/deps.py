"""FastAPI dependency providers for the v1 API.

Lifecycle: ``CatalogService`` is per-request; the underlying ``DataProvider``
is process-cached by ``get_data_provider`` so the mock dataset isn't
re-generated on every request. The ``ModelRegistry`` is also process-cached
so the active-model lookup doesn't touch the filesystem on every request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends

from app.config import get_settings
from app.features.feature_sets import v2_field_relative, v3_dg_preds
from app.ml.base import ConstantModel
from app.ml.registry import ModelRegistry
from app.providers.factory import get_data_provider
from app.services.board_archive import (
    BoardArchive,
    FileBoardArchive,
    RedisBoardArchive,
)
from app.services.catalog import CatalogService
from app.services.features import FeatureExtractor
from app.services.predictions import PathASource, PredictionService

if TYPE_CHECKING:
    from datetime import date

    from app.features.base import FeatureSet
    from app.ml.base import Model
    from app.providers.base import DataProvider


def _feature_set_for_active_model() -> FeatureSet:
    """The feature set matching the active golf model's ``feature_set_hash``.

    The extractor must compute exactly the features the active model was
    trained against, or serving silently defaults the missing ones and skews
    predictions. Falls back to ``v2_field_relative`` when no model is active or
    the hash is unrecognised, so a fresh environment behaves exactly as before.
    """
    factories = (v2_field_relative, v3_dg_preds)
    by_hash = {factory().hash: factory for factory in factories}
    registry = get_model_registry()
    active = registry.get_active(get_settings().active_model_name)
    if active is not None:
        factory = by_hash.get(active.feature_set_hash)
        if factory is not None:
            return factory()
    return v2_field_relative()


# Outputs the fallback model serves when no real model has been registered.
# A flat ~10% top-10 rate sits in the right neighborhood for a typical PGA
# Tour field; the leaderboard sorts by win_prob so all rows tie at 0.5%.
_FALLBACK_OUTCOMES: dict[str, float] = {
    "win_prob": 0.005,
    "top_5_prob": 0.05,
    "top_10_prob": 0.10,
    "top_20_prob": 0.20,
    "make_cut_prob": 0.65,
}


def _provider_dep() -> DataProvider:
    return get_data_provider()


def get_catalog_service(
    provider: DataProvider = Depends(_provider_dep),  # noqa: B008 — FastAPI DI
) -> CatalogService:
    return CatalogService(provider)


def get_feature_extractor(
    provider: DataProvider = Depends(_provider_dep),  # noqa: B008 — FastAPI DI
) -> FeatureExtractor:
    return FeatureExtractor(provider, feature_set=_feature_set_for_active_model())


@lru_cache(maxsize=1)
def get_model_registry() -> ModelRegistry:
    """Process-cached registry rooted at the configured directory."""
    return ModelRegistry(Path(get_settings().model_registry_path))


@lru_cache(maxsize=1)
def get_board_archive() -> BoardArchive:
    """Process-cached forward prediction-board archive.

    Redis-backed in production (the service disk is ephemeral and would drop the
    archive on every redeploy); filesystem-backed otherwise, so dev and tests
    stay dependency-free.
    """
    settings = get_settings()
    if settings.board_archive_backend == "redis":
        from app.cache.redis import redis_client

        return RedisBoardArchive(redis_client)
    return FileBoardArchive(Path(settings.prediction_boards_path))


def _resolve_active_model() -> tuple[Model, str, str | None]:
    """Return ``(model, name, version_id)`` for the active golf model.

    Falls back to the ConstantModel when no version is marked active so
    the predictions endpoint stays usable in fresh environments.
    """
    registry = get_model_registry()
    name = get_settings().active_model_name
    active = registry.get_active(name)
    if active is None:
        return ConstantModel(_FALLBACK_OUTCOMES), name, None
    return registry.load_artifact(active), name, active.version_id


def _latest_v2_cold_start() -> tuple[Model, str | None, date | None] | None:
    """Newest registered SG-only (v2) model, for Path A cold-start serving.

    Selected by feature-set hash (``v2_field_relative``) rather than a pinned id
    so a future v2 retrain flows through automatically. ``None`` when no v2 model
    is registered → Path A can't cold-start and the caller falls back to stacked.
    """
    v2_hash = v2_field_relative().hash
    registry = get_model_registry()
    name = get_settings().active_model_name
    candidates = [
        v for v in registry.list_versions(name) if v.feature_set_hash == v2_hash
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda v: v.training_data_through)
    return registry.load_artifact(best), best.version_id, best.training_data_through


def get_prediction_service(
    catalog: CatalogService = Depends(get_catalog_service),  # noqa: B008
    provider: DataProvider = Depends(_provider_dep),  # noqa: B008
) -> PredictionService:
    """Assemble the predictions service per the configured serving strategy.

    Path A (default): DataGolf-direct for covered players + the SG-only v2 model
    for cold-start, extracting only the 14 v2 features (no wasted DG-feature
    fetch). Falls back to the stacked v3 path when Path A is disabled or no v2
    cold-start model is registered.
    """
    strategy = get_settings().serving_strategy
    if strategy == "path_a":
        cold = _latest_v2_cold_start()
        if cold is not None:
            cold_model, cold_version, cold_through = cold
            return PredictionService(
                catalog=catalog,
                extractor=FeatureExtractor(provider, feature_set=v2_field_relative()),
                model=cold_model,
                model_name=get_settings().active_model_name,
                model_version_id=f"path_a@{cold_version}",
                model_trained_through=cold_through,
                path_a=PathASource(provider=provider),
            )
        # No v2 model registered → fall through to the stacked path below.

    model, name, version_id = _resolve_active_model()
    active = get_model_registry().get_active(name)
    return PredictionService(
        catalog=catalog,
        extractor=FeatureExtractor(provider, feature_set=_feature_set_for_active_model()),
        model=model,
        model_name=name,
        model_version_id=version_id,
        model_trained_through=active.training_data_through if active else None,
    )


