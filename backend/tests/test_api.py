"""DB/Redis 없이 도는 API 계약 테스트 (CI 필수 통과 대상)."""
import pytest
from fastapi.testclient import TestClient

from app import cache, repository
from app.main import app
from app.repository import IssueResult

client = TestClient(app)  # lifespan 미실행 → 실제 DB 연결 없음


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    monkeypatch.setattr(cache, "get_remaining", lambda event_id: None)
    monkeypatch.setattr(cache, "set_remaining", lambda event_id, value: None)
    monkeypatch.setattr(cache, "invalidate", lambda event_id: None)
    monkeypatch.setattr(cache, "get_meta", lambda event_id: None)
    monkeypatch.setattr(cache, "set_meta", lambda event_id, name, total_qty: None)


def test_healthz_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["X-Served-By"]  # 어느 인스턴스가 응답했는지 항상 식별 가능


def test_get_stock_from_db(monkeypatch):
    monkeypatch.setattr(
        repository,
        "get_event",
        lambda event_id: {
            "id": event_id,
            "name": "테스트",
            "total_qty": 100,
            "remaining_qty": 7,
        },
    )
    r = client.get("/api/events/1")
    assert r.status_code == 200
    body = r.json()
    assert body["remaining"] == 7
    assert body["source"] == "db"


def test_get_stock_from_cache(monkeypatch):
    monkeypatch.setattr(cache, "get_remaining", lambda event_id: 42)
    monkeypatch.setattr(
        cache, "get_meta", lambda event_id: {"name": "테스트", "total_qty": 100}
    )

    def db_must_not_be_called(event_id):
        raise AssertionError("cache hit 인데 DB 를 조회했다")

    monkeypatch.setattr(repository, "get_event", db_must_not_be_called)
    r = client.get("/api/events/1")
    assert r.status_code == 200
    assert r.json() == {
        "event_id": 1,
        "name": "테스트",
        "total_qty": 100,
        "remaining": 42,
        "source": "cache",
    }


def test_get_stock_unknown_event(monkeypatch):
    monkeypatch.setattr(repository, "get_event", lambda event_id: None)
    assert client.get("/api/events/999").status_code == 404


@pytest.mark.parametrize(
    "result,expected_status,expected_state",
    [
        (IssueResult.ISSUED, 201, "issued"),
        (IssueResult.DUPLICATE, 409, "duplicate"),
        (IssueResult.SOLD_OUT, 410, "sold_out"),
    ],
)
def test_issue_status_mapping(monkeypatch, result, expected_status, expected_state):
    """PRD 5.1: 201 발급 / 409 중복 / 410 마감."""
    monkeypatch.setattr(
        repository,
        "issue",
        lambda event_id, user_id: (result, {"coupon_id": 1, "remaining": 99}),
    )
    r = client.post("/api/events/1/issue", json={"userId": "user-001"})
    assert r.status_code == expected_status
    assert r.json()["status"] == expected_state


def test_issue_invalidates_cache_only_after_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(cache, "invalidate", lambda event_id: calls.append(event_id))
    monkeypatch.setattr(
        repository, "issue", lambda e, u: (IssueResult.SOLD_OUT, {"remaining": 0})
    )
    client.post("/api/events/1/issue", json={"userId": "user-001"})
    assert calls == []  # 발급 실패 시 캐시를 건드리지 않는다

    monkeypatch.setattr(
        repository, "issue", lambda e, u: (IssueResult.ISSUED, {"coupon_id": 1})
    )
    client.post("/api/events/1/issue", json={"userId": "user-001"})
    assert calls == [1]


def test_issue_rejects_bad_user_id():
    for bad in ["", "a" * 65, "user 001", "'; DROP TABLE events;--"]:
        r = client.post("/api/events/1/issue", json={"userId": bad})
        assert r.status_code == 422, bad


def test_user_coupons(monkeypatch):
    monkeypatch.setattr(
        repository,
        "list_user_coupons",
        lambda user_id, limit=100: [
            {
                "coupon_id": 1,
                "event_id": 1,
                "event_name": "테스트",
                "issued_at": "2026-10-20T10:00:00+09:00",
            }
        ],
    )
    r = client.get("/api/users/user-001/coupons")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_ops_requires_token():
    assert client.get("/api/ops/stats").status_code == 403


def test_db_unavailable_returns_503(monkeypatch):
    from psycopg_pool import PoolTimeout

    def boom(event_id):
        raise PoolTimeout("couldn't get a connection")

    monkeypatch.setattr(repository, "get_event", boom)
    r = client.get("/api/events/1")
    assert r.status_code == 503
    assert r.json() == {"detail": "database unavailable"}


def test_settings_survive_missing_secret(monkeypatch):
    """SSM 비밀값이 없어도 프로세스는 떠야 한다 (ALB 헬스체크 유지)."""
    from app import config

    def no_param(s):
        raise RuntimeError("ParameterNotFound")

    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "_resolve_db_password", no_param)
    s = config.get_settings()
    assert s.db_password == ""
    monkeypatch.setattr(config, "_settings", None)
