from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from fastapi import Request
from app.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=3600,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Control-plane engine: always points at the shared oms_db.
# For the main pod CONTROL_DATABASE_URL is blank → reuse the same engine.
# For tenant pods CONTROL_DATABASE_URL points back at oms_db.
_control_db_url = settings.CONTROL_DATABASE_URL or settings.DATABASE_URL
control_engine = create_async_engine(
    _control_db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
)

control_session_factory = async_sessionmaker(
    control_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Return a session for the active environment's database.

    If the EnvironmentMiddleware has resolved an environment (request.state.environment),
    route to its engine via the EnvironmentEngineRegistry. Otherwise use the default engine.
    """
    env = getattr(request.state, "environment", None)
    factory = async_session_factory  # default

    if env is not None:
        try:
            from app.database.env_registry import registry
            await registry.get_or_create_engine(env)
            factory = registry.get_session_factory(str(env.id)) or async_session_factory
        except Exception:
            pass  # Fall through to default factory

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_control_db() -> AsyncGenerator[AsyncSession, None]:
    """Return a session for the shared control-plane database (oms_db).

    On the main pod this is the same as get_db().
    On tenant pods CONTROL_DATABASE_URL redirects this to oms_db so that
    organizations, environments and users are always visible.
    """
    async with control_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables and apply additive schema migrations."""
    # Enum value additions must run outside a transaction block (PostgreSQL restriction).
    sa = __import__("sqlalchemy")
    async with engine.connect() as conn:
        for val in ["AI_ADAPTIVE", "AI_HYBRID"]:
            try:
                await conn.execute(sa.text(f"ALTER TYPE sourcingstrategy ADD VALUE IF NOT EXISTS '{val}'"))
            except Exception:
                pass
        for val in ["B2B", "EDI", "WHOLESALE"]:
            try:
                await conn.execute(sa.text(f"ALTER TYPE orderchannel ADD VALUE IF NOT EXISTS '{val}'"))
            except Exception:
                pass
        await conn.commit()

    async with engine.begin() as conn:
        from app.models.postgres import connector_models, order_models, inventory_models, node_models, sourcing_rule_models, auth_models, ai_models, org_models, lifecycle_models, b2b_models, brand_models, invoice_models, return_models, customer_models, api_key_models, user_brand_role_models  # noqa
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        # Additive migrations
        for ddl in [
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS tenant_mode VARCHAR(20) DEFAULT 'HYBRID'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS platform_role VARCHAR(20)",
            "ALTER TABLE environments ADD COLUMN IF NOT EXISTS base_url VARCHAR(500)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS lifecycle_id UUID REFERENCES lifecycles(id)",
            # B2B migrations — columns first, then FK constraints separately (idempotent)
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type VARCHAR(20) DEFAULT 'RETAIL'",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_account_id UUID",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS po_number VARCHAR(100)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_terms VARCHAR(20) DEFAULT 'PREPAID'",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) DEFAULT 'NOT_REQUIRED'",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS approved_by_id UUID",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_due_date TIMESTAMPTZ",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_name VARCHAR(200)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_address1 VARCHAR(255)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_address2 VARCHAR(255)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_city VARCHAR(100)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_state VARCHAR(100)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_postal_code VARCHAR(20)",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_country VARCHAR(3) DEFAULT 'US'",
            # FK constraints — each guarded by a DO block so re-runs are safe
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'orders_customer_account_id_fkey'
                      AND table_name = 'orders'
                ) THEN
                    ALTER TABLE orders ADD CONSTRAINT orders_customer_account_id_fkey
                        FOREIGN KEY (customer_account_id) REFERENCES customer_accounts(id);
                END IF;
            END $$""",
            """DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'orders_approved_by_id_fkey'
                      AND table_name = 'orders'
                ) THEN
                    ALTER TABLE orders ADD CONSTRAINT orders_approved_by_id_fkey
                        FOREIGN KEY (approved_by_id) REFERENCES users(id);
                END IF;
            END $$""",
            "CREATE INDEX IF NOT EXISTS ix_orders_customer_account ON orders(customer_account_id)",
            "CREATE INDEX IF NOT EXISTS ix_orders_po_number ON orders(po_number)",
            "CREATE INDEX IF NOT EXISTS ix_orders_approval_status ON orders(approval_status)",
        ]:
            await conn.execute(sa.text(ddl))
        # Backfill: existing superadmins get SUPERADMIN role
        await conn.execute(
            sa.text(
                "UPDATE users SET platform_role = 'SUPERADMIN' "
                "WHERE is_superadmin = TRUE AND platform_role IS NULL"
            )
        )

    # Brand entity migrations — idempotent via IF NOT EXISTS / IF EXISTS guards
    async with engine.begin() as conn:
        for ddl in [
            "CREATE TABLE IF NOT EXISTS brands (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), slug VARCHAR(80) UNIQUE NOT NULL, name VARCHAR(200) NOT NULL, tenant_mode VARCHAR(20) NOT NULL DEFAULT 'HYBRID', description TEXT, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
            "ALTER TABLE sourcing_rules ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
            "ALTER TABLE customer_accounts ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
            "ALTER TABLE connectors ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
            "CREATE INDEX IF NOT EXISTS ix_orders_brand ON orders(brand_id)",
            "CREATE INDEX IF NOT EXISTS ix_sourcing_rules_brand ON sourcing_rules(brand_id)",
            "CREATE INDEX IF NOT EXISTS ix_customer_accounts_brand ON customer_accounts(brand_id)",
            "CREATE INDEX IF NOT EXISTS ix_connectors_brand ON connectors(brand_id)",
        ]:
            await conn.execute(sa.text(ddl))

    # Phase 2/3/5 migrations — BrandConfig, BrandNode, inventory_mode, brand isolation, seller brand
    async with engine.begin() as conn:
        for ddl in [
            # inventory_mode column on brands (SHARED / ISOLATED)
            "ALTER TABLE brands ADD COLUMN IF NOT EXISTS inventory_mode VARCHAR(20) NOT NULL DEFAULT 'SHARED'",
            # BrandConfig — one-to-one operational config per brand
            """CREATE TABLE IF NOT EXISTS brand_configs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                default_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                default_locale VARCHAR(10) NOT NULL DEFAULT 'en-US',
                sla_ship_hours INT NOT NULL DEFAULT 48,
                sla_deliver_days INT NOT NULL DEFAULT 5,
                return_window_days INT NOT NULL DEFAULT 30,
                logo_url TEXT,
                support_email VARCHAR(255),
                support_phone VARCHAR(50),
                default_fulfillment_type VARCHAR(50),
                auto_approve_orders BOOLEAN NOT NULL DEFAULT FALSE,
                ai_sourcing_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(brand_id)
            )""",
            # BrandNode — many brand-to-node assignments with priority
            """CREATE TABLE IF NOT EXISTS brand_nodes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                node_id UUID NOT NULL REFERENCES fulfillment_nodes(id) ON DELETE CASCADE,
                priority INT NOT NULL DEFAULT 100,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                max_daily_orders INT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(brand_id, node_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ix_brand_nodes_brand ON brand_nodes(brand_id)",
            # brand_id on inventory_items for ISOLATED mode
            "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
            "CREATE INDEX IF NOT EXISTS ix_inventory_items_brand ON inventory_items(brand_id)",
            # seller_brand_id on orders for marketplace / B2B2C participant model
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS seller_brand_id UUID REFERENCES brands(id)",
            "CREATE INDEX IF NOT EXISTS ix_orders_seller_brand ON orders(seller_brand_id)",
            # B2B account contacts + addresses (Agent C)
            "CREATE TABLE IF NOT EXISTS account_contacts (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), customer_account_id UUID NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE, role VARCHAR(20) NOT NULL DEFAULT 'OTHER', first_name VARCHAR(100) NOT NULL, last_name VARCHAR(100) NOT NULL, email VARCHAR(255), phone VARCHAR(30), title VARCHAR(100), is_primary BOOLEAN NOT NULL DEFAULT FALSE, receives_invoices BOOLEAN NOT NULL DEFAULT FALSE, receives_order_updates BOOLEAN NOT NULL DEFAULT TRUE, is_active BOOLEAN NOT NULL DEFAULT TRUE, notes TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())",
            "CREATE INDEX IF NOT EXISTS ix_account_contacts_account ON account_contacts(customer_account_id)",
            "CREATE TABLE IF NOT EXISTS account_addresses (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), customer_account_id UUID NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE, address_type VARCHAR(20) NOT NULL DEFAULT 'SHIPPING', label VARCHAR(100), address1 VARCHAR(255) NOT NULL, address2 VARCHAR(255), city VARCHAR(100) NOT NULL, state VARCHAR(100), postal_code VARCHAR(20) NOT NULL, country VARCHAR(3) NOT NULL DEFAULT 'US', latitude FLOAT, longitude FLOAT, is_default BOOLEAN NOT NULL DEFAULT FALSE, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())",
            "CREATE INDEX IF NOT EXISTS ix_account_addresses_account ON account_addresses(customer_account_id)",
            # Invoice line items, payments, credit memos (Agent B)
            "CREATE TABLE IF NOT EXISTS invoice_line_items (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE, order_item_id UUID REFERENCES order_items(id), sku VARCHAR(100) NOT NULL, description VARCHAR(500) NOT NULL, quantity NUMERIC(10,3) NOT NULL, unit_price NUMERIC(12,2) NOT NULL, discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0, tax_amount NUMERIC(12,2) NOT NULL DEFAULT 0, line_total NUMERIC(12,2) NOT NULL, created_at TIMESTAMPTZ DEFAULT now())",
            "CREATE INDEX IF NOT EXISTS ix_invoice_line_items_invoice ON invoice_line_items(invoice_id)",
            "CREATE TABLE IF NOT EXISTS invoice_payments (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE, amount NUMERIC(12,2) NOT NULL, payment_date DATE NOT NULL, payment_method VARCHAR(30) NOT NULL, reference_number VARCHAR(100), notes TEXT, recorded_by_id UUID REFERENCES users(id), created_at TIMESTAMPTZ DEFAULT now())",
            "CREATE INDEX IF NOT EXISTS ix_invoice_payments_invoice ON invoice_payments(invoice_id)",
            "CREATE TABLE IF NOT EXISTS credit_memos (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), memo_number VARCHAR(50) UNIQUE NOT NULL, customer_account_id UUID NOT NULL REFERENCES customer_accounts(id), invoice_id UUID REFERENCES invoices(id), order_id UUID REFERENCES orders(id), status VARCHAR(20) NOT NULL DEFAULT 'DRAFT', amount NUMERIC(12,2) NOT NULL, currency VARCHAR(3) NOT NULL DEFAULT 'USD', reason VARCHAR(500) NOT NULL, notes TEXT, issued_date DATE, applied_date DATE, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())",
            "CREATE INDEX IF NOT EXISTS ix_credit_memos_account ON credit_memos(customer_account_id)",
            "CREATE INDEX IF NOT EXISTS ix_credit_memos_invoice ON credit_memos(invoice_id)",
        ]:
            await conn.execute(sa.text(ddl))

    # RMA / Refund migrations
    async with engine.begin() as conn:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS order_returns (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                return_number VARCHAR(50) UNIQUE NOT NULL,
                order_id UUID NOT NULL REFERENCES orders(id),
                status VARCHAR(20) NOT NULL DEFAULT 'REQUESTED',
                reason VARCHAR(50) NOT NULL,
                customer_notes TEXT,
                staff_notes TEXT,
                return_tracking_number VARCHAR(100),
                return_carrier VARCHAR(50),
                received_at TIMESTAMPTZ,
                restocked_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_order_returns_order_id ON order_returns(order_id)",
            "CREATE INDEX IF NOT EXISTS ix_order_returns_status ON order_returns(status)",
            """CREATE TABLE IF NOT EXISTS return_items (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                return_id UUID NOT NULL REFERENCES order_returns(id) ON DELETE CASCADE,
                order_item_id UUID REFERENCES order_items(id),
                sku VARCHAR(100) NOT NULL,
                description VARCHAR(500) NOT NULL,
                quantity_requested NUMERIC(10,3) NOT NULL,
                quantity_received NUMERIC(10,3),
                condition VARCHAR(20),
                restock BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_return_items_return_id ON return_items(return_id)",
            """CREATE TABLE IF NOT EXISTS refunds (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                refund_number VARCHAR(50) UNIQUE NOT NULL,
                order_id UUID NOT NULL REFERENCES orders(id),
                return_id UUID REFERENCES order_returns(id),
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                refund_method VARCHAR(30) NOT NULL,
                amount NUMERIC(12,2) NOT NULL,
                currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                transaction_id VARCHAR(200),
                reason VARCHAR(500) NOT NULL,
                notes TEXT,
                processed_at TIMESTAMPTZ,
                processed_by_id UUID REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_refunds_order_id ON refunds(order_id)",
            "CREATE INDEX IF NOT EXISTS ix_refunds_status ON refunds(status)",
            "CREATE INDEX IF NOT EXISTS ix_refunds_return_id ON refunds(return_id)",
        ]:
            await conn.execute(sa.text(ddl))

    # B2C customer profile tables
    async with engine.begin() as conn:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS customer_profiles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                phone VARCHAR(30),
                brand_id UUID REFERENCES brands(id),
                tags JSON DEFAULT '[]',
                email_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
                sms_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
                preferred_language VARCHAR(10) NOT NULL DEFAULT 'en',
                total_orders INTEGER NOT NULL DEFAULT 0,
                total_spent NUMERIC(14,2) NOT NULL DEFAULT 0,
                last_order_at TIMESTAMPTZ,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                notes TEXT,
                metadata JSON DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_customer_email_brand UNIQUE (email, brand_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ix_customer_profiles_email_brand ON customer_profiles(email, brand_id)",
            "CREATE INDEX IF NOT EXISTS ix_customer_profiles_brand ON customer_profiles(brand_id)",
            "CREATE INDEX IF NOT EXISTS ix_customer_profiles_active ON customer_profiles(is_active)",
            """CREATE TABLE IF NOT EXISTS customer_profile_addresses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
                label VARCHAR(100),
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                address1 VARCHAR(255) NOT NULL,
                address2 VARCHAR(255),
                city VARCHAR(100) NOT NULL,
                state VARCHAR(100),
                postal_code VARCHAR(20) NOT NULL,
                country VARCHAR(3) NOT NULL DEFAULT 'US',
                phone VARCHAR(30),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_customer_profile_addresses_customer ON customer_profile_addresses(customer_id)",
        ]:
            await conn.execute(sa.text(ddl))

    # Lifecycle new columns
    async with engine.begin() as conn:
        for ddl in [
            "ALTER TABLE lifecycles ADD COLUMN IF NOT EXISTS pipeline_type VARCHAR(20) NOT NULL DEFAULT 'ORDER'",
            "ALTER TABLE lifecycles ADD COLUMN IF NOT EXISTS order_type VARCHAR(20)",
            "ALTER TABLE lifecycles ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
            "ALTER TABLE lifecycles ADD COLUMN IF NOT EXISTS custom_statuses JSON DEFAULT '[]'",
            "CREATE INDEX IF NOT EXISTS ix_lifecycles_pipeline_type ON lifecycles(pipeline_type)",
            "CREATE INDEX IF NOT EXISTS ix_lifecycles_brand ON lifecycles(brand_id)",
            # Distribution Groups tables
            """CREATE TABLE IF NOT EXISTS distribution_groups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(200) NOT NULL,
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                brand_id UUID REFERENCES brands(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS ix_distribution_groups_active ON distribution_groups(is_active)",
            "CREATE INDEX IF NOT EXISTS ix_distribution_groups_brand ON distribution_groups(brand_id)",
            """CREATE TABLE IF NOT EXISTS distribution_group_members (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                group_id UUID NOT NULL REFERENCES distribution_groups(id) ON DELETE CASCADE,
                node_id UUID NOT NULL REFERENCES fulfillment_nodes(id) ON DELETE CASCADE,
                priority INTEGER NOT NULL DEFAULT 1,
                CONSTRAINT uq_dg_member_group_node UNIQUE (group_id, node_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ix_dg_members_group_id ON distribution_group_members(group_id)",
            "CREATE INDEX IF NOT EXISTS ix_dg_members_node_id ON distribution_group_members(node_id)",
            # sourcing_targets column on sourcing rules
            "ALTER TABLE sourcing_rules ADD COLUMN IF NOT EXISTS sourcing_targets JSON DEFAULT '[]'",
        ]:
            await conn.execute(sa.text(ddl))

    # User-brand role assignments — brand-scoped access control
    async with engine.begin() as conn:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS user_brand_roles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                environment_id UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                CONSTRAINT uq_user_brand_env UNIQUE (user_id, brand_id, environment_id)
            )""",
            "CREATE INDEX IF NOT EXISTS ix_user_brand_roles_user ON user_brand_roles(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_user_brand_roles_brand ON user_brand_roles(brand_id)",
            "CREATE INDEX IF NOT EXISTS ix_user_brand_roles_env ON user_brand_roles(environment_id)",
        ]:
            await conn.execute(sa.text(ddl))

    # Propagate data-plane migrations to all active environment DBs
    await _run_env_migrations()


async def _migrate_env_db(db_url: str) -> None:
    """Apply data-plane B2B migrations to a tenant environment DB."""
    import logging
    sa = __import__("sqlalchemy")
    logger = logging.getLogger(__name__)
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        env_engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
        async with env_engine.begin() as conn:
            for ddl in [
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type VARCHAR(20) DEFAULT 'RETAIL'",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_account_id UUID",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS po_number VARCHAR(100)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_terms VARCHAR(20) DEFAULT 'PREPAID'",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) DEFAULT 'NOT_REQUIRED'",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS approved_by_id UUID",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_due_date TIMESTAMPTZ",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_name VARCHAR(200)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_address1 VARCHAR(255)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_address2 VARCHAR(255)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_city VARCHAR(100)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_state VARCHAR(100)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_postal_code VARCHAR(20)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_country VARCHAR(3) DEFAULT 'US'",
                """CREATE TABLE IF NOT EXISTS customer_accounts (
                    id UUID PRIMARY KEY,
                    account_number VARCHAR(50) NOT NULL UNIQUE,
                    company_name VARCHAR(300) NOT NULL,
                    trading_name VARCHAR(300),
                    account_type VARCHAR(30) NOT NULL DEFAULT 'PROSPECT',
                    contact_name VARCHAR(200),
                    contact_email VARCHAR(255),
                    contact_phone VARCHAR(30),
                    credit_limit NUMERIC(14,2) DEFAULT 0,
                    credit_used NUMERIC(14,2) DEFAULT 0,
                    payment_terms VARCHAR(20) DEFAULT 'PREPAID',
                    pricing_tier VARCHAR(20) NOT NULL DEFAULT 'STANDARD',
                    tax_exempt BOOLEAN DEFAULT FALSE,
                    tax_exempt_id VARCHAR(100),
                    billing_name VARCHAR(200),
                    billing_address1 VARCHAR(255),
                    billing_city VARCHAR(100),
                    billing_state VARCHAR(100),
                    billing_country VARCHAR(3) DEFAULT 'US',
                    approval_threshold NUMERIC(14,2),
                    notes TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                )""",
                "CREATE INDEX IF NOT EXISTS ix_orders_customer_account ON orders(customer_account_id)",
                "CREATE INDEX IF NOT EXISTS ix_orders_po_number ON orders(po_number)",
                "CREATE INDEX IF NOT EXISTS ix_orders_approval_status ON orders(approval_status)",
                # Brand entity migrations for tenant DBs
                "CREATE TABLE IF NOT EXISTS brands (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), slug VARCHAR(80) UNIQUE NOT NULL, name VARCHAR(200) NOT NULL, tenant_mode VARCHAR(20) NOT NULL DEFAULT 'HYBRID', description TEXT, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
                "ALTER TABLE sourcing_rules ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
                "ALTER TABLE customer_accounts ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
                "ALTER TABLE connectors ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
                "CREATE INDEX IF NOT EXISTS ix_orders_brand ON orders(brand_id)",
                "CREATE INDEX IF NOT EXISTS ix_sourcing_rules_brand ON sourcing_rules(brand_id)",
                "CREATE INDEX IF NOT EXISTS ix_customer_accounts_brand ON customer_accounts(brand_id)",
                "CREATE INDEX IF NOT EXISTS ix_connectors_brand ON connectors(brand_id)",
                # Phase 2/3/5 — BrandConfig, BrandNode, inventory_mode, brand isolation, seller brand
                "ALTER TABLE brands ADD COLUMN IF NOT EXISTS inventory_mode VARCHAR(20) NOT NULL DEFAULT 'SHARED'",
                """CREATE TABLE IF NOT EXISTS brand_configs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                    default_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                    default_locale VARCHAR(10) NOT NULL DEFAULT 'en-US',
                    sla_ship_hours INT NOT NULL DEFAULT 48,
                    sla_deliver_days INT NOT NULL DEFAULT 5,
                    return_window_days INT NOT NULL DEFAULT 30,
                    logo_url TEXT,
                    support_email VARCHAR(255),
                    support_phone VARCHAR(50),
                    default_fulfillment_type VARCHAR(50),
                    auto_approve_orders BOOLEAN NOT NULL DEFAULT FALSE,
                    ai_sourcing_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(brand_id)
                )""",
                """CREATE TABLE IF NOT EXISTS brand_nodes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                    node_id UUID NOT NULL REFERENCES fulfillment_nodes(id) ON DELETE CASCADE,
                    priority INT NOT NULL DEFAULT 100,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    max_daily_orders INT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(brand_id, node_id)
                )""",
                "CREATE INDEX IF NOT EXISTS ix_brand_nodes_brand ON brand_nodes(brand_id)",
                "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS brand_id UUID REFERENCES brands(id)",
                "CREATE INDEX IF NOT EXISTS ix_inventory_items_brand ON inventory_items(brand_id)",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS seller_brand_id UUID REFERENCES brands(id)",
                "CREATE INDEX IF NOT EXISTS ix_orders_seller_brand ON orders(seller_brand_id)",
                # RMA / Refund tables
                """CREATE TABLE IF NOT EXISTS order_returns (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    return_number VARCHAR(50) UNIQUE NOT NULL,
                    order_id UUID NOT NULL REFERENCES orders(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'REQUESTED',
                    reason VARCHAR(50) NOT NULL,
                    customer_notes TEXT,
                    staff_notes TEXT,
                    return_tracking_number VARCHAR(100),
                    return_carrier VARCHAR(50),
                    received_at TIMESTAMPTZ,
                    restocked_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )""",
                "CREATE INDEX IF NOT EXISTS ix_order_returns_order_id ON order_returns(order_id)",
                "CREATE INDEX IF NOT EXISTS ix_order_returns_status ON order_returns(status)",
                """CREATE TABLE IF NOT EXISTS return_items (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    return_id UUID NOT NULL REFERENCES order_returns(id) ON DELETE CASCADE,
                    order_item_id UUID REFERENCES order_items(id),
                    sku VARCHAR(100) NOT NULL,
                    description VARCHAR(500) NOT NULL,
                    quantity_requested NUMERIC(10,3) NOT NULL,
                    quantity_received NUMERIC(10,3),
                    condition VARCHAR(20),
                    restock BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )""",
                "CREATE INDEX IF NOT EXISTS ix_return_items_return_id ON return_items(return_id)",
                """CREATE TABLE IF NOT EXISTS refunds (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    refund_number VARCHAR(50) UNIQUE NOT NULL,
                    order_id UUID NOT NULL REFERENCES orders(id),
                    return_id UUID REFERENCES order_returns(id),
                    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    refund_method VARCHAR(30) NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                    transaction_id VARCHAR(200),
                    reason VARCHAR(500) NOT NULL,
                    notes TEXT,
                    processed_at TIMESTAMPTZ,
                    processed_by_id UUID REFERENCES users(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )""",
                "CREATE INDEX IF NOT EXISTS ix_refunds_order_id ON refunds(order_id)",
                "CREATE INDEX IF NOT EXISTS ix_refunds_status ON refunds(status)",
                "CREATE INDEX IF NOT EXISTS ix_refunds_return_id ON refunds(return_id)",
                # B2C customer profile tables
                """CREATE TABLE IF NOT EXISTS customer_profiles (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(255) NOT NULL,
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    phone VARCHAR(30),
                    brand_id UUID REFERENCES brands(id),
                    tags JSON DEFAULT '[]',
                    email_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
                    sms_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
                    preferred_language VARCHAR(10) NOT NULL DEFAULT 'en',
                    total_orders INTEGER NOT NULL DEFAULT 0,
                    total_spent NUMERIC(14,2) NOT NULL DEFAULT 0,
                    last_order_at TIMESTAMPTZ,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    notes TEXT,
                    metadata JSON DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_customer_email_brand UNIQUE (email, brand_id)
                )""",
                "CREATE INDEX IF NOT EXISTS ix_customer_profiles_email_brand ON customer_profiles(email, brand_id)",
                "CREATE INDEX IF NOT EXISTS ix_customer_profiles_brand ON customer_profiles(brand_id)",
                "CREATE INDEX IF NOT EXISTS ix_customer_profiles_active ON customer_profiles(is_active)",
                """CREATE TABLE IF NOT EXISTS customer_profile_addresses (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
                    label VARCHAR(100),
                    is_default BOOLEAN NOT NULL DEFAULT FALSE,
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    address1 VARCHAR(255) NOT NULL,
                    address2 VARCHAR(255),
                    city VARCHAR(100) NOT NULL,
                    state VARCHAR(100),
                    postal_code VARCHAR(20) NOT NULL,
                    country VARCHAR(3) NOT NULL DEFAULT 'US',
                    phone VARCHAR(30),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )""",
                "CREATE INDEX IF NOT EXISTS ix_customer_profile_addresses_customer ON customer_profile_addresses(customer_id)",
            ]:
                await conn.execute(sa.text(ddl))
        await env_engine.dispose()
    except Exception as exc:
        logger.warning("_migrate_env_db: failed for %s: %s", db_url[:60], exc)


async def _run_env_migrations() -> None:
    """Apply data-plane migrations to all registered environment DBs."""
    import re
    import logging
    logger = logging.getLogger(__name__)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT db_name, pg_host, pg_port, pg_user, pg_password "
                    "FROM environments WHERE status = 'ACTIVE'"
                )
            )
            envs = rows.fetchall()

        control_db = settings.DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
        for row in envs:
            db_name, pg_host, pg_port, pg_user, pg_password = row
            if not db_name or db_name == control_db:
                continue
            host = pg_host or "postgres"
            port = pg_port or 5432
            user = pg_user or "oms_user"
            base_url = re.sub(r"[^/]+$", "", settings.DATABASE_URL)
            if pg_password:
                db_url = f"postgresql+asyncpg://{user}:{pg_password}@{host}:{port}/{db_name}"
            else:
                db_url = f"{base_url}{db_name}"
            await _migrate_env_db(db_url)
            logger.info("init_db: applied data-plane migrations to %s", db_name)
    except Exception as exc:
        logger.warning("_run_env_migrations: %s", exc)


async def drop_db():
    """Drop all tables (for testing/reset only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
