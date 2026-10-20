"""환경 변수 기반 설정. 비밀값은 SSM Parameter Store(SecureString)에서 읽을 수 있다."""
import os
import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- PostgreSQL (RDS) ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "coupon"
    db_user: str = "coupon"
    db_password: str = ""
    # 값이 있으면 db_password 대신 SSM SecureString 파라미터에서 조회한다.
    db_password_param: str = ""
    db_sslmode: str = "prefer"  # RDS 운영 시 require 권장
    db_pool_min: int = 2
    db_pool_max: int = 10

    # --- ElastiCache (Valkey/Redis) ---
    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 4  # PRD 5.4: 3~5초
    redis_timeout_seconds: float = 0.2  # 캐시 장애가 API를 끌고 가지 않도록 짧게

    # --- 운영 ---
    aws_region: str = "ap-northeast-2"
    instance_id: str = ""  # 비우면 hostname 사용. 2대 분산 확인용 응답 헤더에 실림
    # 값이 설정된 경우에만 /api/ops/* 운영 엔드포인트가 열린다 (빈 값이면 비활성).
    admin_token: str = ""
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_settings: Settings | None = None


def _resolve_db_password(s: Settings) -> str:
    """SSM SecureString 우선, 없으면 환경 변수 값."""
    if not s.db_password_param:
        return s.db_password
    import boto3  # 지연 import: 로컬/테스트에서 AWS 호출을 강제하지 않는다

    ssm = boto3.client("ssm", region_name=s.aws_region)
    resp = ssm.get_parameter(Name=s.db_password_param, WithDecryption=True)
    return resp["Parameter"]["Value"]


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        s = Settings()
        s.db_password = _resolve_db_password(s)
        if not s.instance_id:
            s.instance_id = os.environ.get("HOSTNAME") or socket.gethostname()
        _settings = s
    return _settings
