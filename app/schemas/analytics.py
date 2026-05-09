from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date


class DateRangeParams(BaseModel):
    from_date: Optional[date] = None
    to_date: Optional[date] = None


class OrderVolumeMetric(BaseModel):
    date: str
    count: int
    total_revenue: float
    avg_order_value: float


class ChannelBreakdown(BaseModel):
    channel: str
    count: int
    percentage: float
    total_revenue: float


class FulfillmentTypeBreakdown(BaseModel):
    fulfillment_type: str
    count: int
    percentage: float
    avg_processing_hours: float


class NodePerformanceMetric(BaseModel):
    node_id: str
    node_name: str
    node_code: str
    total_orders: int
    total_allocations: int
    avg_processing_hours: float
    capacity_utilization: float


class SourcingStrategyMetric(BaseModel):
    strategy: str
    count: int
    percentage: float
    avg_split_nodes: float


class OrderTypeBreakdown(BaseModel):
    order_type: str
    count: int
    percentage: float
    total_revenue: float


class DashboardSummary(BaseModel):
    period_start: str
    period_end: str
    total_orders: int
    total_revenue: float
    avg_order_value: float
    orders_by_status: dict
    orders_by_channel: List[ChannelBreakdown]
    orders_by_fulfillment_type: List[FulfillmentTypeBreakdown]
    orders_by_order_type: List[OrderTypeBreakdown]
    top_nodes: List[NodePerformanceMetric]
    sourcing_strategies: List[SourcingStrategyMetric]
    inventory_alerts: List[dict]
