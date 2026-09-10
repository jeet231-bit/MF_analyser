from fastapi import APIRouter

from app.api import health, workbooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(workbooks.router, tags=["workbooks"])
