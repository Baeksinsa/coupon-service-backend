"""ElastiCache(Valkey/Redis) 조회 캐시.

PRD 5.4 원칙:
  - 재고 조회만 캐시한다. 발급 승인 판단에는 절대 쓰지 않는다.
  - Redis가 죽어도 GET은 PostgreSQL로 폴백해 기능을 유지한다.
"""
import json
import logging

import redis

from .config import get_settings

log = logging.getLogger(__name__)

_client: redis.Redis | None = None

# 캐시 Hit/Miss 집계 (T4 증거용, 인스턴스 로컬 카운터)
stats = {"hit": 0, "miss": 0, "error": 0, "invalidate": 0}


# 이벤트 이름/총수량은 거의 바뀌지 않으므로 재고보다 길게 캐시한다
META_TTL_SECONDS = 300


def remaining_key(event_id: int) -> str:
    return f"coupon:{event_id}:remaining"


def meta_key(event_id: int) -> str:
    return f"coupon:{event_id}:meta"


def init_client() -> redis.Redis | None:
    """캐시가 꺼져 있으면 None. 연결 실패해도 예외를 올리지 않는다."""
    global _client
    s = get_settings()
    if not s.cache_enabled:
        _client = None
        return None
    if _client is None:
        _client = redis.Redis.from_url(
            s.redis_url,
            decode_responses=True,
            socket_connect_timeout=s.redis_timeout_seconds,
            socket_timeout=s.redis_timeout_seconds,
            retry_on_timeout=False,
            health_check_interval=30,
        )
        log.info("redis client created url=%s", s.redis_url.split("@")[-1])
    return _client


def get_client() -> redis.Redis | None:
    s = get_settings()
    if not s.cache_enabled:
        return None
    return _client or init_client()


def close_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        finally:
            _client = None


def get_remaining(event_id: int) -> int | None:
    """캐시 Hit면 재고 값, Miss/장애면 None."""
    c = get_client()
    if c is None:
        stats["miss"] += 1
        return None
    try:
        raw = c.get(remaining_key(event_id))
    except Exception as exc:  # noqa: BLE001 - 캐시 장애는 Miss로 처리하고 DB로 폴백
        stats["error"] += 1
        log.warning("redis get failed: %s", exc)
        return None
    if raw is None:
        stats["miss"] += 1
        return None
    stats["hit"] += 1
    try:
        return int(raw)
    except ValueError:
        return None


def set_remaining(event_id: int, value: int) -> None:
    c = get_client()
    if c is None:
        return
    s = get_settings()
    try:
        c.set(remaining_key(event_id), value, ex=s.cache_ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        stats["error"] += 1
        log.warning("redis set failed: %s", exc)


def get_meta(event_id: int) -> dict | None:
    c = get_client()
    if c is None:
        return None
    try:
        raw = c.get(meta_key(event_id))
    except Exception as exc:  # noqa: BLE001
        stats["error"] += 1
        log.warning("redis get meta failed: %s", exc)
        return None
    return json.loads(raw) if raw else None


def set_meta(event_id: int, name: str, total_qty: int) -> None:
    c = get_client()
    if c is None:
        return
    try:
        c.set(
            meta_key(event_id),
            json.dumps({"name": name, "total_qty": total_qty}, ensure_ascii=False),
            ex=META_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        stats["error"] += 1
        log.warning("redis set meta failed: %s", exc)


def invalidate_meta(event_id: int) -> None:
    """이벤트 정의가 바뀔 때(reset-event)만 호출한다."""
    c = get_client()
    if c is None:
        return
    try:
        c.delete(meta_key(event_id))
    except Exception as exc:  # noqa: BLE001
        stats["error"] += 1
        log.warning("redis delete meta failed: %s", exc)


def invalidate(event_id: int) -> None:
    """발급 성공 직후 호출. 다음 조회가 새 값을 읽도록 유도한다."""
    c = get_client()
    if c is None:
        return
    try:
        c.delete(remaining_key(event_id))
        stats["invalidate"] += 1
    except Exception as exc:  # noqa: BLE001
        stats["error"] += 1
        log.warning("redis delete failed: %s", exc)


def ping() -> bool:
    c = get_client()
    if c is None:
        return False
    try:
        return bool(c.ping())
    except Exception:  # noqa: BLE001
        return False
