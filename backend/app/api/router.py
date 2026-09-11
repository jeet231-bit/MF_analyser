from fastapi import APIRouter

from app.api import config, diffs, health, models, runs, validation, workbooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(config.router, tags=["config"])
api_router.include_router(workbooks.router, tags=["workbooks"])
api_router.include_router(models.router, tags=["logic model"])
api_router.include_router(runs.router, tags=["engine"])
api_router.include_router(validation.router, tags=["validation"])
api_router.include_router(diffs.router, tags=["versions"])
