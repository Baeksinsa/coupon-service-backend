#!/usr/bin/env bash
# Backend EC2 (Amazon Linux 2023) 설치 스크립트. SSM Session Manager 에서 root 로 실행한다.
#
#   sudo bash deploy/bootstrap_backend.sh <레포 경로> <backend-a|backend-b>
#
# 사전 조건: NAT 경유 외부 통신 가능 (dnf/pip), 인스턴스 프로파일에 iam-backend-policy.json 연결
set -euo pipefail

SRC_DIR="$(realpath "${1:?레포 경로를 지정하세요 (예: /home/ssm-user/coupon-service)}")"
INSTANCE_NAME="${2:?인스턴스 이름을 지정하세요 (backend-a 또는 backend-b)}"
APP_DIR=/opt/coupon-api
ENV_FILE=/etc/coupon-api.env

echo "[1/6] 패키지 설치 (python3.11, psql 클라이언트)"
dnf install -y -q python3.11 python3.11-pip postgresql16 rsync

echo "[2/6] 서비스 계정"
id coupon >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /sbin/nologin coupon

echo "[3/6] 코드 배치 -> $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  "$SRC_DIR"/backend "$SRC_DIR"/scripts "$APP_DIR"/

echo "[4/6] 가상환경 및 의존성"
python3.11 -m venv "$APP_DIR/backend/.venv"
"$APP_DIR/backend/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/backend/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"
chown -R coupon:coupon "$APP_DIR"

echo "[5/6] 환경 파일 $ENV_FILE"
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 600 -o root -g root "$SRC_DIR/deploy/coupon-api.env.example" "$ENV_FILE"
  sed -i "s/^INSTANCE_ID=.*/INSTANCE_ID=${INSTANCE_NAME}/" "$ENV_FILE"
  echo "  !! $ENV_FILE 를 새로 만들었습니다. DB_HOST / REDIS_URL 을 채운 뒤 다시 실행하세요."
  exit 2
fi

echo "[6/6] systemd 등록 및 기동"
install -m 644 "$SRC_DIR/deploy/coupon-api.service" /etc/systemd/system/coupon-api.service
systemctl daemon-reload
systemctl enable --now coupon-api
systemctl restart coupon-api

for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
echo "--- healthz ---"; curl -sS http://127.0.0.1:8000/healthz; echo
echo "--- readyz (DB/Redis 연결) ---"; curl -sS http://127.0.0.1:8000/readyz; echo
echo "로그: journalctl -u coupon-api -f"
