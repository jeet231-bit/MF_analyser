from fastapi import APIRouter

from app.api import (
    auth,
    config,
    diffs,
    exports,
    health,
    models,
    research,
    runs,
    validation,
    views,
    workbooks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(config.router, tags=["config"])
api_router.include_router(workbooks.router, tags=["workbooks"])
api_router.include_router(models.router, tags=["logic model"])
api_router.include_router(runs.router, tags=["engine"])
api_router.include_router(validation.router, tags=["validation"])
api_router.include_router(diffs.router, tags=["versions"])
api_router.include_router(views.router, tags=["dashboard views"])
api_router.include_router(exports.router, tags=["exports"])
api_router.include_router(research.router, tags=["research"])
