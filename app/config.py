from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---------------------------------------------------------------------------
    # Tenant identity — injected by Kubernetes per pod
    # ---------------------------------------------------------------------------
    TENANT_SLUG: str = "default"          # e.g. "acme", "widgetco"
    PLAN_TIER: str = "STARTER"            # STARTER | GROWTH | PRO | ENTERPRISE

    # ---------------------------------------------------------------------------
    # PostgreSQL — REQUIRED
    # ---------------------------------------------------------------------------
    DATABASE_URL: str                     # postgresql+asyncpg://user:pass@host/db  (tenant DB)
    SYNC_DATABASE_URL: str = ""           # postgresql+psycopg2://... (Celery workers)
    # Control-plane DB: organizations, environments, users.
    # Defaults to DATABASE_URL (correct for the main pod).
    # Tenant pods must set this to point at the shared oms_db.
    CONTROL_DATABASE_URL: str = ""

    # ---------------------------------------------------------------------------
    # MongoDB — REQUIRED
    # ---------------------------------------------------------------------------
    MONGODB_URL: str
    MONGODB_DB: str = "oms_events"
    MONGODB_AI_DB: str = "oms_ai_learning"

    # ---------------------------------------------------------------------------
    # Redis — REQUIRED
    # ---------------------------------------------------------------------------
    REDIS_URL: str
    CELERY_BROKER_URL: str = ""           # defaults to REDIS_URL db 1 if blank
    CELERY_RESULT_BACKEND: str = ""       # defaults to REDIS_URL db 2 if blank

    # ---------------------------------------------------------------------------
    # Elasticsearch
    # ---------------------------------------------------------------------------
    ELASTICSEARCH_URL: str = "http://elasticsearch:9200"

    # ---------------------------------------------------------------------------
    # App
    # ---------------------------------------------------------------------------
    SECRET_KEY: str = "dev-super-secret-key-change-in-production-please"
    API_KEY: str = "dev-api-key"
    ENVIRONMENT: str = "development"      # development | staging | production
    FRONTEND_URL: str = ""
    API_URL: str = ""

    @property
    def DEBUG(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def LOG_LEVEL(self) -> str:
        return "DEBUG" if self.ENVIRONMENT == "development" else "INFO"

    # ---------------------------------------------------------------------------
    # Webhook
    # ---------------------------------------------------------------------------
    WEBHOOK_SECRET: str = "dev-webhook-signing-secret"
    WEBHOOK_TIMEOUT_SECONDS: int = 10
    WEBHOOK_MAX_RETRIES: int = 3

    # ---------------------------------------------------------------------------
    # Sourcing
    # ---------------------------------------------------------------------------
    DEFAULT_SOURCING_STRATEGY: str = "DISTANCE_OPTIMAL"
    MAX_SPLIT_NODES: int = 3

    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # ---------------------------------------------------------------------------
    # Backorder retry
    # ---------------------------------------------------------------------------
    BACKORDER_RETRY_INTERVAL_MINUTES: int = 30
    BACKORDER_MAX_AGE_HOURS: int = 72

    # ---------------------------------------------------------------------------
    # Auth
    # ---------------------------------------------------------------------------
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ---------------------------------------------------------------------------
    # Bootstrap admin — created once on first startup when no users exist
    # ---------------------------------------------------------------------------
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@oms.local"
    BOOTSTRAP_ADMIN_PASSWORD: str = ""  # empty = auto-generate a random password

    # ---------------------------------------------------------------------------
    # Security
    # ---------------------------------------------------------------------------
    ALLOWED_ORIGINS: str = "http://localhost:3001,http://localhost:3000"
    TEST_API_KEY: str = "dev-test-key"

    # ---------------------------------------------------------------------------
    # DigitalOcean Spaces (object storage)
    # ---------------------------------------------------------------------------
    SPACES_BUCKET: str = ""               # e.g. "oms-assets"
    SPACES_REGION: str = "nyc3"           # DO Spaces region
    SPACES_KEY: str = ""                  # DO Spaces access key
    SPACES_SECRET: str = ""              # DO Spaces secret key
    SPACES_ENDPOINT: str = ""            # e.g. "https://nyc3.digitaloceanspaces.com"

    # ---------------------------------------------------------------------------
    # Shopify App (App Store OAuth)
    # ---------------------------------------------------------------------------
    SHOPIFY_API_KEY: str = ""             # From Shopify Partners dashboard
    SHOPIFY_API_SECRET: str = ""          # From Shopify Partners dashboard
    SHOPIFY_APP_HOST: str = ""            # Public hostname of this app, e.g. "https://oms.yourcompany.com"
    SHOPIFY_API_VERSION: str = "2024-07"  # Shopify API version for new installs
    SHOPIFY_SCOPES: str = "read_orders,write_orders,read_fulfillments,write_fulfillments,read_products,write_inventory,read_inventory"

    # ---------------------------------------------------------------------------
    # Computed properties
    # ---------------------------------------------------------------------------

    @property
    def get_allowed_origins(self) -> list[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        if self.ENVIRONMENT == "production":
            if self.FRONTEND_URL:
                origins.append(self.FRONTEND_URL)
            if self.API_URL:
                origins.append(self.API_URL)
            # In production, actively filter out localhost/127.0.0.1 origins
            import logging as _logging
            _log = _logging.getLogger(__name__)
            localhost_origins = [o for o in origins if "localhost" in o or "127.0.0.1" in o]
            if localhost_origins:
                _log.warning(
                    "SECURITY: Removing localhost entries from production CORS config: %s — "
                    "set ALLOWED_ORIGINS to your actual frontend domain(s).",
                    localhost_origins,
                )
            origins = [o for o in origins if "localhost" not in o and "127.0.0.1" not in o]
        # Allow Shopify Admin to make cross-origin requests when App Bridge
        # embedded mode is enabled. The frontend runs inside admin.shopify.com
        # and calls the OMS API with an Authorization bearer token (not cookies).
        if self.SHOPIFY_API_KEY:
            if "https://admin.shopify.com" not in origins:
                origins.append("https://admin.shopify.com")
        return origins

    @property
    def celery_broker(self) -> str:
        if self.CELERY_BROKER_URL:
            return self.CELERY_BROKER_URL
        # Derive from REDIS_URL: swap db index to 1
        import re
        return re.sub(r"/\d*$", "/1", self.REDIS_URL)

    @property
    def celery_backend(self) -> str:
        if self.CELERY_RESULT_BACKEND:
            return self.CELERY_RESULT_BACKEND
        import re
        return re.sub(r"/\d*$", "/2", self.REDIS_URL)

    # ---------------------------------------------------------------------------
    # Fail-fast: refuse to start in production with insecure defaults
    # ---------------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        if self.ENVIRONMENT != "production":
            return self
        insecure = {
            "SECRET_KEY": ("dev-super-secret-key-change-in-production-please", self.SECRET_KEY),
            "WEBHOOK_SECRET": ("dev-webhook-signing-secret", self.WEBHOOK_SECRET),
            "API_KEY": ("dev-api-key", self.API_KEY),
        }
        bad = [name for name, (default, actual) in insecure.items() if actual == default]
        if bad:
            raise ValueError(
                f"Production deployment detected but insecure defaults still set: {', '.join(bad)}. "
                "Set these to strong random values before running in production."
            )
        # If Shopify App Store integration is enabled, the API secret must be set.
        if self.SHOPIFY_API_KEY and not self.SHOPIFY_API_SECRET:
            raise ValueError(
                "SHOPIFY_API_KEY is set but SHOPIFY_API_SECRET is empty. "
                "Both must be configured together for Shopify App Store integration."
            )
        if self.SHOPIFY_API_KEY and not self.SHOPIFY_APP_HOST:
            raise ValueError(
                "SHOPIFY_APP_HOST must be set when SHOPIFY_API_KEY is configured. "
                "Set it to the public HTTPS URL of this app, e.g. https://oms.yourcompany.com"
            )
        if self.PLAN_TIER not in ("STARTER", "GROWTH", "PRO", "ENTERPRISE"):
            raise ValueError(f"Invalid PLAN_TIER: {self.PLAN_TIER}")
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
