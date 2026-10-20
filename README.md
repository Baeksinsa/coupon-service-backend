# coupon-service-backend

선착순 쿠폰 발급 서비스 Backend API — PRD v3.0 (4일 교육용 PoC)

인프라(Terraform)는 별도 레포 `coupon-service-project` 에서 관리한다.

```
User → Route 53 → ALB ─┬─ /*      → Frontend EC2 (Nginx, 정적 UI)
                       └─ /api/*  → Backend EC2 a / b (FastAPI :8000)
                                        ├─ ElastiCache Valkey (재고 조회 캐시)
                                        └─ RDS PostgreSQL (발급 원장, 진실의 원천)
```

## 디렉터리

| 경로 | 내용 |
|---|---|
| `backend/app/` | FastAPI 앱. 발급 트랜잭션은 `repository.py` 에 전부 있다 |
| `backend/sql/` | `schema.sql` / `seed.sql` / `reset.sql` / `verify.sql` |
| `backend/tests/` | API 계약 테스트 + 실제 DB 동시성 테스트 |
| `deploy/` | systemd 유닛, EC2 설치 스크립트, DB 초기화, IAM 정책, Nginx 프록시 설정 |
| `scripts/verify_e2e.py` | T1~T4 HTTP 검증 (ALB 주소에 바로 실행) |
| `loadtest/` | k6 T2 / T3 / T4 |

## API

| 메서드 · 경로 | 설명 | 응답 |
|---|---|---|
| `GET /api/events/{id}` | 잔여 재고 (Redis 우선, Miss 시 DB) | 200 · 404 |
| `POST /api/events/{id}/issue` `{"userId":"..."}` | 동기 발급 | **201** 발급 · **409** 중복 · **410** 마감 |
| `GET /api/users/{userId}/coupons` | DB 에 확정된 쿠폰 | 200 |
| `GET /healthz` | 프로세스 생존 (ALB 헬스체크용, 의존성 미확인) | 200 |
| `GET /readyz` | DB / Redis 실제 연결 확인 (배포 직후 수동 확인) | 200 · 503 |
| `/api/ops/*` | 테스트용 초기화·통계·캐시 토글. `ADMIN_TOKEN` 설정 시에만 열림 | |

모든 응답에 `X-Served-By: backend-a|backend-b` 헤더가 붙는다. 분산이 실제로 되는지 바로 확인할 수 있다.

`userId` 는 `[A-Za-z0-9_.:@-]` 1~64자. 실습용 가상 값이다.

## 정합성이 어떻게 보장되나

1. 요청마다 트랜잭션 시작 → `SELECT ... FROM events WHERE id=? FOR UPDATE` 로 이벤트 행 잠금
2. 같은 `(event_id, user_id)` 가 있으면 409
3. `remaining_qty = 0` 이면 410
4. `remaining_qty - 1` + `coupon_issues INSERT` 를 한 트랜잭션으로 COMMIT → 201
5. 2차 방어: `UNIQUE(event_id, user_id)`, `CHECK (remaining_qty >= 0)`

**백엔드가 2대여도 직렬화는 DB 행 잠금이 하므로** 앱 레벨 락이나 sticky session 이 필요 없다.
Redis 는 조회 캐시일 뿐 발급 판단에 쓰지 않으며, Redis 가 죽어도 조회는 DB 로 폴백하고 발급은 영향이 없다.

## 로컬 실행

```bash
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/pytest            # DB 없이 도는 테스트

# PostgreSQL 이 있으면 동시성 테스트까지
RUN_DB_TESTS=1 DB_HOST=127.0.0.1 DB_USER=coupon DB_PASSWORD=... DB_SSLMODE=disable .venv/bin/pytest -v

# 서버
DB_HOST=... DB_PASSWORD=... REDIS_URL=redis://127.0.0.1:6379/0 \
  .venv/bin/uvicorn app.main:app --port 8000
# 문서: http://localhost:8000/docs
```

## AWS 배포 (Backend EC2 a / b)

### 0. 콘솔에서 미리 준비 (A 담당)
- RDS 생성 시 **초기 데이터베이스 이름 `coupon`** 지정 (안 하면 DB 를 수동 생성해야 함)
- DB 암호를 SSM Parameter Store SecureString `/coupon/prod/db_password` 로 저장
- Backend 인스턴스 프로파일: `AmazonSSMManagedInstanceCore` + `deploy/iam-backend-policy.json` (ACCOUNT_ID 치환)
- 보안 그룹: `sg-db 5432 ← sg-api`, `sg-cache 6379 ← sg-api`, `sg-api 8000 ← sg-alb`
- ElastiCache 전송 중 암호화(TLS)를 켰다면 `REDIS_URL` 을 `rediss://` 로

