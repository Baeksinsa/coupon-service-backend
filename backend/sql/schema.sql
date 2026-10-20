-- PRD 5.2 DB 스키마
-- psql "host=<rds-endpoint> port=5432 dbname=coupon user=coupon" -f schema.sql

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER      PRIMARY KEY,   -- 실습용으로 ID를 직접 지정한다 (event 1번)
    name          TEXT         NOT NULL,
    total_qty     INTEGER      NOT NULL CHECK (total_qty >= 0),
    remaining_qty INTEGER      NOT NULL CHECK (remaining_qty >= 0),  -- 초과 발급 최종 방어
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coupon_issues (
    id         BIGSERIAL    PRIMARY KEY,
    event_id   INTEGER      NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id    VARCHAR(64)  NOT NULL,
    issued_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_coupon_issues_event_user UNIQUE (event_id, user_id)  -- 중복 발급 차단
);

-- 사용자별 발급 내역 조회 경로
CREATE INDEX IF NOT EXISTS idx_coupon_issues_user ON coupon_issues (user_id, issued_at DESC);
