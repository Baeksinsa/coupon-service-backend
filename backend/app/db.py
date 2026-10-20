"""PostgreSQL 커넥션 풀. 발급 트랜잭션의 진실의 원천(PRD 5.3)."""
import logging

from psycopg_pool import ConnectionPool

from .config import get_settings

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def _conninfo() -> str:
    s = get_settings()
    return (
        f"host={s.db_host} port={s.db_port} dbname={s.db_name} "
        f"user={s.db_user} password={s.db_password} sslmode={s.db_sslmode} "
        f"connect_timeout=5 application_name=coupon-api"
    )


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(
            conninfo=_conninfo(),
            min_size=s.db_pool_min,
            max_size=s.db_pool_max,
            open=True,
            timeout=5.0,
            kwargs={"autocommit": False},
        )
        log.info("db pool ready host=%s db=%s", s.db_host, s.db_name)
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        return init_pool()
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def ping() -> bool:
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as exc:  # noqa: BLE001 - 헬스체크는 모든 예외를 실패로 본다
        log.warning("db ping failed: %s", exc)
        return False
