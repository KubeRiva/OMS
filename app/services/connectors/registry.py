"""Registry mapping ConnectorType → implementation class."""
from app.models.postgres.connector_models import ConnectorType
from app.services.connectors.base import BaseConnector
from app.services.connectors.shopify import ShopifyConnector
from app.services.connectors.amazon import AmazonSPConnector

_REGISTRY: dict[ConnectorType, type[BaseConnector]] = {
    ConnectorType.SHOPIFY: ShopifyConnector,
    ConnectorType.AMAZON_SP: AmazonSPConnector,
    # Future:
    # ConnectorType.WOOCOMMERCE: WooCommerceConnector,
    # ConnectorType.FEDEX:       FedExConnector,
}


def get_connector(connector) -> BaseConnector:
    """
    Return an initialized connector implementation for the given Connector ORM object.
    Raises ValueError if no implementation exists for the connector_type.
    """
    cls = _REGISTRY.get(connector.connector_type)
    if cls is None:
        raise ValueError(
            f"No connector implementation for type '{connector.connector_type}'. "
            f"Supported types: {[k.value for k in _REGISTRY]}"
        )
    return cls(connector)


def get_supported_types() -> list[str]:
    """Return the list of connector types that have implementations."""
    return [k.value for k in _REGISTRY]
