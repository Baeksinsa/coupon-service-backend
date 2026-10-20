"""사용자별 발급 내역 조회 (DB에 확정된 값만)."""
from fastapi import APIRouter, Path

from .. import repository
from ..schemas import CouponItem, UserCouponsResponse

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/{user_id}/coupons", response_model=UserCouponsResponse)
def list_coupons(
    user_id: str = Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:@-]+$"),
) -> UserCouponsResponse:
    rows = repository.list_user_coupons(user_id)
    return UserCouponsResponse(
        userId=user_id,
        count=len(rows),
        coupons=[CouponItem(**row) for row in rows],
    )
