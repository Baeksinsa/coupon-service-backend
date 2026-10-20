"""재고 조회 / 쿠폰 발급."""
import logging

from fastapi import APIRouter, HTTPException, Response

from .. import cache, repository
from ..metrics import counters
from ..repository import IssueResult
from ..schemas import IssueRequest, IssueResponse, StockResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/{event_id}", response_model=StockResponse)
def get_stock(event_id: int) -> StockResponse:
    """잔여 재고 조회. Redis Hit → 반환, Miss → DB 조회 후 짧은 TTL 로 캐시."""
    cached = cache.get_remaining(event_id)
    if cached is not None:
        counters.inc("stock_cache_hit")
        meta = cache.get_meta(event_id) or {}
        return StockResponse(
            event_id=event_id,
            name=meta.get("name"),
            total_qty=meta.get("total_qty"),
            remaining=cached,
            source="cache",
        )

    counters.inc("stock_cache_miss")
    event = repository.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    remaining = int(event["remaining_qty"])
    cache.set_remaining(event_id, remaining)
    cache.set_meta(event_id, event["name"], int(event["total_qty"]))
    return StockResponse(
        event_id=event_id,
        name=event["name"],
        total_qty=int(event["total_qty"]),
        remaining=remaining,
        source="db",
    )


@router.post("/{event_id}/issue", response_model=IssueResponse)
def issue_coupon(event_id: int, body: IssueRequest, response: Response) -> IssueResponse:
    """동기 발급. 201 발급 / 409 중복 / 410 마감."""
    result, data = repository.issue(event_id, body.userId)
    data = data or {}

    if result is IssueResult.NOT_FOUND:
        counters.inc("issue_404")
        raise HTTPException(status_code=404, detail="event not found")

    if result is IssueResult.ISSUED:
        # COMMIT 이 끝난 뒤에만 캐시를 무효화한다.
        cache.invalidate(event_id)
        counters.inc("issue_201")
        response.status_code = 201
        return IssueResponse(
            status="issued",
            event_id=event_id,
            userId=body.userId,
            coupon_id=data.get("coupon_id"),
            issued_at=data.get("issued_at"),
            remaining=data.get("remaining"),
            message="쿠폰이 발급되었습니다.",
        )

    if result is IssueResult.DUPLICATE:
        counters.inc("issue_409")
        response.status_code = 409
        return IssueResponse(
            status="duplicate",
            event_id=event_id,
            userId=body.userId,
            coupon_id=data.get("coupon_id"),
            issued_at=data.get("issued_at"),
            message="이미 발급받은 사용자입니다.",
        )

    counters.inc("issue_410")
    response.status_code = 410
    return IssueResponse(
        status="sold_out",
        event_id=event_id,
        userId=body.userId,
        remaining=0,
        message="쿠폰이 모두 소진되었습니다.",
    )
