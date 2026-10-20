-- 애플리케이션 전용 계정 (DML 만, DDL/소유권 없음). 마스터 계정으로 실행한다.
-- APP_DB_PASSWORD 환경 변수로 비밀번호를 넘긴다 (명령행/파일에 남기지 않음, psql 15+ \getenv).
--   APP_DB_PASSWORD=... psql ... -v app_user=coupon -v db_name=coupondb -f app_user.sql
-- 여러 번 실행해도 안전하다 (계정이 있으면 비밀번호만 갱신).

\getenv app_password APP_DB_PASSWORD

SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

-- CREATE ROLE 기본값이 NOSUPERUSER/NOCREATEDB/NOCREATEROLE 이다 (RDS 는 SUPERUSER 속성 지정 자체를 거부)
ALTER ROLE :"app_user" WITH LOGIN PASSWORD :'app_password';

GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON events, coupon_issues TO :"app_user";
GRANT USAGE, SELECT ON SEQUENCE coupon_issues_id_seq TO :"app_user";
