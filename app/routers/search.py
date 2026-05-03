"""Search router — Elasticsearch-powered full-text order search."""
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)
from typing import Optional
from datetime import datetime

from app.database.elasticsearch_client import get_es_client, ORDER_INDEX, PRODUCT_INDEX
from app.dependencies.auth import get_current_user
from app.schemas.search import OrderSearchRequest, OrderSearchResponse, SearchHit, ProductSearchRequest

router = APIRouter(prefix="/search", tags=["Search"], dependencies=[Depends(get_current_user)])


@router.post("/orders", response_model=OrderSearchResponse)
async def search_orders(payload: OrderSearchRequest):
    es = await get_es_client()
    start = time.time()

    must_clauses = []
    filter_clauses = []

    if payload.query:
        must_clauses.append({
            "multi_match": {
                "query": payload.query,
                "fields": ["order_number^3", "customer_email^2", "customer_name", "tags"],
                "type": "best_fields",
                "fuzziness": "AUTO",
            }
        })

    if payload.channel:
        filter_clauses.append({"term": {"channel": payload.channel}})
    if payload.status:
        filter_clauses.append({"term": {"status": payload.status}})
    if payload.fulfillment_type:
        filter_clauses.append({"term": {"fulfillment_type": payload.fulfillment_type}})
    if payload.customer_email:
        filter_clauses.append({"term": {"customer_email": payload.customer_email}})
    if payload.tags:
        filter_clauses.append({"terms": {"tags": payload.tags}})

    date_range = {}
    if payload.from_date:
        date_range["gte"] = payload.from_date.isoformat()
    if payload.to_date:
        date_range["lte"] = payload.to_date.isoformat()
    if date_range:
        filter_clauses.append({"range": {"created_at": date_range}})

    amount_range = {}
    if payload.min_amount is not None:
        amount_range["gte"] = payload.min_amount
    if payload.max_amount is not None:
        amount_range["lte"] = payload.max_amount
    if amount_range:
        filter_clauses.append({"range": {"total_amount": amount_range}})

    query_body = {
        "bool": {
            "must": must_clauses if must_clauses else [{"match_all": {}}],
            "filter": filter_clauses,
        }
    }

    sort_order = payload.sort_order
    # Allowlist prevents user-controlled strings from reaching ES sort clause
    _ALLOWED_SORT_FIELDS = {
        "created_at", "updated_at", "total_amount",
        "order_number", "channel", "status", "fulfillment_type", "customer_email",
    }
    sort_field = payload.sort_by if payload.sort_by in _ALLOWED_SORT_FIELDS else "created_at"

    from_offset = (payload.page - 1) * payload.page_size

    try:
        response = await es.search(
            index=ORDER_INDEX,
            body={
                "query": query_body,
                "sort": [{sort_field: {"order": sort_order}}],
                "from": from_offset,
                "size": payload.page_size,
            },
        )
    except Exception as e:
        logger.error("Elasticsearch order search error: %s", e)
        raise HTTPException(status_code=500, detail="Search service error")

    elapsed_ms = (time.time() - start) * 1000
    hits_data = response["hits"]
    total = hits_data["total"]["value"] if isinstance(hits_data["total"], dict) else hits_data["total"]

    hits = [
        SearchHit(
            id=h["_id"],
            score=h.get("_score"),
            source=h["_source"],
        )
        for h in hits_data["hits"]
    ]

    return OrderSearchResponse(
        hits=hits,
        total=total,
        page=payload.page,
        page_size=payload.page_size,
        total_pages=(total + payload.page_size - 1) // payload.page_size,
        query_time_ms=round(elapsed_ms, 2),
    )


@router.get("/orders", response_model=OrderSearchResponse)
async def search_orders_get(
    q: Optional[str] = Query(None, description="Search query"),
    status: Optional[str] = None,
    channel: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    payload = OrderSearchRequest(
        query=q,
        status=status,
        channel=channel,
        page=page,
        page_size=page_size,
    )
    return await search_orders(payload)


@router.post("/products", response_model=dict)
async def search_products(payload: ProductSearchRequest):
    es = await get_es_client()
    start = time.time()

    query_body = {
        "bool": {
            "must": [
                {
                    "multi_match": {
                        "query": payload.query,
                        "fields": ["name^3", "description", "category"],
                        "fuzziness": "AUTO",
                    }
                }
            ],
            "filter": [],
        }
    }

    if payload.category:
        query_body["bool"]["filter"].append({"term": {"category": payload.category}})

    price_range = {}
    if payload.min_price is not None:
        price_range["gte"] = payload.min_price
    if payload.max_price is not None:
        price_range["lte"] = payload.max_price
    if price_range:
        query_body["bool"]["filter"].append({"range": {"price": price_range}})

    try:
        response = await es.search(
            index=PRODUCT_INDEX,
            body={
                "query": query_body,
                "from": (payload.page - 1) * payload.page_size,
                "size": payload.page_size,
            },
        )
    except Exception as e:
        logger.error("Elasticsearch product search error: %s", e)
        raise HTTPException(status_code=500, detail="Search service error")

    elapsed_ms = (time.time() - start) * 1000
    hits_data = response["hits"]
    total = hits_data["total"]["value"] if isinstance(hits_data["total"], dict) else hits_data["total"]

    return {
        "hits": [{"id": h["_id"], "score": h.get("_score"), "source": h["_source"]} for h in hits_data["hits"]],
        "total": total,
        "query_time_ms": round(elapsed_ms, 2),
    }
