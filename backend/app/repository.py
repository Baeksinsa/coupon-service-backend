"""쿠폰 발급 정합성의 전부가 여기에 있다 (PRD 5.3).

성공 여부는 오직 PostgreSQL COMMIT 으로만 결정한다.
Redis 값으로 발급을 승인하지 않는다.
"""
import logging
from enum import Enum

from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from .db import get_pool

log = logging.getLogger(__name__)


class IssueResult(str, Enum):
    ISSUED = "issued"        # 201
    DUPLICATE = "duplicate"  # 409
    SOLD_OUT = "sold_out"    # 410
    NOT_FOUND = "not_found"  # 404


def get_event(event_id: int) -> dict | None:
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, name, total_qty, remaining_qty FROM events WHERE id = %s",
                (event_id,),
            )
            return cur.fetchone()


def get_remaining(event_id: int) -> int | None:
    """캐시 Miss 시의 원천 조회."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT remaining_qty FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
            return None if row is None else int(row[0])


def issue(event_id: int, user_id: str) -> tuple[IssueResult, dict | None]:
    """단일 트랜잭션 동기 발급.

    1) events 행을 SELECT ... FOR UPDATE 로 잠가 재고 판단을 직렬화한다.
    2) 동일 (event_id, user_id) 발급 이력이 있으면 DUPLICATE.
    3) remaining_qty 가 0 이면 SOLD_OUT.
    4) remaining_qty -1 과 coupon_issues INSERT 를 같은 트랜잭션에서 COMMIT.

    백엔드를 2대로 늘려도 직렬화는 DB 행 잠금이 보장하므로 앱 레벨 락이 필요 없다.
    """
    pool = get_pool()
    with pool.connection() as conn:
        try:
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT id, remaining_qty FROM events WHERE id = %s FOR UPDATE",
                        (event_id,),
                    )
                    event = cur.fetchone()
                    if event is None:
                        return IssueResult.NOT_FOUND, None

                    cur.execute(
                        "SELECT id, issued_at FROM coupon_issues "
                        "WHERE event_id = %s AND user_id = %s",
                        (event_id, user_id),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        return IssueResult.DUPLICATE, {
                            "coupon_id": existing["id"],
                            "issued_at": existing["issued_at"],
                        }

                    if event["remaining_qty"] <= 0:
                        return IssueResult.SOLD_OUT, {"remaining": 0}

                    cur.execute(
                        "UPDATE events SET remaining_qty = remaining_qty - 1 "
                        "WHERE id = %s AND remaining_qty > 0 RETURNING remaining_qty",
                        (event_id,),
                    )
                    updated = cur.fetchone()
                    if updated is None:
                        # FOR UPDATE 로 이미 막히지만 재고 음수 방지의 2차 방어선
                        return IssueResult.SOLD_OUT, {"remaining": 0}

                    cur.execute(
                        "INSERT INTO coupon_issues (event_id, user_id) "
                        "VALUES (%s, %s) RETURNING id, issued_at",
                        (event_id, user_id),
                    )
                    created = cur.fetchone()
                    return IssueResult.ISSUED, {
                        "coupon_id": created["id"],
                        "issued_at": created["issued_at"],
                        "remaining": int(updated["remaining_qty"]),
                    }
        except pg_errors.UniqueViolation:
            # UNIQUE(event_id, user_id) 최종 방어. 여기 도달하면 중복이 확정이다.
            log.info("unique violation -> duplicate event=%s user=%s", event_id, user_id)
            return IssueResult.DUPLICATE, None


def list_user_coupons(user_id: str, limit: int = 100) -> list[dict]:
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT c.id AS coupon_id, c.event_id, e.name AS event_name, c.issued_at "
                "FROM coupon_issues c JOIN events e ON e.id = c.event_id "
                "WHERE c.user_id = %s ORDER BY c.issued_at DESC LIMIT %s",
                (user_id, limit),
            )
            return list(cur.fetchall())


def count_issues(event_id: int) -> int:
    """테스트 판정용: DB에 확정된 발급 건수."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM coupon_issues WHERE event_id = %s", (event_id,)
            )
            return int(cur.fetchone()[0])
