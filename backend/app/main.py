"""선착순 쿠폰 발급 API (PRD v3.0 Backend).

ALB → (Frontend Nginx) → Backend EC2 a/b 로 분산되는 무상태 API.
상태는 전부 RDS PostgreSQL 과 ElastiCache 에만 있으므로 인스턴스를 늘려도 그대로 동작한다.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import cache, db
from .config import get_settings
from .metrics import counters
from .routers import events, health, ops, users

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("coupon")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info("starting coupon-api instance=%s", s.instance_id)
    db.init_pool()
    cache.init_client()
    yield
    log.info("shutting down coupon-api")
    cache.close_client()
    db.close_pool()


app = FastAPI(
    title="Coupon Service API",
    version="3.0.0",
    description="선착순 쿠폰 발급 - PostgreSQL 트랜잭션 동기 발급 / Redis 조회 캐시",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_ops_headers(request: Request, call_next):
    """어느 백엔드 인스턴스가 응답했는지, 얼마나 걸렸는지 항상 남긴다.

    백엔드 2대 분산이 실제로 동작하는지 X-Served-By 헤더로 바로 확인할 수 있다.
    """
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Served-By"] = get_settings().instance_id
    response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.1f}"
    if request.url.path.startswith("/api/"):
        log.info(
            "%s %s -> %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """예상 밖 5xx 는 건수를 세고 내부 정보를 노출하지 않는다 (PRD 7.1)."""
    counters.inc("unexpected_5xx")
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(health.router)
app.include_router(events.router)
app.include_router(users.router)
app.include_router(ops.router)


@app.get("/api", tags=["ops"])
def api_root() -> dict:
    return {
        "service": "coupon-api",
        "version": "3.0.0",
        "instance": get_settings().instance_id,
        "endpoints": [
            "GET  /api/events/{event_id}",
            "POST /api/events/{event_id}/issue",
            "GET  /api/users/{user_id}/coupons",
            "GET  /healthz",
            "GET  /readyz",
        ],
    }
