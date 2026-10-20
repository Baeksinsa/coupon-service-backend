#!/usr/bin/env bash
# RDS 에 스키마와 시드 데이터를 넣는다. Backend EC2 에서 실행 (sg-db 가 sg-api 만 허용하므로).
#
#   sudo bash deploy/init_db.sh
set -euo pipefail
ENV_FILE=/etc/coupon-api.env
SQL_DIR="$(dirname "$(realpath "$0")")/../backend/sql"

set -a; source "$ENV_FILE"; set +a
if [[ -n "${DB_PASSWORD_PARAM:-}" ]]; then
  PGPASSWORD="$(aws ssm get-parameter --region "$AWS_REGION" --name "$DB_PASSWORD_PARAM" \
    --with-decryption --query Parameter.Value --output text)"
else
  PGPASSWORD="${DB_PASSWORD:?DB_PASSWORD 또는 DB_PASSWORD_PARAM 필요}"
fi
export PGPASSWORD PGSSLMODE="${DB_SSLMODE:-require}"

PSQL=(psql -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1)
"${PSQL[@]}" -f "$SQL_DIR/schema.sql"
"${PSQL[@]}" -f "$SQL_DIR/seed.sql"
"${PSQL[@]}" -c "SELECT id, name, total_qty, remaining_qty FROM events;"
