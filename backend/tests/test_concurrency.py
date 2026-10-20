"""실제 PostgreSQL 에 붙는 동시성 테스트 (T2/T3 의 축소판).

로컬/CI 에서 DB 가 있을 때만 돈다:
    RUN_DB_TESTS=1 DB_HOST=... DB_NAME=... DB_USER=... DB_PASSWORD=... pytest
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="RUN_DB_TESTS=1 이고 PostgreSQL 이 있을 때만 실행",
)


@pytest.fixture(scope="module")
def db():
    from app import db as db_module

    pool = db_module.init_pool()
    schema = (
        os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql")
    )
    with open(schema, encoding="utf-8") as f:
        ddl = f.read()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    yield db_module
    db_module.close_pool()


def reset_event(db, event_id: int, qty: int) -> None:
    with db.get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coupon_issues WHERE event_id = %s", (event_id,))
            cur.execute(
                "INSERT INTO events (id, name, total_qty, remaining_qty) "
                "VALUES (%s, 'T', %s, %s) ON CONFLICT (id) DO UPDATE SET "
                "total_qty = EXCLUDED.total_qty, remaining_qty = EXCLUDED.remaining_qty",
                (event_id, qty, qty),
            )
        conn.commit()


def test_duplicate_same_user_concurrent(db):
    """T2: 동일 userId 로 동시 100회 → 201 1건, 409 99건, DB 1건."""
    from app import repository

    event_id, user = 101, "dup-user"
    reset_event(db, event_id, 100)

    with ThreadPoolExecutor(max_workers=32) as ex:
        results = [r for r, _ in ex.map(lambda _: repository.issue(event_id, user), range(100))]

    assert results.count(repository.IssueResult.ISSUED) == 1
    assert results.count(repository.IssueResult.DUPLICATE) == 99
    assert repository.count_issues(event_id) == 1
    assert repository.get_remaining(event_id) == 99


def test_sold_out_exactly_at_stock(db):
    """T3 축소판: 재고 20 + 서로 다른 사용자 100명 → 201 20건, 410 80건, 재고 0."""
    from app import repository

    event_id, stock, users = 102, 20, 100
    reset_event(db, event_id, stock)

    with ThreadPoolExecutor(max_workers=32) as ex:
        results = [
            r
            for r, _ in ex.map(
                lambda i: repository.issue(event_id, f"user-{i:04d}"), range(users)
            )
        ]

    assert results.count(repository.IssueResult.ISSUED) == stock
    assert results.count(repository.IssueResult.SOLD_OUT) == users - stock
    assert repository.count_issues(event_id) == stock
    assert repository.get_remaining(event_id) == 0  # 초과 발급도 음수 재고도 없다


def test_unknown_event_returns_not_found(db):
    from app import repository

    result, _ = repository.issue(999999, "nobody")
    assert result is repository.IssueResult.NOT_FOUND
