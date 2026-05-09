from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    analytics,
    catalog,
    cohorts,
    entities,
    health,
    local_data,
    openalex,
    registry,
    reports,
    runs,
    slices,
    sources,
)


app = FastAPI(
    title="OpenAlex DSS API",
    version="0.3.0",
    description="Current API for the OpenAlex scientometric decision support workspace.",
)

logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_v1 = APIRouter(prefix="/api/v1")
for router in (
    health.router,
    openalex.router,
    slices.router,
    catalog.router,
    sources.router,
    local_data.router,
    entities.router,
    cohorts.router,
    analytics.router,
    runs.router,
    registry.router,
    reports.router,
):
    api_v1.include_router(router)

app.include_router(api_v1)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            status_code=exc.status_code,
            title=_http_error_title(exc.status_code),
            detail=exc.detail,
            path=str(request.url.path),
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            status_code=422,
            title="Некорректные параметры запроса",
            detail=issues,
            path=str(request.url.path),
            message=_validation_message(issues),
            action="Проверьте значения полей и повторите действие.",
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            status_code=500,
            title="Внутренняя ошибка сервера",
            detail="Подробности записаны в журнал backend.",
            path=str(request.url.path),
            message="Сервер не смог выполнить действие.",
            action="Обновите данные или повторите действие позже. Если ошибка повторяется, проверьте журнал backend.",
        ),
    )


def _error_payload(
    *,
    status_code: int,
    title: str,
    detail: Any,
    path: str,
    message: str = "",
    action: str = "",
) -> dict[str, Any]:
    resolved_message = message or _detail_message(detail) or _http_error_title(status_code)
    encoded_detail = jsonable_encoder(detail)
    return {
        "detail": encoded_detail,
        "error": {
            "status": status_code,
            "title": title,
            "message": resolved_message,
            "action": action or _http_error_action(status_code),
            "path": path,
        },
    }


def _detail_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return _validation_message(detail)
    if isinstance(detail, dict):
        for key in ("message", "detail", "msg"):
            value = detail.get(key)
            if value:
                return str(value)
    return ""


def _validation_message(issues: list[Any]) -> str:
    for item in issues:
        if isinstance(item, dict):
            field = _validation_field_label(item.get("loc"))
            message = _translate_validation_message(str(item.get("msg") or ""))
            if field and message:
                return f"{field}: {message}"
            if message:
                return message
    return "Параметры запроса не прошли проверку."


def _validation_field_label(loc: Any) -> str:
    if not isinstance(loc, (list, tuple)):
        return ""
    parts = [str(part) for part in loc if str(part) not in {"query", "body", "path"}]
    labels = {
        "limit": "Количество строк",
        "data_limit": "Количество строк в выбранной таблице",
        "offset": "Начальная строка",
        "min_cited_by_count": "Минимум цитирований",
        "from_publication_date": "Дата начала",
        "to_publication_date": "Дата окончания",
        "top_n": "Количество авторов",
        "rank_top_n": "Количество авторов для сравнения",
        "run_id": "Расчет",
        "dump_id": "Срез",
        "kind": "Таблица данных",
        "metric": "Показатель",
        "fraction_mode": "Учет соавторов",
    }
    return labels.get(parts[-1], parts[-1]) if parts else ""


def _translate_validation_message(message: str) -> str:
    text = message.lower()
    if "greater than or equal" in text:
        return "значение меньше допустимого"
    if "input should be greater than or equal" in text:
        return "значение меньше допустимого"
    if "less than or equal" in text:
        return "значение больше допустимого"
    if "input should be less than or equal" in text:
        return "значение больше допустимого"
    if "field required" in text:
        return "обязательное поле не заполнено"
    if "valid integer" in text:
        return "нужно целое число"
    if "valid number" in text:
        return "нужно число"
    return message or "некорректное значение"


def _http_error_title(status_code: int) -> str:
    titles = {
        400: "Некорректное действие",
        401: "Нет доступа",
        403: "Действие запрещено",
        404: "Данные не найдены",
        409: "Конфликт состояния",
        422: "Некорректные параметры запроса",
        429: "Слишком много запросов",
        500: "Внутренняя ошибка сервера",
        502: "Внешний источник недоступен",
        503: "Сервис временно недоступен",
    }
    return titles.get(status_code, "Ошибка API")


def _http_error_action(status_code: int) -> str:
    actions = {
        400: "Проверьте параметры и повторите действие.",
        401: "Проверьте ключ доступа или настройки подключения.",
        403: "Измените настройки или выберите доступное действие.",
        404: "Выберите существующий срез или расчет и повторите действие.",
        409: "Дождитесь завершения текущей операции или обновите состояние.",
        422: "Проверьте значения полей и повторите действие.",
        429: "Подождите и повторите запрос позже.",
        502: "Проверьте доступность внешнего источника или используйте уже скачанный срез.",
        503: "Повторите действие после восстановления сервиса.",
    }
    return actions.get(status_code, "Повторите действие или проверьте журнал backend.")


@app.get("/", tags=["health"])
def root() -> dict[str, str]:
    return {
        "name": "OpenAlex DSS API",
        "version": app.version,
        "api": "/api/v1",
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
def root_health() -> dict[str, str]:
    return {"status": "ok", "api": "/api/v1"}
