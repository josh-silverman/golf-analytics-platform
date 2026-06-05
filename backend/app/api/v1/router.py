from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.betting import router as betting_router
from app.api.v1.health import router as health_router
from app.api.v1.meta import router as meta_router
from app.api.v1.players import router as players_router
from app.api.v1.predictions import router as predictions_router
from app.api.v1.simulations import router as simulations_router
from app.api.v1.tournaments import router as tournaments_router

router = APIRouter()
router.include_router(health_router)
router.include_router(meta_router)
router.include_router(players_router)
router.include_router(tournaments_router)
router.include_router(predictions_router)
router.include_router(simulations_router)
router.include_router(analytics_router)
router.include_router(betting_router)
