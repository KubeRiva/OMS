from elasticsearch import AsyncElasticsearch
from typing import Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)

es_client: Optional[AsyncElasticsearch] = None

ORDER_INDEX = "oms_orders"
PRODUCT_INDEX = "oms_products"


async def connect_to_elasticsearch():
    global es_client
    es_client = AsyncElasticsearch(
        [settings.ELASTICSEARCH_URL],
        retry_on_timeout=True,
        max_retries=3,
        request_timeout=30,
    )
    # Verify connection
    info = await es_client.info()
    logger.info(f"Connected to Elasticsearch: {info['version']['number']}")

    # Create indexes
    await _create_indexes()


async def close_elasticsearch():
    global es_client
    if es_client:
        await es_client.close()
        logger.info("Disconnected from Elasticsearch")


async def get_es_client() -> AsyncElasticsearch:
    if es_client is None:
        raise RuntimeError("Elasticsearch client not initialized.")
    return es_client


async def _create_indexes():
    """Create Elasticsearch indexes with mappings."""
    # Orders index
    order_mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "order_number": {"type": "keyword"},
                "channel": {"type": "keyword"},
                "status": {"type": "keyword"},
                "fulfillment_type": {"type": "keyword"},
                "customer_email": {"type": "keyword"},
                "customer_name": {"type": "text", "analyzer": "standard"},
                "total_amount": {"type": "float"},
                "currency": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "shipping_city": {"type": "keyword"},
                "shipping_state": {"type": "keyword"},
                "shipping_country": {"type": "keyword"},
                "line_items": {
                    "type": "nested",
                    "properties": {
                        "sku": {"type": "keyword"},
                        "name": {"type": "text"},
                        "quantity": {"type": "integer"},
                        "unit_price": {"type": "float"},
                    },
                },
                "tags": {"type": "keyword"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "oms_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "stop"],
                    }
                }
            },
        },
    }

    if not await es_client.indices.exists(index=ORDER_INDEX):
        await es_client.indices.create(index=ORDER_INDEX, body=order_mapping)
        logger.info(f"Created Elasticsearch index: {ORDER_INDEX}")

    # Products index
    product_mapping = {
        "mappings": {
            "properties": {
                "sku": {"type": "keyword"},
                "name": {"type": "text", "analyzer": "standard"},
                "description": {"type": "text"},
                "category": {"type": "keyword"},
                "price": {"type": "float"},
                "weight": {"type": "float"},
                "active": {"type": "boolean"},
            }
        },
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    }

    if not await es_client.indices.exists(index=PRODUCT_INDEX):
        await es_client.indices.create(index=PRODUCT_INDEX, body=product_mapping)
        logger.info(f"Created Elasticsearch index: {PRODUCT_INDEX}")
