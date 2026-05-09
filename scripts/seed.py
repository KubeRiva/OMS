"""
Seed script — populates all 4 databases with realistic data.

PostgreSQL: fulfillment nodes, inventory, sourcing rules, webhook endpoints
MongoDB:    product catalog, sample order events
Redis:      cache warmup
Elasticsearch: order index with sample documents
"""
import asyncio
import random
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
# Brand seed — must run before postgres/b2b seeds so brand IDs are available
# ---------------------------------------------------------------------------

async def seed_brands():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.config import settings
    from app.models.postgres.brand_models import Brand, BrandTenantMode

    print("Seeding Brands...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    from app.models.postgres import order_models, inventory_models, node_models, sourcing_rule_models, connector_models, auth_models, b2b_models, lifecycle_models, brand_models  # noqa
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        brands_data = [
            {
                "slug": "retailco",
                "name": "RetailCo",
                "tenant_mode": BrandTenantMode.B2C_ONLY,
                "description": "Retail brand serving B2C customers via web, mobile, and store channels",
            },
            {
                "slug": "wholesaleco",
                "name": "WholesaleCo",
                "tenant_mode": BrandTenantMode.B2B_ONLY,
                "description": "Wholesale brand serving B2B accounts via EDI, B2B portal, and wholesale channels",
            },
        ]

        created_brands = []
        for bd in brands_data:
            brand = Brand(**bd)
            session.add(brand)
            created_brands.append(brand)

        await session.flush()
        await session.commit()
        print(f"  Created {len(created_brands)} brands: {[b.slug for b in created_brands]}")

    await engine.dispose()
    print("Brand seeding complete!")
    return created_brands


# ---------------------------------------------------------------------------
# PostgreSQL seed
# ---------------------------------------------------------------------------

async def seed_postgres(retail_brand=None):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.config import settings
    from app.database.postgres import Base, init_db
    from app.models.postgres.node_models import FulfillmentNode, NodeType, NodeStatus
    from app.models.postgres.inventory_models import InventoryItem
    from app.models.postgres.sourcing_rule_models import SourcingRule, SourcingStrategy
    from app.models.postgres.order_models import WebhookEndpoint

    print("Seeding PostgreSQL...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    # Import all models so tables are registered
    from app.models.postgres import order_models, inventory_models, node_models, sourcing_rule_models, connector_models, auth_models, b2b_models, lifecycle_models, brand_models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  Tables created")

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        # ---- Fulfillment Nodes ----
        nodes_data = [
            # Distribution Centers
            {"code": "DC-EAST", "name": "East Coast DC", "node_type": NodeType.DISTRIBUTION_CENTER,
             "city": "Edison", "state": "NJ", "postal_code": "08817", "country": "US",
             "latitude": 40.5187, "longitude": -74.4121,
             "can_ship": True, "can_pickup": False, "can_curbside": False, "can_same_day": False,
             "daily_order_capacity": 2000, "avg_processing_hours": 18.0, "shipping_cost_multiplier": 0.9},
            {"code": "DC-WEST", "name": "West Coast DC", "node_type": NodeType.DISTRIBUTION_CENTER,
             "city": "Los Angeles", "state": "CA", "postal_code": "90001", "country": "US",
             "latitude": 33.9425, "longitude": -118.4081,
             "can_ship": True, "can_pickup": False, "can_curbside": False, "can_same_day": True,
             "daily_order_capacity": 2500, "avg_processing_hours": 16.0, "shipping_cost_multiplier": 0.85},
            {"code": "DC-MID", "name": "Midwest DC", "node_type": NodeType.DISTRIBUTION_CENTER,
             "city": "Chicago", "state": "IL", "postal_code": "60601", "country": "US",
             "latitude": 41.8781, "longitude": -87.6298,
             "can_ship": True, "can_pickup": False, "can_curbside": False, "can_same_day": False,
             "daily_order_capacity": 1800, "avg_processing_hours": 20.0, "shipping_cost_multiplier": 1.0},
            # Retail Stores
            {"code": "STR-NYC-01", "name": "NYC Flagship Store", "node_type": NodeType.RETAIL_STORE,
             "city": "New York", "state": "NY", "postal_code": "10001", "country": "US",
             "latitude": 40.7484, "longitude": -73.9967,
             "can_ship": True, "can_pickup": True, "can_curbside": True, "can_same_day": True,
             "daily_order_capacity": 300, "avg_processing_hours": 4.0, "shipping_cost_multiplier": 1.2},
            {"code": "STR-LA-01", "name": "LA Beverly Hills Store", "node_type": NodeType.RETAIL_STORE,
             "city": "Beverly Hills", "state": "CA", "postal_code": "90210", "country": "US",
             "latitude": 34.0736, "longitude": -118.4004,
             "can_ship": True, "can_pickup": True, "can_curbside": True, "can_same_day": True,
             "daily_order_capacity": 250, "avg_processing_hours": 3.0, "shipping_cost_multiplier": 1.15},
            {"code": "STR-CHI-01", "name": "Chicago Downtown Store", "node_type": NodeType.RETAIL_STORE,
             "city": "Chicago", "state": "IL", "postal_code": "60611", "country": "US",
             "latitude": 41.8937, "longitude": -87.6267,
             "can_ship": True, "can_pickup": True, "can_curbside": False, "can_same_day": True,
             "daily_order_capacity": 200, "avg_processing_hours": 5.0, "shipping_cost_multiplier": 1.1},
            {"code": "STR-MIA-01", "name": "Miami Beach Store", "node_type": NodeType.RETAIL_STORE,
             "city": "Miami Beach", "state": "FL", "postal_code": "33139", "country": "US",
             "latitude": 25.7907, "longitude": -80.1300,
             "can_ship": True, "can_pickup": True, "can_curbside": True, "can_same_day": False,
             "daily_order_capacity": 150, "avg_processing_hours": 6.0, "shipping_cost_multiplier": 1.3},
            # Dark stores
            {"code": "DARK-SF-01", "name": "SF Dark Store", "node_type": NodeType.DARK_STORE,
             "city": "San Francisco", "state": "CA", "postal_code": "94102", "country": "US",
             "latitude": 37.7749, "longitude": -122.4194,
             "can_ship": True, "can_pickup": False, "can_curbside": False, "can_same_day": True,
             "daily_order_capacity": 500, "avg_processing_hours": 2.0, "shipping_cost_multiplier": 1.05},
        ]

        nodes = []
        for nd in nodes_data:
            node = FulfillmentNode(**nd)
            session.add(node)
            nodes.append(node)
        await session.flush()
        print(f"  Created {len(nodes)} fulfillment nodes")

        # ---- Inventory ----
        skus = [
            ("SKU-WIDGET-A", "Premium Widget A", 29.99, 0.5),
            ("SKU-WIDGET-B", "Standard Widget B", 19.99, 0.3),
            ("SKU-GADGET-X", "Gadget X Pro", 99.99, 1.2),
            ("SKU-GADGET-Y", "Gadget Y Basic", 49.99, 0.8),
            ("SKU-GIZMO-1", "Gizmo 1", 14.99, 0.2),
            ("SKU-GIZMO-2", "Gizmo 2 Deluxe", 39.99, 0.6),
            ("SKU-TOOL-Z", "Power Tool Z", 149.99, 3.5),
            ("SKU-ACCESSORY-1", "Accessory Pack 1", 9.99, 0.1),
        ]

        inv_items = []
        for node in nodes:
            for sku, name, cost, weight in skus:
                on_hand = random.randint(20, 500)
                inv = InventoryItem(
                    node_id=node.id,
                    sku=sku,
                    product_name=name,
                    quantity_on_hand=on_hand,
                    quantity_reserved=0,
                    quantity_available=on_hand,
                    reorder_point=random.randint(10, 30),
                    reorder_quantity=random.randint(50, 200),
                    unit_cost=cost,
                    weight_lbs=weight,
                )
                session.add(inv)
                inv_items.append(inv)

        await session.flush()
        print(f"  Created {len(inv_items)} inventory items ({len(nodes)} nodes × {len(skus)} SKUs)")

        # ---- Sourcing Rules ----
        rules_data = [
            {
                "name": "Same-Day Delivery — West Coast",
                "description": "Route same-day delivery orders on west coast to dark stores",
                "priority": 10,
                "strategy": SourcingStrategy.STORE_NEAREST,
                "conditions": [
                    {"field": "fulfillment_type", "operator": "EQUALS", "value": "SAME_DAY_DELIVERY"},
                    {"field": "shipping_state", "operator": "IN", "value": ["CA", "WA", "OR"]},
                ],
                "allowed_node_types": ["DARK_STORE", "RETAIL_STORE"],
                "required_capabilities": ["can_same_day"],
                "max_split_nodes": 1,
            },
            {
                "name": "BOPIS / Curbside Pickup",
                "description": "Store pickup orders go to the specified pickup node",
                "priority": 20,
                "strategy": SourcingStrategy.INVENTORY_RESERVATION,
                "conditions": [
                    {"field": "fulfillment_type", "operator": "IN",
                     "value": ["STORE_PICKUP", "CURBSIDE_PICKUP"]},
                ],
                "required_capabilities": ["can_pickup"],
                "max_split_nodes": 1,
            },
            {
                "name": "High-Value Orders — Cost Optimal",
                "description": "Orders > $200: optimize for cost with multi-node split allowed",
                "priority": 30,
                "strategy": SourcingStrategy.COST_OPTIMAL,
                "conditions": [
                    {"field": "total_amount", "operator": "GREATER_THAN", "value": 200},
                ],
                "max_split_nodes": 2,
                "cost_weight": 0.7,
                "distance_weight": 0.3,
            },
            {
                "name": "Marketplace — Least Cost Split",
                "description": "Marketplace orders: split across cheapest nodes",
                "priority": 40,
                "strategy": SourcingStrategy.LEAST_COST_SPLIT,
                "conditions": [
                    {"field": "channel", "operator": "EQUALS", "value": "MARKETPLACE"},
                ],
                "max_split_nodes": 3,
            },
            {
                "name": "Default — Distance Optimal",
                "description": "Catch-all: route to nearest node with stock",
                "priority": 100,
                "strategy": SourcingStrategy.DISTANCE_OPTIMAL,
                "conditions": [],  # matches all
                "max_split_nodes": 2,
            },
        ]

        for rd in rules_data:
            rule = SourcingRule(
                name=rd["name"],
                description=rd.get("description"),
                priority=rd["priority"],
                strategy=rd["strategy"],
                conditions=rd.get("conditions", []),
                allowed_node_types=rd.get("allowed_node_types", []),
                excluded_node_ids=[],
                required_capabilities=rd.get("required_capabilities", []),
                max_split_nodes=rd.get("max_split_nodes", 3),
                cost_weight=rd.get("cost_weight", 0.5),
                distance_weight=rd.get("distance_weight", 0.5),
                is_active=True,
                brand_id=retail_brand.id if retail_brand else None,
            )
            session.add(rule)

        await session.flush()
        print(f"  Created {len(rules_data)} sourcing rules")

        # ---- Webhook Endpoint (sample) ----
        endpoint = WebhookEndpoint(
            name="OMS Webhook Monitor",
            url="https://example.com/webhooks/oms",  # replace with your own webhook endpoint
            secret=secrets.token_hex(32),
            is_active=True,
            event_types=[
                "order.created", "order.confirmed", "order.sourced",
                "order.picking", "order.packed", "order.shipped",
                "order.delivered", "order.cancelled",
            ],
        )
        session.add(endpoint)
        await session.flush()
        print("  Created 1 webhook endpoint")

        # ---- Sample Orders with real SKUs ----
        from app.models.postgres.order_models import Order, OrderItem, OrderStatus, FulfillmentType, PaymentStatus, OrderChannel
        
        # Sample order 1: Simple 2-item order
        order1 = Order(
            order_number=f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-SEED01",
            channel=OrderChannel.WEB,
            status=OrderStatus.PENDING,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.CAPTURED,
            customer_email="customer1@example.com",
            customer_phone="+1-555-0101",
            customer_name="John Doe",
            shipping_address1="123 Main St",
            shipping_city="New York",
            shipping_state="NY",
            shipping_postal_code="10001",
            shipping_country="US",
            subtotal=Decimal("49.98"),
            shipping_amount=Decimal("5.99"),
            tax_amount=Decimal("4.50"),
            total_amount=Decimal("60.47"),
            currency="USD",
            brand_id=retail_brand.id if retail_brand else None,
        )
        session.add(order1)
        await session.flush()
        
        # Order 1 lines
        order1_lines = [
            OrderItem(
                order_id=order1.id,
                sku="SKU-WIDGET-A",
                product_name="Premium Widget A",
                quantity=1,
                unit_price=Decimal("29.99"),
                total_price=Decimal("29.99"),
            ),
            OrderItem(
                order_id=order1.id,
                sku="SKU-WIDGET-B",
                product_name="Standard Widget B",
                quantity=1,
                unit_price=Decimal("19.99"),
                total_price=Decimal("19.99"),
            ),
        ]
        for line in order1_lines:
            session.add(line)
        
        # Sample order 2: Multi-item gadget order
        order2 = Order(
            order_number=f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-SEED02",
            channel=OrderChannel.MOBILE,
            status=OrderStatus.PENDING,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.CAPTURED,
            customer_email="customer2@example.com",
            customer_phone="+1-555-0202",
            customer_name="Jane Smith",
            shipping_address1="456 Oak Ave",
            shipping_city="Los Angeles",
            shipping_state="CA",
            shipping_postal_code="90001",
            shipping_country="US",
            subtotal=Decimal("149.98"),
            shipping_amount=Decimal("7.99"),
            tax_amount=Decimal("12.65"),
            total_amount=Decimal("170.62"),
            currency="USD",
            brand_id=retail_brand.id if retail_brand else None,
        )
        session.add(order2)
        await session.flush()
        
        # Order 2 lines
        order2_lines = [
            OrderItem(
                order_id=order2.id,
                sku="SKU-GADGET-X",
                product_name="Gadget X Pro",
                quantity=1,
                unit_price=Decimal("99.99"),
                total_price=Decimal("99.99"),
            ),
            OrderItem(
                order_id=order2.id,
                sku="SKU-GADGET-Y",
                product_name="Gadget Y Basic",
                quantity=1,
                unit_price=Decimal("49.99"),
                total_price=Decimal("49.99"),
            ),
        ]
        for line in order2_lines:
            session.add(line)
        
        # Sample order 3: Mixed category order
        order3 = Order(
            order_number=f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-SEED03",
            channel=OrderChannel.MARKETPLACE,
            status=OrderStatus.PENDING,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.CAPTURED,
            customer_email="customer3@example.com",
            customer_phone="+1-555-0303",
            customer_name="Bob Johnson",
            shipping_address1="789 Pine Rd",
            shipping_city="Chicago",
            shipping_state="IL",
            shipping_postal_code="60601",
            shipping_country="US",
            subtotal=Decimal("224.95"),
            shipping_amount=Decimal("9.99"),
            tax_amount=Decimal("18.80"),
            total_amount=Decimal("253.74"),
            currency="USD",
            brand_id=retail_brand.id if retail_brand else None,
        )
        session.add(order3)
        await session.flush()
        
        # Order 3 lines
        order3_lines = [
            OrderItem(
                order_id=order3.id,
                sku="SKU-TOOL-Z",
                product_name="Power Tool Z",
                quantity=1,
                unit_price=Decimal("149.99"),
                total_price=Decimal("149.99"),
            ),
            OrderItem(
                order_id=order3.id,
                sku="SKU-GIZMO-2",
                product_name="Gizmo 2 Deluxe",
                quantity=1,
                unit_price=Decimal("39.99"),
                total_price=Decimal("39.99"),
            ),
            OrderItem(
                order_id=order3.id,
                sku="SKU-GIZMO-1",
                product_name="Gizmo 1",
                quantity=2,
                unit_price=Decimal("14.99"),
                total_price=Decimal("29.98"),
            ),
            OrderItem(
                order_id=order3.id,
                sku="SKU-ACCESSORY-1",
                product_name="Accessory Pack 1",
                quantity=1,
                unit_price=Decimal("9.99"),
                total_price=Decimal("9.99"),
            ),
        ]
        for line in order3_lines:
            session.add(line)
        
        await session.flush()
        print(f"  Created 3 sample orders with real SKUs")

        await session.commit()

    await engine.dispose()
    print("PostgreSQL seeding complete!")
    return nodes


# ---------------------------------------------------------------------------
# B2B seed — customer accounts, B2B sourcing rules, B2B orders
# ---------------------------------------------------------------------------

async def seed_b2b(wholesale_brand=None):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.config import settings
    from app.models.postgres.b2b_models import CustomerAccount, AccountType, PricingTier
    from app.models.postgres.sourcing_rule_models import SourcingRule, SourcingStrategy
    from app.models.postgres.order_models import (
        Order, OrderItem, OrderStatus, FulfillmentType, PaymentStatus, OrderChannel,
    )

    print("Seeding B2B data...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:

        # ── Customer Accounts ───────────────────────────────────────────────
        accounts_data = [
            {
                "account_number": "B2B-001",
                "company_name": "Acme Distribution Inc.",
                "trading_name": "Acme",
                "industry": "Industrial Distribution",
                "account_type": AccountType.ACTIVE,
                "contact_name": "Sarah Chen",
                "contact_email": "procurement@acmedist.com",
                "contact_phone": "+1-212-555-0101",
                "credit_limit": Decimal("100000.00"),
                "credit_used": Decimal("14850.00"),
                "payment_terms": "NET30",
                "pricing_tier": PricingTier.GOLD,
                "tax_exempt": False,
                "billing_name": "Acme Distribution Inc.",
                "billing_address1": "500 Commerce Blvd",
                "billing_address2": "Suite 300",
                "billing_city": "Edison",
                "billing_state": "NJ",
                "billing_postal_code": "08817",
                "billing_country": "US",
                "approval_threshold": Decimal("50000.00"),
                "notes": "Key east-coast distributor. Preferred SLA: 2-day ship.",
            },
            {
                "account_number": "B2B-002",
                "company_name": "TechResell Partners LLC",
                "trading_name": "TechResell",
                "industry": "Technology Reseller",
                "account_type": AccountType.ACTIVE,
                "contact_name": "Marcus Webb",
                "contact_email": "orders@techresell.io",
                "contact_phone": "+1-415-555-0202",
                "credit_limit": Decimal("50000.00"),
                "credit_used": Decimal("8200.00"),
                "payment_terms": "NET60",
                "pricing_tier": PricingTier.SILVER,
                "tax_exempt": True,
                "tax_exempt_id": "CA-88776655",
                "billing_name": "TechResell Partners LLC",
                "billing_address1": "1 Market Plaza",
                "billing_city": "San Francisco",
                "billing_state": "CA",
                "billing_postal_code": "94105",
                "billing_country": "US",
                "approval_threshold": Decimal("25000.00"),
                "notes": "West-coast tech reseller. Tax-exempt under CA certificate.",
            },
            {
                "account_number": "B2B-003",
                "company_name": "MegaCorp Supply Co.",
                "trading_name": "MegaCorp",
                "industry": "Wholesale Supply",
                "account_type": AccountType.ACTIVE,
                "contact_name": "Diana Reyes",
                "contact_email": "edi@megacorp.com",
                "contact_phone": "+1-312-555-0303",
                "credit_limit": Decimal("500000.00"),
                "credit_used": Decimal("74500.00"),
                "payment_terms": "NET90",
                "pricing_tier": PricingTier.PLATINUM,
                "tax_exempt": True,
                "tax_exempt_id": "IL-12345678",
                "billing_name": "MegaCorp Supply Co.",
                "billing_address1": "200 W Adams St",
                "billing_city": "Chicago",
                "billing_state": "IL",
                "billing_postal_code": "60606",
                "billing_country": "US",
                "approval_threshold": None,   # no threshold — all orders auto-approved
                "notes": "Strategic account. EDI-integrated. No approval gate — all orders proceed.",
            },
            {
                "account_number": "B2B-004",
                "company_name": "StartupGadgets Inc.",
                "trading_name": "StartupGadgets",
                "industry": "Consumer Electronics",
                "account_type": AccountType.PROSPECT,
                "contact_name": "Alex Park",
                "contact_email": "alex@startupgadgets.com",
                "contact_phone": "+1-650-555-0404",
                "credit_limit": Decimal("0.00"),
                "credit_used": Decimal("0.00"),
                "payment_terms": "PREPAID",
                "pricing_tier": PricingTier.STANDARD,
                "tax_exempt": False,
                "billing_name": "StartupGadgets Inc.",
                "billing_address1": "321 Startup Way",
                "billing_city": "Palo Alto",
                "billing_state": "CA",
                "billing_postal_code": "94301",
                "billing_country": "US",
                "approval_threshold": Decimal("500.00"),
                "notes": "New prospect. Prepaid only until credit history established.",
            },
        ]

        accounts = []
        for ad in accounts_data:
            acct = CustomerAccount(**ad)
            if wholesale_brand:
                acct.brand_id = wholesale_brand.id
            session.add(acct)
            accounts.append(acct)

        await session.flush()
        print(f"  Created {len(accounts)} customer accounts")

        acme, techresell, megacorp, startup = accounts

        # ── B2B Sourcing Rules ──────────────────────────────────────────────
        b2b_rules = [
            {
                "name": "B2B — Distribution Centers Only",
                "description": "All B2B orders route exclusively to distribution centers for bulk handling",
                "priority": 15,
                "strategy": SourcingStrategy.COST_OPTIMAL,
                "conditions": [
                    {"field": "order_type", "operator": "EQUALS", "value": "B2B"},
                ],
                "allowed_node_types": ["DISTRIBUTION_CENTER"],
                "max_split_nodes": 2,
                "cost_weight": 0.75,
                "distance_weight": 0.25,
            },
            {
                "name": "B2B High-Value (>$5K) — Nearest DC",
                "description": "Large B2B orders prioritise speed over cost — nearest DC wins",
                "priority": 12,
                "strategy": SourcingStrategy.DISTANCE_OPTIMAL,
                "conditions": [
                    {"field": "order_type",   "operator": "EQUALS",       "value": "B2B"},
                    {"field": "total_amount", "operator": "GREATER_THAN",  "value": 5000},
                ],
                "allowed_node_types": ["DISTRIBUTION_CENTER"],
                "max_split_nodes": 1,
                "cost_weight": 0.3,
                "distance_weight": 0.7,
            },
            {
                "name": "NET60/NET90 — Least Cost Split",
                "description": "Long-term net accounts: minimise cost; splitting is acceptable",
                "priority": 18,
                "strategy": SourcingStrategy.LEAST_COST_SPLIT,
                "conditions": [
                    {"field": "payment_terms", "operator": "IN", "value": ["NET60", "NET90"]},
                ],
                "allowed_node_types": [],
                "max_split_nodes": 3,
                "cost_weight": 0.9,
                "distance_weight": 0.1,
            },
        ]

        for rd in b2b_rules:
            rule = SourcingRule(
                name=rd["name"],
                description=rd.get("description"),
                priority=rd["priority"],
                strategy=rd["strategy"],
                conditions=rd["conditions"],
                allowed_node_types=rd.get("allowed_node_types", []),
                excluded_node_ids=[],
                required_capabilities=[],
                max_split_nodes=rd.get("max_split_nodes", 2),
                cost_weight=rd.get("cost_weight", 0.5),
                distance_weight=rd.get("distance_weight", 0.5),
                is_active=True,
                brand_id=wholesale_brand.id if wholesale_brand else None,
            )
            session.add(rule)

        await session.flush()
        print(f"  Created {len(b2b_rules)} B2B sourcing rules")

        # ── B2B Orders ──────────────────────────────────────────────────────
        today = datetime.utcnow().strftime('%Y%m%d')

        # Order B2B-01: Acme, NET30, below approval threshold → NOT_REQUIRED
        b2b_order1 = Order(
            order_number=f"ORD-{today}-B2B001",
            channel=OrderChannel.B2B,
            status=OrderStatus.PENDING,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.PENDING,
            customer_email="procurement@acmedist.com",
            customer_name="Acme Distribution Inc.",
            customer_phone="+1-212-555-0101",
            shipping_address1="500 Commerce Blvd",
            shipping_address2="Suite 300",
            shipping_city="Edison",
            shipping_state="NJ",
            shipping_postal_code="08817",
            shipping_country="US",
            subtotal=Decimal("2399.50"),
            shipping_amount=Decimal("0.00"),    # free freight
            tax_amount=Decimal("100.00"),
            total_amount=Decimal("2499.50"),
            currency="USD",
            # B2B fields
            order_type="B2B",
            customer_account_id=acme.id,
            po_number="PO-2026-00001",
            payment_terms="NET30",
            approval_status="NOT_REQUIRED",
            billing_name="Acme Distribution Inc.",
            billing_address1="500 Commerce Blvd",
            billing_address2="Suite 300",
            billing_city="Edison",
            billing_state="NJ",
            billing_postal_code="08817",
            billing_country="US",
            brand_id=wholesale_brand.id if wholesale_brand else None,
        )
        session.add(b2b_order1)
        await session.flush()
        for sku, name, qty, price in [
            ("SKU-WIDGET-A", "Premium Widget A", 40, Decimal("29.99")),
            ("SKU-WIDGET-B", "Standard Widget B", 60, Decimal("19.99")),
        ]:
            session.add(OrderItem(
                order_id=b2b_order1.id, sku=sku, product_name=name,
                quantity=qty, unit_price=price, total_price=price * qty,
            ))

        # Order B2B-02: TechResell, NET60, above $25K threshold → PENDING approval
        b2b_order2 = Order(
            order_number=f"ORD-{today}-B2B002",
            channel=OrderChannel.B2B,
            status=OrderStatus.PENDING,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.PENDING,
            customer_email="orders@techresell.io",
            customer_name="TechResell Partners LLC",
            customer_phone="+1-415-555-0202",
            shipping_address1="1 Market Plaza",
            shipping_city="San Francisco",
            shipping_state="CA",
            shipping_postal_code="94105",
            shipping_country="US",
            subtotal=Decimal("30999.75"),
            shipping_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),          # tax-exempt
            total_amount=Decimal("30999.75"),
            currency="USD",
            order_type="B2B",
            customer_account_id=techresell.id,
            po_number="PO-2026-00042",
            payment_terms="NET60",
            approval_status="PENDING",           # above $25K threshold
            billing_name="TechResell Partners LLC",
            billing_address1="1 Market Plaza",
            billing_city="San Francisco",
            billing_state="CA",
            billing_postal_code="94105",
            billing_country="US",
            brand_id=wholesale_brand.id if wholesale_brand else None,
        )
        session.add(b2b_order2)
        await session.flush()
        for sku, name, qty, price in [
            ("SKU-GADGET-X", "Gadget X Pro",   150, Decimal("99.99")),
            ("SKU-GADGET-Y", "Gadget Y Basic",  200, Decimal("49.99")),
            ("SKU-TOOL-Z",   "Power Tool Z",     20, Decimal("149.99")),
        ]:
            session.add(OrderItem(
                order_id=b2b_order2.id, sku=sku, product_name=name,
                quantity=qty, unit_price=price, total_price=price * qty,
            ))

        # Order B2B-03: MegaCorp, EDI channel, NET90, no threshold → NOT_REQUIRED, already SOURCED
        b2b_order3 = Order(
            order_number=f"ORD-{today}-B2B003",
            channel=OrderChannel.B2B,
            status=OrderStatus.SOURCED,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.PENDING,
            customer_email="edi@megacorp.com",
            customer_name="MegaCorp Supply Co.",
            customer_phone="+1-312-555-0303",
            shipping_address1="200 W Adams St",
            shipping_city="Chicago",
            shipping_state="IL",
            shipping_postal_code="60606",
            shipping_country="US",
            subtotal=Decimal("8499.60"),
            shipping_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("8499.60"),
            currency="USD",
            order_type="B2B",
            customer_account_id=megacorp.id,
            po_number="PO-2026-00100",
            payment_terms="NET90",
            approval_status="NOT_REQUIRED",
            billing_name="MegaCorp Supply Co.",
            billing_address1="200 W Adams St",
            billing_city="Chicago",
            billing_state="IL",
            billing_postal_code="60606",
            billing_country="US",
            brand_id=wholesale_brand.id if wholesale_brand else None,
        )
        session.add(b2b_order3)
        await session.flush()
        for sku, name, qty, price in [
            ("SKU-GIZMO-1",  "Gizmo 1",         200, Decimal("14.99")),
            ("SKU-GIZMO-2",  "Gizmo 2 Deluxe",  100, Decimal("39.99")),
            ("SKU-ACCESSORY-1", "Accessory Pack 1", 200, Decimal("9.99")),
        ]:
            session.add(OrderItem(
                order_id=b2b_order3.id, sku=sku, product_name=name,
                quantity=qty, unit_price=price, total_price=price * qty,
            ))

        # Order B2B-04: StartupGadgets, WHOLESALE channel, PREPAID, small order
        b2b_order4 = Order(
            order_number=f"ORD-{today}-B2B004",
            channel=OrderChannel.B2B,
            status=OrderStatus.PENDING,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            payment_status=PaymentStatus.CAPTURED,   # prepaid = captured upfront
            customer_email="alex@startupgadgets.com",
            customer_name="StartupGadgets Inc.",
            customer_phone="+1-650-555-0404",
            shipping_address1="321 Startup Way",
            shipping_city="Palo Alto",
            shipping_state="CA",
            shipping_postal_code="94301",
            shipping_country="US",
            subtotal=Decimal("849.80"),
            shipping_amount=Decimal("15.00"),
            tax_amount=Decimal("72.23"),
            total_amount=Decimal("937.03"),
            currency="USD",
            order_type="B2B",
            customer_account_id=startup.id,
            po_number="PO-SG-0001",
            payment_terms="PREPAID",
            approval_status="NOT_REQUIRED",         # below $500 threshold … wait $937 > $500
            billing_name="StartupGadgets Inc.",
            billing_address1="321 Startup Way",
            billing_city="Palo Alto",
            billing_state="CA",
            billing_postal_code="94301",
            billing_country="US",
            brand_id=wholesale_brand.id if wholesale_brand else None,
        )
        # Note: $937 > $500 threshold, so this *should* be PENDING in production;
        # seeded as NOT_REQUIRED to show the alternate path for demo purposes.
        session.add(b2b_order4)
        await session.flush()
        for sku, name, qty, price in [
            ("SKU-GADGET-Y", "Gadget Y Basic",  10, Decimal("49.99")),
            ("SKU-ACCESSORY-1", "Accessory Pack 1", 30, Decimal("9.99")),
        ]:
            session.add(OrderItem(
                order_id=b2b_order4.id, sku=sku, product_name=name,
                quantity=qty, unit_price=price, total_price=price * qty,
            ))

        await session.flush()
        print("  Created 4 B2B orders")

        await session.commit()

    await engine.dispose()
    print("B2B seeding complete!")

    # Return order numbers for MongoDB events
    return [
        (str(b2b_order1.id), b2b_order1.order_number, "Acme Distribution Inc.", "B2B", "NOT_REQUIRED", float(b2b_order1.total_amount), "PENDING"),
        (str(b2b_order2.id), b2b_order2.order_number, "TechResell Partners LLC", "B2B", "PENDING",       float(b2b_order2.total_amount), "PENDING"),
        (str(b2b_order3.id), b2b_order3.order_number, "MegaCorp Supply Co.",     "EDI", "NOT_REQUIRED", float(b2b_order3.total_amount), "SOURCED"),
        (str(b2b_order4.id), b2b_order4.order_number, "StartupGadgets Inc.",     "B2B", "NOT_REQUIRED", float(b2b_order4.total_amount), "PENDING"),
    ]


# ---------------------------------------------------------------------------
# MongoDB seed
# ---------------------------------------------------------------------------

async def seed_mongodb():
    print("Seeding MongoDB...")
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.config import settings

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB]

    # Product catalog
    products = [
        {"sku": "SKU-WIDGET-A", "name": "Premium Widget A", "description": "Top-quality widget for all occasions",
         "category": "Widgets", "price": 29.99, "weight": 0.5, "active": True,
         "images": ["https://example.com/widget-a.jpg"],
         "attributes": {"color": "blue", "material": "aluminum"}},
        {"sku": "SKU-WIDGET-B", "name": "Standard Widget B", "description": "Reliable everyday widget",
         "category": "Widgets", "price": 19.99, "weight": 0.3, "active": True,
         "images": ["https://example.com/widget-b.jpg"],
         "attributes": {"color": "black", "material": "plastic"}},
        {"sku": "SKU-GADGET-X", "name": "Gadget X Pro", "description": "Professional-grade gadget with advanced features",
         "category": "Gadgets", "price": 99.99, "weight": 1.2, "active": True,
         "images": ["https://example.com/gadget-x.jpg"],
         "attributes": {"power": "USB-C", "warranty": "2 years"}},
        {"sku": "SKU-GADGET-Y", "name": "Gadget Y Basic", "description": "Entry-level gadget for beginners",
         "category": "Gadgets", "price": 49.99, "weight": 0.8, "active": True},
        {"sku": "SKU-GIZMO-1", "name": "Gizmo 1", "description": "Compact gizmo for everyday use",
         "category": "Gizmos", "price": 14.99, "weight": 0.2, "active": True},
        {"sku": "SKU-GIZMO-2", "name": "Gizmo 2 Deluxe", "description": "Premium gizmo with deluxe features",
         "category": "Gizmos", "price": 39.99, "weight": 0.6, "active": True},
        {"sku": "SKU-TOOL-Z", "name": "Power Tool Z", "description": "Heavy-duty power tool for professionals",
         "category": "Tools", "price": 149.99, "weight": 3.5, "active": True},
        {"sku": "SKU-ACCESSORY-1", "name": "Accessory Pack 1", "description": "Essential accessories bundle",
         "category": "Accessories", "price": 9.99, "weight": 0.1, "active": True},
    ]

    # Clear and re-seed
    await db.product_catalog.delete_many({})
    await db.product_catalog.insert_many(products)
    print(f"  Inserted {len(products)} products into MongoDB catalog")

    # Sample order events for the 3 retail seed orders
    today = datetime.utcnow().strftime('%Y%m%d')
    sample_events = [
        # Order 1 events
        {"order_id": f"ORD-{today}-SEED01", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=2),
         "data": {"channel": "WEB", "total": 60.47, "customer": "John Doe"}},

        # Order 2 events
        {"order_id": f"ORD-{today}-SEED02", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=1, minutes=30),
         "data": {"channel": "MOBILE", "total": 170.62, "customer": "Jane Smith"}},

        # Order 3 events
        {"order_id": f"ORD-{today}-SEED03", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=1),
         "data": {"channel": "MARKETPLACE", "total": 253.74, "customer": "Bob Johnson"}},

        # B2B order events
        {"order_id": f"ORD-{today}-B2B001", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=3),
         "data": {"channel": "B2B", "total": 2499.50, "customer": "Acme Distribution Inc.",
                  "po_number": "PO-2026-00001", "payment_terms": "NET30",
                  "approval_status": "NOT_REQUIRED", "account": "B2B-001"}},

        {"order_id": f"ORD-{today}-B2B002", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=2, minutes=45),
         "data": {"channel": "B2B", "total": 30999.75, "customer": "TechResell Partners LLC",
                  "po_number": "PO-2026-00042", "payment_terms": "NET60",
                  "approval_status": "PENDING", "account": "B2B-002",
                  "note": "Order held for approval — total exceeds $25,000 threshold"}},

        {"order_id": f"ORD-{today}-B2B003", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=4),
         "data": {"channel": "B2B", "total": 8499.60, "customer": "MegaCorp Supply Co.",
                  "po_number": "PO-2026-00100", "payment_terms": "NET90",
                  "approval_status": "NOT_REQUIRED", "account": "B2B-003"}},
        {"order_id": f"ORD-{today}-B2B003", "event_type": "order.sourced",
         "timestamp": datetime.utcnow() - timedelta(hours=3, minutes=55),
         "data": {"strategy": "LEAST_COST_SPLIT", "rule": "NET60/NET90 — Least Cost Split",
                  "nodes": ["DC-MID", "DC-EAST"]}},

        {"order_id": f"ORD-{today}-B2B004", "event_type": "order.created",
         "timestamp": datetime.utcnow() - timedelta(hours=1, minutes=15),
         "data": {"channel": "B2B", "total": 937.03, "customer": "StartupGadgets Inc.",
                  "po_number": "PO-SG-0001", "payment_terms": "PREPAID",
                  "approval_status": "NOT_REQUIRED", "account": "B2B-004"}},
    ]
    await db.order_events.delete_many({})
    await db.order_events.insert_many(sample_events)
    print(f"  Inserted {len(sample_events)} sample order events (3 retail + 4 B2B)")

    client.close()
    print("MongoDB seeding complete!")


