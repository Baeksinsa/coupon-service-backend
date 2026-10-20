#!/usr/bin/env bash
# /etc/coupon-api.env 의 키를 설정한다 (있으면 교체, 없으면 추가). Backend-A/B 공통.
# 비밀값은 넣지 않는다: 비밀번호는 DB_PASSWORD_SECRET_ID 로 Secrets Manager 에서 읽는다.
#
#   sudo bash deploy/configure_env.sh KEY=VALUE [KEY=VALUE ...]
#   예) sudo bash deploy/configure_env.sh DB_HOST=xxx.rds.amazonaws.com DB_NAME=coupondb \
#         DB_PASSWORD_SECRET_ID=coupon/prod/app-db DB_PASSWORD_PARAM= \
#         REDIS_URL=rediss://master.xxx.cache.amazonaws.com:6379/0 INSTANCE_ID=backend-a
set -euo pipefail
ENV_FILE=/etc/coupon-api.env
[[ $# -gt 0 ]] || { echo "KEY=VALUE 를 하나 이상 지정하세요" >&2; exit 1; }

cp -p "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
for kv in "$@"; do
  key="${kv%%=*}"
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ && "$kv" == *=* ]] || { echo "잘못된 형식: $kv" >&2; exit 1; }
  if grep -q "^${key}=" "$ENV_FILE"; then
    KV="$kv" KEY="$key" awk 'index($0, ENVIRON["KEY"] "=") == 1 { print ENVIRON["KV"]; next } { print }' \
      "$ENV_FILE" > "$ENV_FILE.tmp"
    cat "$ENV_FILE.tmp" > "$ENV_FILE" && rm -f "$ENV_FILE.tmp"
  else
    printf '%s\n' "$kv" >> "$ENV_FILE"
  fi
done
chmod 600 "$ENV_FILE"; chown root:root "$ENV_FILE"
grep -vE '^(ADMIN_TOKEN|DB_PASSWORD)=' "$ENV_FILE" | grep -vE '^\s*(#|$)'