### 1. 설치 (SSM Session Manager 로 각 Backend 접속)
```bash
sudo dnf install -y git
git clone <repo-url> ~/coupon-service && cd ~/coupon-service

sudo bash deploy/bootstrap_backend.sh ~/coupon-service backend-a   # 첫 실행: /etc/coupon-api.env 생성 후 종료
sudo vi /etc/coupon-api.env                                         # DB_HOST, REDIS_URL 채우기
sudo bash deploy/bootstrap_backend.sh ~/coupon-service backend-a   # 재실행 → 기동 + readyz 출력
```
Backend b 에서는 `backend-b` 로 같은 과정을 반복한다.

### 2. DB 스키마 (한 대에서만 1회)
```bash
sudo bash deploy/init_db.sh
```

### 3. ALB 연결
| 규칙 | Target Group | 헬스체크 |
|---|---|---|
| `/api/*` (우선순위 1) | `tg-coupon-api` — Backend a, b `:8000` | `GET /healthz` → 200 |
| 기본 `/*` | `tg-coupon-web` — Frontend `:80` | `GET /` → 200 |

```bash
curl -i http://<ALB-DNS>/api/events/1          # X-Served-By 가 a/b 번갈아 나오는지 확인
```

### API 경로 구성: ALB 직접 vs Frontend Nginx 경유

Backend 코드는 두 방식 모두 그대로 동작한다. **ALB 직접(위 표)을 권장한다.**

| | ALB `/api/*` → tg-coupon-api (권장, PRD 2.1) | ALB → Frontend Nginx → Backend a/b |
|---|---|---|
| 헬스체크 | ALB 능동 헬스체크, 콘솔에서 Healthy/Unhealthy 확인 | Nginx OSS 는 수동(실패 감지)만 |
| DoD "각 Target Group Healthy" / T5 증거 | 그대로 충족 | API TG 가 없어 별도 증거 필요 |
| CloudWatch 지표 | 백엔드별 요청 수·5xx·응답 시간 | Nginx 로그에서 직접 집계 |
| 장애 지점 | Frontend 가 죽어도 API 는 동작 | Frontend 1대가 API 경로의 단일 장애점 |
| 보안 그룹 | `sg-api 8000 ← sg-alb` | `sg-api 8000 ← sg-web` |

Nginx 경유를 택하면 `deploy/nginx-frontend-api-proxy.conf` 를 사용한다.

## 테스트 (PRD 7.2)

테스트 전 서버에 `ADMIN_TOKEN` 을 설정하고 재시작한다. 끝나면 비우고 다시 재시작한다.

```bash
# T1~T4 한 번에 (ALB 경유)
python scripts/verify_e2e.py --base http://<ALB-DNS> --admin-token $ADMIN_TOKEN

# k6 — 매 실행 전 초기화
curl -X POST http://<ALB-DNS>/api/ops/reset-event \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H 'content-type: application/json' \
  -d '{"event_id":1,"total_qty":100}'
k6 run -e BASE=http://<ALB-DNS> loadtest/t3_soldout.js

# DB 최종 증거 (Backend 에서)
psql ... -v event_id=1 -f backend/sql/verify.sql
```

- **T4 캐시 On/Off**: `/api/ops/cache` 는 요청을 받은 프로세스에만 적용된다. ALB 뒤에서는 Backend a, b 각각에
  (SSM 접속 후 `curl localhost:8000/api/ops/cache ...`) 보내거나 `CACHE_ENABLED=false` + 재시작으로 비교한다.
  같은 VPC 안에서는 DB 단건 조회도 수 ms 라 지연 차이는 작을 수 있다. **DB 조회 횟수 감소**
  (`/api/ops/stats` 의 `cache.hit/miss`, RDS `ReadIOPS`) 를 함께 기록한다.
- **T5 장애**: `sudo systemctl stop coupon-api` → TG Unhealthy 까지 시간 기록 → `start` → Healthy 복귀 시간 기록.
  한 대만 멈추면 나머지 한 대가 계속 응답하는 것도 확인할 수 있다.
- `/api/ops/stats` 의 카운터는 인스턴스별 값이다. 전체 합계는 DB `COUNT` 와 ALB 지표를 기준으로 한다.

## 운영 메모

- 로그: `journalctl -u coupon-api -f` (요청마다 `METHOD path -> status 시간ms`)
- 재시작: `sudo systemctl restart coupon-api`
- 코드 갱신: `git pull` 후 `sudo bash deploy/bootstrap_backend.sh ~/coupon-service backend-a`
- uvicorn 워커는 1개 고정 (캐시 토글이 프로세스 메모리에 있음). 처리량은 인스턴스 수로 늘린다.
