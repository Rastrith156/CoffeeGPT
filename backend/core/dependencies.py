from __future__ import annotations

from fastapi import Request

from core.runtime import ApplicationContainer, build_container


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = build_container()
        request.app.state.container = container
    return container


def get_health_service(request: Request):
    return get_container(request).health_service


def get_market_service(request: Request):
    return get_container(request).market_service


def get_weather_service(request: Request):
    return get_container(request).weather_service


def get_news_service(request: Request):
    return get_container(request).news_service


def get_forecast_service(request: Request):
    return get_container(request).forecast_service


def get_orchestrator(request: Request):
    return get_container(request).orchestrator


def get_ingestion_pipeline(request: Request):
    return get_container(request).ingestion_pipeline
