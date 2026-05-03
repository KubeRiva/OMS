from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class OrderSearchRequest(BaseModel):
    query: Optional[str] = None
    channel: Optional[str] = None
    status: Optional[str] = None
    fulfillment_type: Optional[str] = None
    customer_email: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    tags: Optional[List[str]] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: str = "created_at"
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")


class SearchHit(BaseModel):
    id: str
    score: Optional[float] = None
    source: dict


class OrderSearchResponse(BaseModel):
    hits: List[SearchHit]
    total: int
    page: int
    page_size: int
    total_pages: int
    query_time_ms: float


class ProductSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    category: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
