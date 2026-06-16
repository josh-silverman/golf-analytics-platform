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
from app.ml.base import ConstantModel
from app.ml.registry import ModelRegistry
from app.providers.factory import get_data_provider
from app.services.catalog import CatalogService
from app.services.features import FeatureExtractor
from app.services.predictions import PredictionService

if TYPE_CHECKING:
    from app.ml.base import Model
    from app.providers.base import DataProvider


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
    return FeatureExtractor(provider)


@lru_cache(maxsize=1)
def get_model_registry() -> ModelRegistry:
    """Process-cached registry rooted at the configured directory."""
    return ModelRegistry(Path(get_settings().model_registry_path))


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


def get_prediction_service(
    catalog: CatalogService = Depends(get_catalog_service),  # noqa: B008
    extractor: FeatureExtractor = Depends(get_feature_extractor),  # noqa: B008
) -> PredictionService:
    model, name, version_id = _resolve_active_model()
    return PredictionService(
        catalog=catalog,
        extractor=extractor,
        model=model,
        model_name=name,
        model_version_id=version_id,
    )


