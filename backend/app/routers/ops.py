"""테스트 운영용 엔드포인트.

ADMIN_TOKEN 이 설정된 경우에만 열린다. 교육용 PoC 범위이며
상용 수준의 인증이 아니다 (PRD 1.3 제외 범위).
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from .. import cache, repository
from ..config import get_settings
from ..db import get_pool
from ..metrics import counters

router = APIRouter(prefix="/api/ops", tags=["ops"])


def require_admin(x_admin_token: str = Header(default="")) -> None:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(status_code=404, detail="not found")
    if x_admin_token != token:
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/stats", dependencies=[Depends(require_admin)])
def stats(event_id: int = 1) -> dict:
    """201/409/410 건수, 캐시 Hit/Miss, DB 확정 건수를 한 번에 본다 (T2~T4 증거)."""
    s = get_settings()
    event = repository.get_event(event_id)
    return {
        "instance": s.instance_id,
        "cache_enabled": s.cache_enabled,
        "counters": counters.snapshot(),
        "cache": dict(cache.stats),
        "db": {
            "event_id": event_id,
            "remaining_qty": event["remaining_qty"] if event else None,
            "total_qty": event["total_qty"] if event else None,
            "issued_count": repository.count_issues(event_id),
        },
    }


@router.post("/counters/reset", dependencies=[Depends(require_admin)])
def reset_counters() -> dict:
    counters.reset()
    for k in cache.stats:
        cache.stats[k] = 0
    return {"status": "reset"}


class CacheToggle(BaseModel):
    enabled: bool


@router.post("/cache", dependencies=[Depends(require_admin)])
def toggle_cache(body: CacheToggle) -> dict:
    """T4: 재시작 없이 캐시 On/Off 를 바꿔 동일 조건에서 비교한다.

    설정은 프로세스 메모리에 있으므로 이 호출을 받은 프로세스에만 적용된다.
    systemd 유닛이 uvicorn 워커 1개로 도는 이유다. 워커를 늘리려면
    CACHE_ENABLED 환경 변수 + 재시작으로 비교한다.
    """
    s = get_settings()
    s.cache_enabled = body.enabled
    if not body.enabled:
        cache.close_client()
    else:
        cache.init_client()
    return {"cache_enabled": s.cache_enabled}


class ResetEvent(BaseModel):
    event_id: int = 1
    total_qty: int = 100
    name: str | None = None


@router.post("/reset-event", dependencies=[Depends(require_admin)])
def reset_event(body: ResetEvent) -> dict:
    """테스트마다 이벤트/발급 테이블을 초기화한다 (PRD 7.2).

    백엔드 2대 모두의 캐시 키가 같은 Redis 를 가리키므로 한 번만 지우면 된다.
    """
    with get_pool().connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM coupon_issues WHERE event_id = %s", (body.event_id,)
                )
                # name 을 안 넘기면 기존 이벤트 이름을 유지한다
                cur.execute(
                    "INSERT INTO events (id, name, total_qty, remaining_qty) "
                    "VALUES (%(id)s, COALESCE(%(name)s, '선착순 쿠폰 이벤트'), %(qty)s, %(qty)s) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "  name = COALESCE(%(name)s, events.name), "
                    "  total_qty = EXCLUDED.total_qty, "
                    "  remaining_qty = EXCLUDED.remaining_qty",
                    {"id": body.event_id, "name": body.name, "qty": body.total_qty},
                )
    cache.invalidate(body.event_id)
    cache.invalidate_meta(body.event_id)
    counters.reset()
    return {
        "event_id": body.event_id,
        "total_qty": body.total_qty,
        "remaining_qty": body.total_qty,
        "issued_count": repository.count_issues(body.event_id),
    }
