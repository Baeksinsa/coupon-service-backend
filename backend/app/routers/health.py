"""ALB Target Group 헬스 체크용 엔드포인트."""
from fastapi import APIRouter, Response

from .. import cache, db
from ..config import get_settings
from ..schemas import HealthResponse

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """ALB가 매번 호출한다. 프로세스 생존만 확인하고 의존성은 건드리지 않는다."""
    return HealthResponse(status="ok", instance=get_settings().instance_id)


@router.get("/readyz", response_model=HealthResponse)
def readyz(response: Response) -> HealthResponse:
    """배포 직후 수동 확인용. DB/캐시까지 실제로 찔러 본다."""
    s = get_settings()
    db_ok = db.ping()
    cache_ok = cache.ping() if s.cache_enabled else None
    # DB가 없으면 발급이 불가능하므로 503. 캐시는 폴백이 있으므로 degraded 로만 표시.
    if not db_ok:
        response.status_code = 503
    return HealthResponse(
        status="ok" if db_ok else "unavailable",
        instance=s.instance_id,
        db="up" if db_ok else "down",
        cache=("up" if cache_ok else "down") if s.cache_enabled else "disabled",
    )