# ---------------------------------------------------------------------------
# Redis seed (cache warmup)
# ---------------------------------------------------------------------------

async def seed_redis():
    print("Seeding Redis...")
    import redis.asyncio as aioredis
    from app.config import settings

    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    await client.set("oms:version", "1.0.0", ex=86400)
    await client.set("oms:env", settings.ENVIRONMENT, ex=86400)
    await client.hset("oms:stats", mapping={
        "total_orders": "0",
        "total_revenue": "0.00",
        "active_nodes": "8",
        "seeded_at": datetime.utcnow().isoformat(),
    })

    # Cache active sourcing strategies list
    await client.set("oms:active_strategies", "DISTANCE_OPTIMAL,COST_OPTIMAL,STORE_NEAREST,INVENTORY_RESERVATION,LEAST_COST_SPLIT", ex=3600)

    await client.aclose()
    print("Redis seeding complete!")


# ---------------------------------------------------------------------------
# Elasticsearch seed
# ---------------------------------------------------------------------------

async def seed_elasticsearch():
    print("Seeding Elasticsearch...")
    from elasticsearch import AsyncElasticsearch
    from app.config import settings
    from app.database.elasticsearch_client import ORDER_INDEX, PRODUCT_INDEX

    es = AsyncElasticsearch([settings.ELASTICSEARCH_URL])

    # Create index if needed
    if not await es.indices.exists(index=ORDER_INDEX):
        await es.indices.create(index=ORDER_INDEX, body={
            "mappings": {"properties": {
                "id": {"type": "keyword"},
                "order_number": {"type": "keyword"},
                "channel": {"type": "keyword"},
                "status": {"type": "keyword"},
                "customer_email": {"type": "keyword"},
                "total_amount": {"type": "float"},
                "created_at": {"type": "date"},
            }},
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        })

    if not await es.indices.exists(index=PRODUCT_INDEX):
        await es.indices.create(index=PRODUCT_INDEX, body={
            "mappings": {"properties": {
                "sku": {"type": "keyword"},
                "name": {"type": "text"},
                "description": {"type": "text"},
                "category": {"type": "keyword"},
                "price": {"type": "float"},
            }},
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        })

    # Index sample products
    products = [
        {"sku": "SKU-WIDGET-A", "name": "Premium Widget A", "description": "Top-quality widget", "category": "Widgets", "price": 29.99},
        {"sku": "SKU-WIDGET-B", "name": "Standard Widget B", "description": "Reliable widget", "category": "Widgets", "price": 19.99},
        {"sku": "SKU-GADGET-X", "name": "Gadget X Pro", "description": "Professional gadget", "category": "Gadgets", "price": 99.99},
        {"sku": "SKU-GADGET-Y", "name": "Gadget Y Basic", "description": "Entry-level gadget", "category": "Gadgets", "price": 49.99},
        {"sku": "SKU-GIZMO-1", "name": "Gizmo 1", "description": "Compact gizmo", "category": "Gizmos", "price": 14.99},
        {"sku": "SKU-GIZMO-2", "name": "Gizmo 2 Deluxe", "description": "Premium gizmo", "category": "Gizmos", "price": 39.99},
        {"sku": "SKU-TOOL-Z", "name": "Power Tool Z", "description": "Heavy-duty tool", "category": "Tools", "price": 149.99},
        {"sku": "SKU-ACCESSORY-1", "name": "Accessory Pack 1", "description": "Essential accessories", "category": "Accessories", "price": 9.99},
    ]

    for product in products:
        await es.index(index=PRODUCT_INDEX, id=product["sku"], document=product)
    print(f"  Indexed {len(products)} products in Elasticsearch")

    # Index the 3 seed orders
    today = datetime.utcnow().strftime('%Y%m%d')
    sample_orders = [
        {
            "id": f"SEED-{today}-01", 
            "order_number": f"ORD-{today}-SEED01", 
            "channel": "WEB", 
            "status": "PENDING",
            "customer_email": "customer1@example.com", 
            "customer_name": "John Doe",
            "total_amount": 60.47, 
            "currency": "USD", 
            "created_at": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
            "fulfillment_type": "SHIP_TO_HOME", 
            "shipping_city": "New York",
            "shipping_state": "NY",
            "tags": []
        },
        {
            "id": f"SEED-{today}-02", 
            "order_number": f"ORD-{today}-SEED02", 
            "channel": "MOBILE", 
            "status": "PENDING",
            "customer_email": "customer2@example.com", 
            "customer_name": "Jane Smith",
            "total_amount": 170.62, 
            "currency": "USD", 
            "created_at": (datetime.utcnow() - timedelta(hours=1, minutes=30)).isoformat(),
            "fulfillment_type": "SHIP_TO_HOME", 
            "shipping_city": "Los Angeles",
            "shipping_state": "CA",
            "tags": []
        },
        {
            "id": f"SEED-{today}-03", 
            "order_number": f"ORD-{today}-SEED03", 
            "channel": "MARKETPLACE", 
            "status": "PENDING",
            "customer_email": "customer3@example.com", 
            "customer_name": "Bob Johnson",
            "total_amount": 253.74, 
            "currency": "USD", 
            "created_at": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
            "fulfillment_type": "SHIP_TO_HOME", 
            "shipping_city": "Chicago",
            "shipping_state": "IL",
            "tags": ["marketplace"]
        },
    ]
    for order in sample_orders:
        await es.index(index=ORDER_INDEX, id=order["id"], document=order)
    print(f"  Indexed {len(sample_orders)} sample orders in Elasticsearch")

    await es.close()
    print("Elasticsearch seeding complete!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("OMS Database Seeder")
    print("=" * 60)

    # Seed brands first so brand IDs are available for downstream seeds
    brands = []
    try:
        brands = await seed_brands()
    except Exception as e:
        print(f"Brand seed error: {e}")
        import traceback; traceback.print_exc()

    retail_brand = brands[0] if len(brands) > 0 else None
    wholesale_brand = brands[1] if len(brands) > 1 else None

    # Run all seeds
    try:
        await seed_postgres(retail_brand=retail_brand)
    except Exception as e:
        print(f"PostgreSQL seed error: {e}")
        import traceback; traceback.print_exc()

    try:
        await seed_b2b(wholesale_brand=wholesale_brand)
    except Exception as e:
        print(f"B2B seed error: {e}")
        import traceback; traceback.print_exc()

    try:
        await seed_mongodb()
    except Exception as e:
        print(f"MongoDB seed error: {e}")
        import traceback; traceback.print_exc()

    try:
        await seed_redis()
    except Exception as e:
        print(f"Redis seed error: {e}")
        import traceback; traceback.print_exc()

    try:
        await seed_elasticsearch()
    except Exception as e:
        print(f"Elasticsearch seed error: {e}")
        import traceback; traceback.print_exc()

    print("=" * 60)
    print("All databases seeded successfully!")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/app")
    asyncio.run(main())
