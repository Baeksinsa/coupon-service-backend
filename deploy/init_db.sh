#!/usr/bin/env bash
# RDS 에 스키마/시드/앱 전용 계정을 준비한다. Backend EC2 에서 실행 (sg-db 가 sg-api 만 허용하므로).
# 기존 데이터는 지우지 않는다: 스키마는 IF NOT EXISTS, 시드는 events 가 비어 있을 때만 넣는다.
#
#   sudo bash deploy/init_db.sh <RDS 마스터 시크릿 ARN 또는 이름>
#
# 마스터 계정은 이 스크립트에서만 쓰고, 앱은 DB_USER / DB_PASSWORD_SECRET_ID 로 접속한다.
set -euo pipefail
ADMIN_SECRET_ID="${1:?RDS 마스터 시크릿 ARN 또는 이름을 지정하세요 (rds!db-...)}"
ENV_FILE=/etc/coupon-api.env
SQL_DIR="$(dirname "$(realpath "$0")")/../backend/sql"

set -a; source "$ENV_FILE"; set +a
: "${DB_PASSWORD_SECRET_ID:?$ENV_FILE 에 DB_PASSWORD_SECRET_ID 가 필요합니다}"

get_secret() {
  aws secretsmanager get-secret-value --region "$AWS_REGION" --secret-id "$1" \
    --query SecretString --output text
}
# JSON 시크릿이면 해당 키, 아니면 원문 (app/config.py 와 같은 규칙)
secret_field() {
  python3 -c 'import json,sys
raw=sys.stdin.read().rstrip("\n")
try: d=json.loads(raw)
except ValueError: d=None
print(d.get(sys.argv[1], "") if isinstance(d, dict) else (raw if sys.argv[1]=="password" else ""))' "$1"
}

ADMIN_JSON="$(get_secret "$ADMIN_SECRET_ID")"
ADMIN_USER="$(secret_field username <<<"$ADMIN_JSON")"
PGPASSWORD="$(secret_field password <<<"$ADMIN_JSON")"
APP_DB_PASSWORD="$(get_secret "$DB_PASSWORD_SECRET_ID" | secret_field password)"
unset ADMIN_JSON
export PGPASSWORD APP_DB_PASSWORD PGSSLMODE="${DB_SSLMODE:-require}"

PSQL=(psql -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$ADMIN_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -X)

echo "--- 기존 테이블"
"${PSQL[@]}" -c "\dt public.*"

"${PSQL[@]}" -f "$SQL_DIR/schema.sql"
if [[ "$("${PSQL[@]}" -tAc 'SELECT count(*) FROM events')" == "0" ]]; then
  "${PSQL[@]}" -f "$SQL_DIR/seed.sql"
else
  echo "events 에 데이터가 있어 seed.sql 을 건너뜁니다 (재고 덮어쓰기 방지)"
fi
"${PSQL[@]}" -v app_user="$DB_USER" -v db_name="$DB_NAME" -f "$SQL_DIR/app_user.sql"

"${PSQL[@]}" -c "SELECT id, name, total_qty, remaining_qty FROM events;" \
  -c "SELECT event_id, count(*) AS issued FROM coupon_issues GROUP BY event_id;"

echo "--- 앱 계정($DB_USER) 접속 확인"
PGPASSWORD="$APP_DB_PASSWORD" psql -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" \
  -X -tAc "SELECT current_user, count(*) FROM events"
