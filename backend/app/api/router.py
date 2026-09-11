from fastapi import APIRouter

from app.api import health, models, workbooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(workbooks.router, tags=["workbooks"])
api_router.include_router(models.router, tags=["logic model"])
