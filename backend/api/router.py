from __future__ import annotations

from fastapi import APIRouter

from api import chat, forecast, health, ingestion, market, news, weather

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(chat.router, tags=["AI Chatbot"])
api_router.include_router(market.router, tags=["Market Intelligence"])
api_router.include_router(weather.router, tags=["Weather Intelligence"])
api_router.include_router(news.router, tags=["News Intelligence"])
api_router.include_router(forecast.router, tags=["Forecast Engine"])
api_router.include_router(ingestion.router, tags=["Data Ingestion"])
