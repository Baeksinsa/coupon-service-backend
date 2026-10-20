"""요청/응답 모델. userId 는 실습용 가상 값이며 개인정보가 아니다 (PRD 5.1)."""
from datetime import datetime

from pydantic import BaseModel, Field


class StockResponse(BaseModel):
    event_id: int
    name: str | None = None
    total_qty: int | None = None
    remaining: int
    source: str = Field(description="cache | db")


class IssueRequest(BaseModel):
    userId: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:@-]+$")


class IssueResponse(BaseModel):
    status: str
    event_id: int
    userId: str
    coupon_id: int | None = None
    issued_at: datetime | None = None
    remaining: int | None = None
    message: str | None = None


class CouponItem(BaseModel):
    coupon_id: int
    event_id: int
    event_name: str
    issued_at: datetime


class UserCouponsResponse(BaseModel):
    userId: str
    count: int
    coupons: list[CouponItem]


class HealthResponse(BaseModel):
    status: str
    instance: str
    db: str | None = None
    cache: str | None = None
