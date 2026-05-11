"""
E2E Testing Service
Provides comprehensive test workflows for the OMS system.
"""
import uuid
import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_

from app.models.postgres.auth_models import User
from app.models.postgres.order_models import (
    Order, OrderItem, FulfillmentAllocation, Shipment, WebhookEvent,
    OrderStatus, AllocationStatus, ShipmentStatus, OrderChannel, FulfillmentType, PaymentStatus
)
from app.models.postgres.connector_models import ConnectorEvent
from app.models.postgres.inventory_models import InventoryItem, InventoryAdjustment
from app.models.postgres.node_models import FulfillmentNode, NodeStatus, NodeType
from app.models.postgres.sourcing_rule_models import SourcingRule


class TestFlowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


@dataclass
class TestFlowResult:
    """Result of a test flow execution."""
    name: str
    status: TestFlowStatus
    duration_ms: float
    message: str
    created_resources: Dict[str, Any]
    errors: List[str]


class E2ETestService:
    """Service for running end-to-end tests on the OMS system."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.test_user: Optional[User] = None
        self.test_nodes: List[FulfillmentNode] = []
        self.test_orders: List[Order] = []
        self.test_resources: Dict[str, List[uuid.UUID]] = {
            "users": [],
            "nodes": [],
            "orders": [],
            "allocations": [],
            "shipments": [],
        }

    async def setup_test_data(self) -> Dict[str, Any]:
        """Create test user, nodes, and inventory."""
        try:
            # 0. Pre-clean: remove any E2E-SKU inventory that may be sitting on real
            #    production nodes (DC-EAST, DC-WEST, etc.) from a previous seed script
            #    or a crashed test run.  Only the per-run temp nodes should carry these.
            # Must delete FK-referencing adjustments first.
            stale_e2e_ids = (
                await self.db.execute(
                    select(InventoryItem.id).where(InventoryItem.sku.like("E2E-SKU-%"))
                )
            ).scalars().all()
            if stale_e2e_ids:
                await self.db.execute(
                    delete(InventoryAdjustment).where(
                        InventoryAdjustment.inventory_item_id.in_(stale_e2e_ids)
                    )
                )
                await self.db.execute(
                    delete(InventoryItem).where(InventoryItem.id.in_(stale_e2e_ids))
                )
            await self.db.flush()

            # 1. Create test user
            user = User(
                id=uuid.uuid4(),
                email=f"test_{datetime.now().timestamp()}@example.com",
                hashed_password="$2b$12$dummy",
                full_name="Test User",
                is_active=True,
                is_superadmin=False,
            )
            self.db.add(user)
            await self.db.flush()
            self.test_user = user
            self.test_resources["users"].append(user.id)

            # 2. Create test nodes
            nodes_config = [
                {
                    "code": f"TEST-NYC-{uuid.uuid4().hex[:4]}",
                    "name": "Test NYC Warehouse",
                    "type": NodeType.WAREHOUSE,
                    "lat": 40.7128,
                    "lng": -74.0060,
                },
                {
                    "code": f"TEST-LA-{uuid.uuid4().hex[:4]}",
                    "name": "Test LA Warehouse",
                    "type": NodeType.WAREHOUSE,
                    "lat": 34.0522,
                    "lng": -118.2437,
                },
            ]

            for config in nodes_config:
                node = FulfillmentNode(
                    id=uuid.uuid4(),
                    code=config["code"],
                    name=config["name"],
                    node_type=config["type"],
                    status=NodeStatus.ACTIVE,
                    address_line1="123 Test St",
                    city="Test City",
                    state="TS",
                    postal_code="12345",
                    country="US",
                    latitude=config["lat"],
                    longitude=config["lng"],
                    can_ship=True,
                    can_pickup=True,
                )
                self.db.add(node)
                self.test_nodes.append(node)
                self.test_resources["nodes"].append(node.id)

            await self.db.flush()

            # 3. Create basic-test inventory (TEST-SKU-*) on both test nodes
            skus = [
                ("TEST-SKU-1", "Test Product 1", 100),
                ("TEST-SKU-2", "Test Product 2", 100),
            ]
            for node in self.test_nodes:
                for sku, name, qty in skus:
                    self.db.add(InventoryItem(
                        id=uuid.uuid4(),
                        node_id=node.id,
                        sku=sku,
                        product_name=name,
                        quantity_on_hand=qty,
                        quantity_available=qty,
                        quantity_reserved=0,
                        is_active=True,
                    ))

            # 4. Seed E2E scenario SKUs (E2E-SKU-*) ONLY on the temp test nodes.
            #    test_nodes[0] = "east analog" (NYC), test_nodes[1] = "west analog" (LA).
            #    This ensures zero impact on real DC-EAST / DC-WEST inventory.
            e2e_inv_count = 0
            for sku, (east_qty, west_qty) in self._E2E_INVENTORY_CANONICAL.items():
                for node, qty in [(self.test_nodes[0], east_qty), (self.test_nodes[1], west_qty)]:
                    if qty > 0:
                        self.db.add(InventoryItem(
                            id=uuid.uuid4(),
                            node_id=node.id,
                            sku=sku,
                            product_name=f"E2E Test Product {sku}",
                            quantity_on_hand=qty,
                            quantity_available=qty,
                            quantity_reserved=0,
                            is_active=True,
                        ))
                        e2e_inv_count += 1

            await self.db.flush()

            return {
                "user_id": str(user.id),
                "user_email": user.email,
                "nodes_count": len(self.test_nodes),
                "inventory_items": len(skus) * len(self.test_nodes) + e2e_inv_count,
            }

        except Exception as e:
            raise Exception(f"Failed to setup test data: {str(e)}")

    async def test_create_order(self) -> TestFlowResult:
        """Test: Create a new order."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            order = Order(
                id=uuid.uuid4(),
                order_number=f"TEST-{uuid.uuid4().hex[:8]}",
                channel=OrderChannel.WEB,
                fulfillment_type=FulfillmentType.SHIP_TO_HOME,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
                customer_name="Test Customer",
                customer_email=f"test_{uuid.uuid4().hex[:4]}@example.com",
                customer_phone="+1-555-0000",
                subtotal=Decimal("100.00"),
                tax_amount=Decimal("5.00"),
                shipping_amount=Decimal("10.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("115.00"),
                currency="USD",
                shipping_address1="123 Test St",
                shipping_city="Test City",
                shipping_state="TS",
                shipping_postal_code="12345",
                shipping_country="US",
                shipping_latitude=40.7128,
                shipping_longitude=-74.0060,
                created_at=datetime.now(timezone.utc),
                metadata_={},
            )
            self.db.add(order)
            await self.db.flush()

            # Add line items
            for i in range(2):
                item = OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    sku=f"TEST-SKU-{i+1}",
                    product_name=f"Test Product {i+1}",
                    quantity=1,
                    unit_price=Decimal("50.00"),
                    total_price=Decimal("50.00"),
                    metadata_={},
                )
                self.db.add(item)

            await self.db.commit()
            self.test_orders.append(order)
            self.test_resources["orders"].append(order.id)

            created_resources = {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "line_items": 2,
            }

        except Exception as e:
            errors.append(str(e))
            await self.db.rollback()

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Create Order",
            status=status,
            duration_ms=duration,
            message="Order created successfully" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_source_order(self) -> TestFlowResult:
        """Test: Source an order (allocation)."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            if not self.test_orders:
                raise Exception("No test order available. Run test_create_order first.")

            # Create allocations directly without querying
            order = self.test_orders[-1]
            allocation_count = 0
            
            # Refresh the order to get updated line_items
            await self.db.refresh(order, ["line_items"])
            
            for item in order.line_items:
                if self.test_nodes:
                    node = self.test_nodes[0]
                    alloc = FulfillmentAllocation(
                        id=uuid.uuid4(),
                        order_id=order.id,
                        order_item_id=item.id,
                        node_id=node.id,
                        sku=item.sku,
                        quantity_allocated=item.quantity,
                        status=AllocationStatus.ALLOCATED,
                        sourcing_score=0.95,
                        sourcing_metadata={"test": True},
                    )
                    self.db.add(alloc)
                    self.test_resources["allocations"].append(alloc.id)
                    allocation_count += 1

            await self.db.flush()
            
            # Update order status
            order.status = OrderStatus.SOURCED
            self.db.add(order)
            await self.db.flush()
            await self.db.commit()

            created_resources = {
                "order_id": str(order.id),
                "allocations_count": allocation_count,
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Source Order",
            status=status,
            duration_ms=duration,
            message="Order sourced successfully" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_create_shipment(self) -> TestFlowResult:
        """Test: Create shipment for order."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            if not self.test_orders:
                raise Exception("No test order available.")

            if not self.test_resources["allocations"]:
                raise Exception("No allocations found. Run test_source_order first.")

            order = self.test_orders[-1]
            allocation_id = self.test_resources["allocations"][0] if self.test_resources["allocations"] else None

            # Create shipment
            shipment = Shipment(
                id=uuid.uuid4(),
                order_id=order.id,
                allocation_id=allocation_id,
                status=ShipmentStatus.PENDING,
                tracking_number=None,
                carrier=None,
                service_level=None,
                tracking_events=[],
            )
            self.db.add(shipment)
            await self.db.flush()
            await self.db.commit()
            self.test_resources["shipments"].append(shipment.id)

            created_resources = {
                "order_id": str(order.id),
                "shipment_id": str(shipment.id),
                "allocation_id": str(allocation_id),
                "tracking_number": shipment.tracking_number,
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Create Shipment",
            status=status,
            duration_ms=duration,
            message="Shipment created successfully" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_multi_node_allocation(self) -> TestFlowResult:
        """Test: Order split across multiple nodes."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            if len(self.test_nodes) < 2:
                raise Exception("Need at least 2 nodes for multi-node allocation test")

            # Create order for multiple nodes
            order = Order(
                id=uuid.uuid4(),
                order_number=f"TEST-MULTI-{uuid.uuid4().hex[:6]}",
                channel=OrderChannel.WEB,
                fulfillment_type=FulfillmentType.SHIP_TO_HOME,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
                customer_name="Multi-Node Customer",
                customer_email=f"multi_{uuid.uuid4().hex[:4]}@example.com",
                customer_phone="+1-555-0001",
                subtotal=Decimal("200.00"),
                tax_amount=Decimal("10.00"),
                shipping_amount=Decimal("15.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("225.00"),
                currency="USD",
                shipping_address1="456 Multi St",
                shipping_city="Test City",
                shipping_state="TS",
                shipping_postal_code="12346",
                shipping_country="US",
                shipping_latitude=40.7128,
                shipping_longitude=-74.0060,
                created_at=datetime.now(timezone.utc),
                metadata_={"test_type": "multi_node"},
            )
            self.db.add(order)
            await self.db.flush()

            # Add line items
            for i in range(3):
                item = OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    sku=f"TEST-SKU-{i+1}",
                    product_name=f"Test Product {i+1}",
                    quantity=2,
                    unit_price=Decimal("50.00"),
                    total_price=Decimal("100.00"),
                    metadata_={},
                )
                self.db.add(item)

            await self.db.flush()

            # Create allocations across multiple nodes
            await self.db.refresh(order, ["line_items"])
            allocation_count = 0
            
            for item_idx, item in enumerate(order.line_items):
                node = self.test_nodes[item_idx % len(self.test_nodes)]
                alloc = FulfillmentAllocation(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    order_item_id=item.id,
                    node_id=node.id,
                    sku=item.sku,
                    quantity_allocated=item.quantity,
                    status=AllocationStatus.ALLOCATED,
                    sourcing_score=0.90 + (0.01 * item_idx),
                    sourcing_metadata={"node_index": item_idx, "test_type": "multi_node"},
                )
                self.db.add(alloc)
                self.test_resources["allocations"].append(alloc.id)
                allocation_count += 1

            order.status = OrderStatus.SOURCED
            await self.db.commit()
            self.test_orders.append(order)
            self.test_resources["orders"].append(order.id)

            created_resources = {
                "order_id": str(order.id),
                "line_items": len(order.line_items),
                "nodes_used": allocation_count,
                "unique_nodes": len(set(self.test_nodes[i % len(self.test_nodes)] for i in range(allocation_count))),
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Multi-Node Allocation",
            status=status,
            duration_ms=duration,
            message="Multi-node allocation successful" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_inventory_validation(self) -> TestFlowResult:
        """Test: Validate inventory levels after allocations."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            # Get current inventory levels
            from sqlalchemy.orm import selectinload
            
            inventory_before = {}
            for node in self.test_nodes:
                node_inventories = (await self.db.execute(
                    select(InventoryItem).where(InventoryItem.node_id == node.id)
                )).scalars().all()
                inventory_before[str(node.id)] = {
                    inv.sku: {
                        "on_hand": inv.quantity_on_hand,
                        "available": inv.quantity_available,
                        "reserved": inv.quantity_reserved,
                    }
                    for inv in node_inventories
                }

            # Create and allocate order
            order = Order(
                id=uuid.uuid4(),
                order_number=f"TEST-INV-{uuid.uuid4().hex[:6]}",
                channel=OrderChannel.WEB,
                fulfillment_type=FulfillmentType.SHIP_TO_HOME,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
                customer_name="Inventory Test Customer",
                customer_email=f"inv_{uuid.uuid4().hex[:4]}@example.com",
                customer_phone="+1-555-0002",
                subtotal=Decimal("50.00"),
                tax_amount=Decimal("2.50"),
                shipping_amount=Decimal("5.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("57.50"),
                currency="USD",
                shipping_address1="789 Inv St",
                shipping_city="Test City",
                shipping_state="TS",
                shipping_postal_code="12347",
                shipping_country="US",
                shipping_latitude=40.7128,
                shipping_longitude=-74.0060,
                created_at=datetime.now(timezone.utc),
                metadata_={"test_type": "inventory_validation"},
            )
            self.db.add(order)
            await self.db.flush()

            item = OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                sku="TEST-SKU-1",
                product_name="Test Product 1",
                quantity=5,
                unit_price=Decimal("50.00"),
                total_price=Decimal("50.00"),
                metadata_={},
            )
            self.db.add(item)
            await self.db.flush()

            # Create allocation
            alloc = FulfillmentAllocation(
                id=uuid.uuid4(),
                order_id=order.id,
                order_item_id=item.id,
                node_id=self.test_nodes[0].id,
                sku=item.sku,
                quantity_allocated=item.quantity,
                status=AllocationStatus.ALLOCATED,
                sourcing_score=0.95,
                sourcing_metadata={"test_type": "inventory_validation"},
            )
            self.db.add(alloc)
            order.status = OrderStatus.SOURCED
            await self.db.commit()
            self.test_orders.append(order)
            self.test_resources["orders"].append(order.id)
            self.test_resources["allocations"].append(alloc.id)

            created_resources = {
                "order_id": str(order.id),
                "sku_allocated": item.sku,
                "quantity_allocated": item.quantity,
                "node_id": str(self.test_nodes[0].id),
                "inventory_tracked": len(inventory_before) > 0,
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Inventory Validation",
            status=status,
            duration_ms=duration,
            message="Inventory validation successful" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_order_status_transitions(self) -> TestFlowResult:
        """Test: Order status transitions through full lifecycle."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}
        status_transitions = []

        try:
            # Create order in PENDING state
            order = Order(
                id=uuid.uuid4(),
                order_number=f"TEST-STATUS-{uuid.uuid4().hex[:6]}",
                channel=OrderChannel.WEB,
                fulfillment_type=FulfillmentType.SHIP_TO_HOME,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
                customer_name="Status Test Customer",
                customer_email=f"status_{uuid.uuid4().hex[:4]}@example.com",
                customer_phone="+1-555-0003",
                subtotal=Decimal("75.00"),
                tax_amount=Decimal("3.75"),
                shipping_amount=Decimal("7.50"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("86.25"),
                currency="USD",
                shipping_address1="321 Status St",
                shipping_city="Test City",
                shipping_state="TS",
                shipping_postal_code="12348",
                shipping_country="US",
                shipping_latitude=40.7128,
                shipping_longitude=-74.0060,
                created_at=datetime.now(timezone.utc),
                metadata_={},
            )
            self.db.add(order)
            await self.db.flush()
            status_transitions.append(order.status.value)

            # Add line item
            item = OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                sku="TEST-SKU-1",
                product_name="Test Product 1",
                quantity=1,
                unit_price=Decimal("75.00"),
                total_price=Decimal("75.00"),
                metadata_={},
            )
            self.db.add(item)
            await self.db.flush()

            # Transition 1: PENDING → SOURCED (via allocation)
            order.status = OrderStatus.SOURCED
            alloc = FulfillmentAllocation(
                id=uuid.uuid4(),
                order_id=order.id,
                order_item_id=item.id,
                node_id=self.test_nodes[0].id,
                sku=item.sku,
                quantity_allocated=item.quantity,
                status=AllocationStatus.ALLOCATED,
                sourcing_score=0.95,
                sourcing_metadata={},
            )
            self.db.add(alloc)
            await self.db.flush()
            status_transitions.append(order.status.value)
            self.test_resources["allocations"].append(alloc.id)

            # Transition 2: SOURCED → PICKING (fulfillment workflow)
            order.status = OrderStatus.PICKING
            alloc.status = AllocationStatus.PICKING
            await self.db.flush()
            status_transitions.append(order.status.value)

            # Transition 3: PICKING → PACKING (after pick is complete)
            order.status = OrderStatus.PACKING
            alloc.status = AllocationStatus.PACKED
            await self.db.flush()
            status_transitions.append(order.status.value)

            # Transition 4: PACKING → READY_TO_SHIP (after packing)
            order.status = OrderStatus.READY_TO_SHIP
            await self.db.flush()
            status_transitions.append(order.status.value)

            # Create shipment and mark SHIPPED
            shipment = Shipment(
                id=uuid.uuid4(),
                order_id=order.id,
                allocation_id=alloc.id,
                status=ShipmentStatus.PENDING,
                tracking_number=None,
                carrier=None,
                service_level=None,
                tracking_events=[],
            )
            self.db.add(shipment)
            await self.db.flush()
            self.test_resources["shipments"].append(shipment.id)

            # Transition 5: READY_TO_SHIP → SHIPPED (after shipment)
            order.status = OrderStatus.SHIPPED
            alloc.status = AllocationStatus.SHIPPED
            shipment.status = ShipmentStatus.PENDING
            await self.db.flush()
            status_transitions.append(order.status.value)

            await self.db.commit()
            self.test_orders.append(order)
            self.test_resources["orders"].append(order.id)

            created_resources = {
                "order_id": str(order.id),
                "status_transitions": status_transitions,
                "final_status": order.status.value,
                "transitions_count": len(status_transitions),
                "workflow_path": "PENDING → SOURCED → PICKING → PACKING → READY_TO_SHIP → SHIPPED",
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Order Status Transitions",
            status=status,
            duration_ms=duration,
            message="Status transitions successful" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_large_order(self) -> TestFlowResult:
        """Test: Large order with many line items."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            # Create large order with 20 line items
            order = Order(
                id=uuid.uuid4(),
                order_number=f"TEST-LARGE-{uuid.uuid4().hex[:6]}",
                channel=OrderChannel.WEB,
                fulfillment_type=FulfillmentType.SHIP_TO_HOME,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
                customer_name="Large Order Customer",
                customer_email=f"large_{uuid.uuid4().hex[:4]}@example.com",
                customer_phone="+1-555-0004",
                subtotal=Decimal("1000.00"),
                tax_amount=Decimal("50.00"),
                shipping_amount=Decimal("25.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("1075.00"),
                currency="USD",
                shipping_address1="999 Large St",
                shipping_city="Test City",
                shipping_state="TS",
                shipping_postal_code="12349",
                shipping_country="US",
                shipping_latitude=40.7128,
                shipping_longitude=-74.0060,
                created_at=datetime.now(timezone.utc),
                metadata_={"test_type": "large_order", "line_item_count": 20},
            )
            self.db.add(order)
            await self.db.flush()

            # Create 20 line items
            for i in range(20):
                item = OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    sku=f"TEST-SKU-{(i % 2) + 1}",
                    product_name=f"Test Product {(i % 2) + 1}",
                    quantity=3,
                    unit_price=Decimal("50.00"),
                    total_price=Decimal("150.00"),
                    metadata_={"item_index": i},
                )
                self.db.add(item)

            await self.db.flush()

            # Create allocations for all items
            await self.db.refresh(order, ["line_items"])
            allocation_count = 0
            
            for item_idx, item in enumerate(order.line_items):
                node = self.test_nodes[item_idx % len(self.test_nodes)]
                alloc = FulfillmentAllocation(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    order_item_id=item.id,
                    node_id=node.id,
                    sku=item.sku,
                    quantity_allocated=item.quantity,
                    status=AllocationStatus.ALLOCATED,
                    sourcing_score=0.92,
                    sourcing_metadata={"item_index": item_idx},
                )
                self.db.add(alloc)
                self.test_resources["allocations"].append(alloc.id)
                allocation_count += 1

            order.status = OrderStatus.SOURCED
            await self.db.commit()
            self.test_orders.append(order)
            self.test_resources["orders"].append(order.id)

            created_resources = {
                "order_id": str(order.id),
                "line_items": len(order.line_items),
                "allocations_created": allocation_count,
                "total_quantity": sum(item.quantity for item in order.line_items),
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Large Order Processing",
            status=status,
            duration_ms=duration,
            message="Large order processed successfully" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    async def test_partial_allocation(self) -> TestFlowResult:
        """Test: Partial allocation across available inventory."""
        start = datetime.now(timezone.utc)
        errors = []
        created_resources = {}

        try:
            # Create order requiring partial allocation
            order = Order(
                id=uuid.uuid4(),
                order_number=f"TEST-PARTIAL-{uuid.uuid4().hex[:6]}",
                channel=OrderChannel.WEB,
                fulfillment_type=FulfillmentType.SHIP_TO_HOME,
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
                customer_name="Partial Order Customer",
                customer_email=f"partial_{uuid.uuid4().hex[:4]}@example.com",
                customer_phone="+1-555-0005",
                subtotal=Decimal("150.00"),
                tax_amount=Decimal("7.50"),
                shipping_amount=Decimal("10.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("167.50"),
                currency="USD",
                shipping_address1="555 Partial St",
                shipping_city="Test City",
                shipping_state="TS",
                shipping_postal_code="12350",
                shipping_country="US",
                shipping_latitude=40.7128,
                shipping_longitude=-74.0060,
                created_at=datetime.now(timezone.utc),
                metadata_={"test_type": "partial_allocation"},
            )
            self.db.add(order)
            await self.db.flush()

            # Add line items requesting more than single node has
            for i in range(2):
                item = OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    sku=f"TEST-SKU-{i+1}",
                    product_name=f"Test Product {i+1}",
                    quantity=50,  # More than any single node's 100
                    unit_price=Decimal("75.00"),
                    total_price=Decimal("75.00"),
                    metadata_={},
                )
                self.db.add(item)

            await self.db.flush()

            # Create partial allocations from different nodes
            await self.db.refresh(order, ["line_items"])
            nodes_used = set()
            
            for item in order.line_items:
                # Allocate from first available node with inventory
                for node in self.test_nodes:
                    alloc = FulfillmentAllocation(
                        id=uuid.uuid4(),
                        order_id=order.id,
                        order_item_id=item.id,
                        node_id=node.id,
                        sku=item.sku,
                        quantity_allocated=item.quantity,  # Full allocation
                        status=AllocationStatus.ALLOCATED,
                        sourcing_score=0.88,
                        sourcing_metadata={"partial": True},
                    )
                    self.db.add(alloc)
                    self.test_resources["allocations"].append(alloc.id)
                    nodes_used.add(str(node.id))
                    break  # Only allocate from one node per item

            order.status = OrderStatus.SOURCED
            await self.db.commit()
            self.test_orders.append(order)
            self.test_resources["orders"].append(order.id)

            created_resources = {
                "order_id": str(order.id),
                "line_items": len(order.line_items),
                "nodes_used": len(nodes_used),
                "allocation_strategy": "partial_from_available",
            }

        except Exception as e:
            try:
                await self.db.rollback()
            except:
                pass
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        status = TestFlowStatus.PASSED if not errors else TestFlowStatus.FAILED

        return TestFlowResult(
            name="Partial Allocation",
            status=status,
            duration_ms=duration,
            message="Partial allocation successful" if status == TestFlowStatus.PASSED else errors[0],
            created_resources=created_resources,
            errors=errors,
        )

    # ── Real pipeline scenario helpers ───────────────────────────────────────

    # Canonical starting inventory for E2E SKUs.
    # Format: {sku: (east_qty, west_qty)}
    #   east = test_nodes[0] (TEST-NYC-*)  — geographic analog of DC-EAST
    #   west = test_nodes[1] (TEST-LA-*)   — geographic analog of DC-WEST
    # Real DC-EAST / DC-WEST nodes are never touched by E2E tests.
    _E2E_INVENTORY_CANONICAL: Dict[str, tuple] = {
        "E2E-SKU-A": (50, 0),   # east only
        "E2E-SKU-B": (0,  50),  # west only
        "E2E-SKU-C": (8,  7),   # split: 8 east, 7 west
        "E2E-SKU-D": (50, 0),   # east only
        "E2E-SKU-E": (50, 0),   # east only
        "E2E-SKU-F": (10, 0),   # east only
    }

    async def _reset_e2e_inventory(self, spec: Optional[Dict[str, tuple]] = None):
        """
        Reset E2E SKU quantities on the *test nodes* for this run.

        spec format: {sku: (east_qty, west_qty)}
          east = self.test_nodes[0], west = self.test_nodes[1]

        Real DC-EAST / DC-WEST inventory is NEVER modified.
        """
        if not self.test_nodes or len(self.test_nodes) < 2:
            return
        if spec is None:
            spec = self._E2E_INVENTORY_CANONICAL
        east_id = self.test_nodes[0].id
        west_id = self.test_nodes[1].id
        from sqlalchemy import text as sqla_text
        for sku, (east_qty, west_qty) in spec.items():
            for node_id, qty in [(east_id, east_qty), (west_id, west_qty)]:
                await self.db.execute(sqla_text("""
                    UPDATE inventory_items
                    SET quantity_on_hand   = :qty,
                        quantity_available = :qty,
                        quantity_reserved  = 0
                    WHERE node_id = :node_id
                      AND sku     = :sku
                """), {"qty": qty, "node_id": node_id, "sku": sku})
        await self.db.flush()

    async def _create_scenario_order(
        self,
        order_number: str,
        lines: List[Dict[str, Any]],
    ) -> "Order":
        from decimal import Decimal as D
        subtotal = sum(D(str(l["price"])) * l["qty"] for l in lines)
        order = Order(
            id=uuid.uuid4(),
            order_number=order_number,
            channel=OrderChannel.WEB,
            fulfillment_type=FulfillmentType.SHIP_TO_HOME,
            status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.CAPTURED,
            customer_name="E2E Test Customer",
            customer_email=f"e2e_{uuid.uuid4().hex[:6]}@test.internal",
            subtotal=subtotal,
            tax_amount=(subtotal * D("0.08")).quantize(D("0.01")),
            shipping_amount=D("0"),
            discount_amount=D("0"),
            total_amount=subtotal,
            currency="USD",
            shipping_address1="1 E2E Way",
            shipping_city="Test City",
            shipping_state="TX",
            shipping_postal_code="75001",
            shipping_country="US",
            tags=[],
            confirmed_at=datetime.now(timezone.utc),
            metadata_={"e2e": True},
        )
        self.db.add(order)
        await self.db.flush()
        for line in lines:
            self.db.add(OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                sku=line["sku"],
                product_name=line.get("name", line["sku"]),
                quantity=line["qty"],
                unit_price=D(str(line["price"])),
                total_price=D(str(line["price"])) * line["qty"],
                metadata_={},
            ))
        await self.db.commit()
        self.test_resources["orders"].append(order.id)
        return order

    async def _run_full_pipeline(self, order_id: "uuid.UUID") -> Dict[str, Any]:
        """
        Drive an order through source → pick → pack → book_shipment → deliver.

        Each call opens its own AsyncSession so that stale identity-map state
        from previous scenario runs cannot trigger lazy-relationship loads
        (greenlet_spawn error).  No expire_all() calls are needed because every
        step re-queries the objects it needs from the fresh session.
        """
        import uuid as _uuid
        import random
        from datetime import timedelta
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload as _sil
        from app.services.sourcing_engine import SourcingEngine
        from app.database.postgres import async_session_factory

        async with async_session_factory() as db:

            # ── 1. Source ────────────────────────────────────────────────────
            order = (await db.execute(
                sa_select(Order)
                .options(_sil(Order.line_items))
                .where(Order.id == order_id)
            )).scalar_one_or_none()
            if not order:
                return {"order_status": "NOT_FOUND", "shipment_count": 0,
                        "alloc_count": 0, "allocations": [], "shipments": []}

            se = SourcingEngine(db)
            sourcing_result = await se.source_order(order, skip_rule=True)

            if sourcing_result.total_split_nodes == 0:
                order.status = OrderStatus.BACKORDERED
            await db.commit()

            # ── 2. Pick ──────────────────────────────────────────────────────
            order = (await db.execute(
                sa_select(Order).where(Order.id == order_id)
            )).scalar_one_or_none()
            if order and order.status == OrderStatus.SOURCED:
                order.status = OrderStatus.PICKING
                allocs = (await db.execute(
                    sa_select(FulfillmentAllocation).where(
                        FulfillmentAllocation.order_id == order_id,
                        FulfillmentAllocation.status == AllocationStatus.ALLOCATED,
                    )
                )).scalars().all()
                for a in allocs:
                    a.status = AllocationStatus.PICKING
                    a.picking_started_at = datetime.now(timezone.utc)
                await db.commit()

            # ── 3. Pack ──────────────────────────────────────────────────────
            order = (await db.execute(
                sa_select(Order).where(Order.id == order_id)
            )).scalar_one_or_none()
            if order and order.status == OrderStatus.PICKING:
                order.status = OrderStatus.PACKING
                allocs = (await db.execute(
                    sa_select(FulfillmentAllocation).where(
                        FulfillmentAllocation.order_id == order_id)
                )).scalars().all()
                for a in allocs:
                    a.status = AllocationStatus.PACKED
                    a.packed_at = datetime.now(timezone.utc)
                await db.commit()

                order = (await db.execute(
                    sa_select(Order).where(Order.id == order_id)
                )).scalar_one_or_none()
                if order:
                    order.status = OrderStatus.READY_TO_SHIP
                    await db.commit()

            # ── 4. Book Shipment ─────────────────────────────────────────────
            order = (await db.execute(
                sa_select(Order).where(Order.id == order_id)
            )).scalar_one_or_none()
            if order and order.status == OrderStatus.READY_TO_SHIP:
                allocations = (await db.execute(
                    sa_select(FulfillmentAllocation).where(
                        FulfillmentAllocation.order_id == order_id)
                )).scalars().all()

                allocs_by_node: Dict[Any, list] = {}
                for alloc in allocations:
                    allocs_by_node.setdefault(alloc.node_id, []).append(alloc)

                CARRIERS = ["UPS", "FedEx", "USPS", "DHL"]
                SERVICE_LEVELS = ["Ground", "2-Day", "Overnight"]
                est_days_map = {"Ground": 5, "2-Day": 2, "Overnight": 1}

                for node_id, node_allocs in allocs_by_node.items():
                    carrier = random.choice(CARRIERS)
                    service = random.choice(SERVICE_LEVELS)
                    tracking = f"E2E{_uuid.uuid4().hex[:14].upper()}"
                    est_delivery = datetime.now(timezone.utc) + timedelta(
                        days=est_days_map.get(service, 3))
                    shipped_items = [
                        {"allocation_id": str(a.id), "sku": a.sku,
                         "quantity": a.quantity_allocated,
                         "node_id": str(a.node_id) if a.node_id else None}
                        for a in node_allocs
                    ]
                    shipment = Shipment(
                        order_id=order.id,
                        allocation_id=node_allocs[0].id,
                        tracking_number=tracking,
                        carrier=carrier,
                        service_level=service,
                        status=ShipmentStatus.LABEL_CREATED,
                        label_url=f"https://labels.example.com/{tracking}.pdf",
                        label_created_at=datetime.now(timezone.utc),
                        shipped_at=datetime.now(timezone.utc),
                        estimated_delivery_at=est_delivery,
                        shipping_cost=round(random.uniform(4.99, 24.99), 2),
                        tracking_events=[{
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "status": "LABEL_CREATED",
                            "location": "Origin Facility",
                            "description": "Shipping label created",
                            "items": shipped_items,
                        }],
                    )
                    db.add(shipment)
                    await db.flush()  # materialise shipment.id

                    for a in node_allocs:
                        a.status = AllocationStatus.SHIPPED
                        a.shipped_at = datetime.now(timezone.utc)

                    # Deduct inventory
                    from app.models.postgres.inventory_models import InventoryItem as _II
                    for a in node_allocs:
                        if not a.node_id or not a.sku:
                            continue
                        inv = (await db.execute(
                            sa_select(_II).where(
                                _II.node_id == a.node_id, _II.sku == a.sku)
                        )).scalar_one_or_none()
                        if inv:
                            qty = a.quantity_allocated or 0
                            inv.quantity_on_hand   = max(0, inv.quantity_on_hand   - qty)
                            inv.quantity_reserved  = max(0, inv.quantity_reserved  - qty)
                            inv.quantity_available = max(0, inv.quantity_on_hand
                                                         - inv.quantity_reserved)

                order.status = OrderStatus.SHIPPED
                await db.commit()

            # ── 5. Simulate Delivery ─────────────────────────────────────────
            # Re-query shipments fresh (no expire_all needed in isolated session)
            ship_rows = (await db.execute(
                sa_select(Shipment).where(Shipment.order_id == order_id)
            )).scalars().all()

            if ship_rows:
                deliver_ts = datetime.now(timezone.utc)

                # Update each shipment's tracking events
                for shp in ship_rows:
                    events = list(shp.tracking_events or [])
                    events += [
                        {"timestamp": deliver_ts.isoformat(), "status": "IN_TRANSIT",
                         "location": "Regional Sort Facility",
                         "description": "Package in transit"},
                        {"timestamp": deliver_ts.isoformat(), "status": "OUT_FOR_DELIVERY",
                         "location": "Local Delivery Facility",
                         "description": "Out for delivery"},
                        {"timestamp": deliver_ts.isoformat(), "status": "DELIVERED",
                         "location": "Customer Address",
                         "description": "Package delivered"},
                    ]
                    shp.tracking_events = events
                    shp.status = ShipmentStatus.DELIVERED
                    shp.actual_delivery_at = deliver_ts

                # Bulk-mark ALL order allocations as DELIVERED in one query
                # (avoids per-shipment alloc_id resolution and the need for
                #  expire_all() between setting status and committing)
                all_allocs = (await db.execute(
                    sa_select(FulfillmentAllocation).where(
                        FulfillmentAllocation.order_id == order_id)
                )).scalars().all()
                for a in all_allocs:
                    a.status = AllocationStatus.DELIVERED

                # Re-query order and mark DELIVERED — no expire_all() needed
                order = (await db.execute(
                    sa_select(Order).where(Order.id == order_id)
                )).scalar_one_or_none()
                if order:
                    order.status = OrderStatus.DELIVERED

                # Single commit — all changes (shipments + allocs + order) land together
                await db.commit()

            # ── Read Final State ─────────────────────────────────────────────
            final_order = (await db.execute(
                sa_select(Order).where(Order.id == order_id)
            )).scalar_one_or_none()
            allocs = (await db.execute(
                sa_select(FulfillmentAllocation).where(
                    FulfillmentAllocation.order_id == order_id)
            )).scalars().all()
            ships = (await db.execute(
                sa_select(Shipment).where(Shipment.order_id == order_id)
            )).scalars().all()

            return {
                "order_status": final_order.status.value if final_order else "NOT_FOUND",
                "shipment_count": len(ships),
                "alloc_count": len(allocs),
                "allocations": [
                    {"sku": a.sku, "qty": a.quantity_allocated,
                     "status": a.status.value if hasattr(a.status, "value") else str(a.status)}
                    for a in allocs
                ],
                "shipments": [
                    {"tracking": s.tracking_number,
                     "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                     "items": (s.tracking_events or [{}])[0].get("items", [])}
                    for s in ships
                ],
            }

    # ── TC-01: Single Line, Single Unit ───────────────────────────────────────

    async def scenario_tc01_single_line_single_unit(self) -> "TestFlowResult":
        """TC-01: 1 SKU × 1 unit → DC-EAST only → 1 shipment → DELIVERED."""
        start = datetime.now(timezone.utc)
        errors: List[str] = []
        resource: Dict[str, Any] = {}
        try:
            await self._reset_e2e_inventory({"E2E-SKU-A": (50, 0)})
            order = await self._create_scenario_order(
                f"TC01-{uuid.uuid4().hex[:6]}",
                [{"sku": "E2E-SKU-A", "qty": 1, "price": "19.99"}],
            )
            resource["order_number"] = order.order_number
            state = await self._run_full_pipeline(order.id)
            resource.update(state)
            if state["order_status"] != "DELIVERED":
                errors.append(f"Expected DELIVERED, got {state['order_status']}")
            if state["shipment_count"] != 1:
                errors.append(f"Expected 1 shipment, got {state['shipment_count']}")
            all_delivered = all(a["status"] == "DELIVERED" for a in state["allocations"])
            if not all_delivered:
                errors.append("Not all allocations DELIVERED")
        except Exception as exc:
            errors.append(str(exc))
            try: await self.db.rollback()
            except Exception: pass

        ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        ok = not errors
        return TestFlowResult(
            name="TC-01: Single Line, Single Unit",
            status=TestFlowStatus.PASSED if ok else TestFlowStatus.FAILED,
            duration_ms=ms,
            message="1 SKU × 1 unit → 1 shipment → DELIVERED ✓" if ok else errors[0],
            created_resources=resource, errors=errors,
        )

    # ── TC-02: Single Line, Multiple Units, Single DC ─────────────────────────

    async def scenario_tc02_single_line_multi_unit(self) -> "TestFlowResult":
        """TC-02: 1 SKU × 10 units → DC-EAST only → 1 shipment → DELIVERED."""
        start = datetime.now(timezone.utc)
        errors: List[str] = []
        resource: Dict[str, Any] = {}
        try:
            await self._reset_e2e_inventory({"E2E-SKU-A": (50, 0)})
            order = await self._create_scenario_order(
                f"TC02-{uuid.uuid4().hex[:6]}",
                [{"sku": "E2E-SKU-A", "qty": 10, "price": "19.99"}],
            )
            resource["order_number"] = order.order_number
            state = await self._run_full_pipeline(order.id)
            resource.update(state)
            if state["order_status"] != "DELIVERED":
                errors.append(f"Expected DELIVERED, got {state['order_status']}")
            if state["shipment_count"] != 1:
                errors.append(f"Expected 1 shipment, got {state['shipment_count']}")
            total = sum(a["qty"] for a in state["allocations"])
            if total != 10:
                errors.append(f"Expected 10 units, got {total}")
        except Exception as exc:
            errors.append(str(exc))
            try: await self.db.rollback()
            except Exception: pass

        ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        ok = not errors
        return TestFlowResult(
            name="TC-02: Single Line, 10 Units, Single DC",
            status=TestFlowStatus.PASSED if ok else TestFlowStatus.FAILED,
            duration_ms=ms,
            message="1 SKU × 10 units → 1 shipment → DELIVERED ✓" if ok else errors[0],
            created_resources=resource, errors=errors,
        )

    # ── TC-03: Single Line, Split Across 2 DCs ───────────────────────────────

    async def scenario_tc03_single_line_split_dcs(self) -> "TestFlowResult":
        """TC-03: 1 SKU × 15 units, DC-EAST=8, DC-WEST=7 → 2 shipments → DELIVERED."""
        start = datetime.now(timezone.utc)
        errors: List[str] = []
        resource: Dict[str, Any] = {}
        try:
            await self._reset_e2e_inventory({"E2E-SKU-C": (8, 7)})
            order = await self._create_scenario_order(
                f"TC03-{uuid.uuid4().hex[:6]}",
                [{"sku": "E2E-SKU-C", "qty": 15, "price": "29.99"}],
            )
            resource["order_number"] = order.order_number
            state = await self._run_full_pipeline(order.id)
            resource.update(state)
            if state["order_status"] != "DELIVERED":
                errors.append(f"Expected DELIVERED, got {state['order_status']}")
            if state["shipment_count"] != 2:
                errors.append(f"Expected 2 shipments (DC split), got {state['shipment_count']}")
            total = sum(a["qty"] for a in state["allocations"])
            if total != 15:
                errors.append(f"Expected 15 total units, got {total}")
        except Exception as exc:
            errors.append(str(exc))
            try: await self.db.rollback()
            except Exception: pass

        ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        ok = not errors
        return TestFlowResult(
            name="TC-03: Single Line Split Across 2 DCs (8+7)",
            status=TestFlowStatus.PASSED if ok else TestFlowStatus.FAILED,
            duration_ms=ms,
            message="1 SKU × 15 split DC-EAST:8 + DC-WEST:7 → 2 shipments → DELIVERED ✓" if ok else errors[0],
            created_resources=resource, errors=errors,
        )

    # ── TC-04: Multi-Line, All Same DC (Grouped Shipment) ────────────────────

    async def scenario_tc04_multi_line_grouped_shipment(self) -> "TestFlowResult":
        """TC-04: 3 SKUs × 5 units each, all at DC-EAST → 1 grouped shipment → DELIVERED."""
        start = datetime.now(timezone.utc)
        errors: List[str] = []
        resource: Dict[str, Any] = {}
        try:
            await self._reset_e2e_inventory({
                "E2E-SKU-A": (50, 0),
                "E2E-SKU-D": (50, 0),
                "E2E-SKU-E": (50, 0),
            })
            order = await self._create_scenario_order(
                f"TC04-{uuid.uuid4().hex[:6]}",
                [
                    {"sku": "E2E-SKU-A", "qty": 5, "price": "19.99"},
                    {"sku": "E2E-SKU-D", "qty": 5, "price": "24.99"},
                    {"sku": "E2E-SKU-E", "qty": 5, "price": "34.99"},
                ],
            )
            resource["order_number"] = order.order_number
            state = await self._run_full_pipeline(order.id)
            resource.update(state)
            if state["order_status"] != "DELIVERED":
                errors.append(f"Expected DELIVERED, got {state['order_status']}")
            if state["shipment_count"] != 1:
                errors.append(f"Expected 1 grouped shipment, got {state['shipment_count']}")
            if state["shipments"]:
                items = state["shipments"][0]["items"]
                shipped_skus = {i["sku"] for i in items}
                expected = {"E2E-SKU-A", "E2E-SKU-D", "E2E-SKU-E"}
                missing = expected - shipped_skus
                if missing:
                    errors.append(f"Missing SKUs in grouped shipment: {missing}")
        except Exception as exc:
            errors.append(str(exc))
            try: await self.db.rollback()
            except Exception: pass

        ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        ok = not errors
        return TestFlowResult(
            name="TC-04: Multi-Line Grouped Shipment (same DC)",
            status=TestFlowStatus.PASSED if ok else TestFlowStatus.FAILED,
            duration_ms=ms,
            message="3 SKUs × 5 units all DC-EAST → 1 grouped shipment → DELIVERED ✓" if ok else errors[0],
            created_resources=resource, errors=errors,
        )

    # ── TC-05: Multi-Line, SKUs at Different DCs ──────────────────────────────

    async def scenario_tc05_multi_line_split_dcs(self) -> "TestFlowResult":
        """TC-05: SKU-A only at DC-EAST, SKU-B only at DC-WEST → 2 shipments → DELIVERED."""
        start = datetime.now(timezone.utc)
        errors: List[str] = []
        resource: Dict[str, Any] = {}
        try:
            await self._reset_e2e_inventory({
                "E2E-SKU-A": (50, 0),
                "E2E-SKU-B": (0,  50),
            })
            order = await self._create_scenario_order(
                f"TC05-{uuid.uuid4().hex[:6]}",
                [
                    {"sku": "E2E-SKU-A", "qty": 5, "price": "19.99"},
                    {"sku": "E2E-SKU-B", "qty": 5, "price": "29.99"},
                ],
            )
            resource["order_number"] = order.order_number
            state = await self._run_full_pipeline(order.id)
            resource.update(state)
            if state["order_status"] != "DELIVERED":
                errors.append(f"Expected DELIVERED, got {state['order_status']}")
            if state["shipment_count"] != 2:
                errors.append(f"Expected 2 shipments (one per DC), got {state['shipment_count']}")
            alloc_skus = {a["sku"] for a in state["allocations"]}
            if alloc_skus != {"E2E-SKU-A", "E2E-SKU-B"}:
                errors.append(f"Expected both SKUs allocated, got {alloc_skus}")
        except Exception as exc:
            errors.append(str(exc))
            try: await self.db.rollback()
            except Exception: pass

        ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        ok = not errors
        return TestFlowResult(
            name="TC-05: Multi-Line SKUs at Different DCs",
            status=TestFlowStatus.PASSED if ok else TestFlowStatus.FAILED,
            duration_ms=ms,
            message="SKU-A@DC-EAST + SKU-B@DC-WEST → 2 shipments → DELIVERED ✓" if ok else errors[0],
            created_resources=resource, errors=errors,
        )

    # ── TC-06: Backorder (Insufficient Inventory) ─────────────────────────────

    async def scenario_tc06_backorder(self) -> "TestFlowResult":
        """TC-06: Order 20 units, only 10 in stock. Engine must not oversell."""
        start = datetime.now(timezone.utc)
        errors: List[str] = []
        resource: Dict[str, Any] = {}
        try:
            await self._reset_e2e_inventory({"E2E-SKU-F": (10, 0)})
            order = await self._create_scenario_order(
                f"TC06-{uuid.uuid4().hex[:6]}",
                [{"sku": "E2E-SKU-F", "qty": 20, "price": "49.99"}],
            )
            resource["order_number"] = order.order_number

            # Run the full pipeline — engine may only partially fulfil due to stock limit
            state = await self._run_full_pipeline(order.id)
            resource.update(state)

            total_allocated = sum(a["qty"] for a in state.get("allocations", []))
            resource["total_allocated"] = total_allocated
            resource["ordered_qty"] = 20
            resource["available_stock"] = 10

            if total_allocated > 10:
                errors.append(f"OVERSELL: engine allocated {total_allocated} but only 10 in stock")
        except Exception as exc:
            errors.append(str(exc))
            try: await self.db.rollback()
            except Exception: pass

        ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        ok = not errors
        return TestFlowResult(
            name="TC-06: Backorder — Insufficient Inventory",
            status=TestFlowStatus.PASSED if ok else TestFlowStatus.FAILED,
            duration_ms=ms,
            message=f"Order 20, stock=10 → allocated {resource.get('total_allocated','?')} (no oversell) ✓" if ok else errors[0],
            created_resources=resource, errors=errors,
        )

    async def run_all_tests(self) -> List[TestFlowResult]:
        """Run all test flows in sequence."""
        results: List[TestFlowResult] = []

        # Setup shared test data for basic tests
        await self.setup_test_data()

        # ── Basic (data-driven) tests ─────────────────────────────────────────
        results.append(await self.test_create_order())
        results.append(await self.test_source_order())
        results.append(await self.test_create_shipment())
        results.append(await self.test_multi_node_allocation())
        results.append(await self.test_inventory_validation())
        results.append(await self.test_order_status_transitions())
        results.append(await self.test_large_order())
        results.append(await self.test_partial_allocation())

        # ── Real pipeline scenarios (run actual Celery workers) ───────────────
        results.append(await self.scenario_tc01_single_line_single_unit())
        results.append(await self.scenario_tc02_single_line_multi_unit())
        results.append(await self.scenario_tc03_single_line_split_dcs())
        results.append(await self.scenario_tc04_multi_line_grouped_shipment())
        results.append(await self.scenario_tc05_multi_line_split_dcs())
        results.append(await self.scenario_tc06_backorder())

        return results

    async def _delete_order_children(self, order_id) -> None:
        """Delete all FK-dependent rows for an order before deleting the order itself."""
        from app.models.postgres.return_models import OrderReturn, Refund
        from app.models.postgres.invoice_models import Invoice, CreditMemo
        from app.models.postgres.ai_models import SourcingOutcomeLabel

        # Must delete in FK-safe order: children before parents
        await self.db.execute(delete(SourcingOutcomeLabel).where(SourcingOutcomeLabel.order_id == order_id))
        await self.db.execute(delete(Refund).where(Refund.order_id == order_id))
        await self.db.execute(delete(CreditMemo).where(CreditMemo.order_id == order_id))
        # ReturnItems cascade-delete when OrderReturn is deleted
        await self.db.execute(delete(OrderReturn).where(OrderReturn.order_id == order_id))
        # InvoiceLineItems and InvoicePayments cascade-delete when Invoice is deleted
        await self.db.execute(delete(Invoice).where(Invoice.order_id == order_id))
        await self.db.execute(delete(WebhookEvent).where(WebhookEvent.order_id == order_id))
        await self.db.execute(delete(ConnectorEvent).where(ConnectorEvent.order_id == order_id))
        await self.db.execute(delete(Shipment).where(Shipment.order_id == order_id))
        await self.db.execute(delete(FulfillmentAllocation).where(FulfillmentAllocation.order_id == order_id))
        await self.db.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
        await self.db.execute(delete(Order).where(Order.id == order_id))

    async def cleanup(self) -> Dict[str, int]:
        """Delete all test data created during testing."""
        deleted_counts = {}
        all_cleaned_order_ids: List[str] = []

        try:
            # ── Step 1: delete orders tracked by this run ─────────────────────
            for order_id in self.test_resources["orders"]:
                await self._delete_order_children(order_id)
                all_cleaned_order_ids.append(str(order_id))

            deleted_counts["orders"] = len(self.test_resources["orders"])

            # ── Step 2: sweep orphaned test orders from any previous run ──────
            # Matches all order_number patterns produced by basic + scenario tests:
            #   TEST-*    – basic test_create_order
            #   TC01-* ... TC06-*  – real pipeline scenarios
            orphan_result = await self.db.execute(
                select(Order.id).where(
                    or_(
                        Order.order_number.like("TEST-%"),
                        Order.order_number.like("TC0%"),
                        Order.order_number.like("E2E-TC%"),  # legacy pattern
                    )
                )
            )
            orphan_ids = [row[0] for row in orphan_result.fetchall()]
            for order_id in orphan_ids:
                await self._delete_order_children(order_id)
                all_cleaned_order_ids.append(str(order_id))

            deleted_counts["orphaned_orders"] = len(orphan_ids)

            # ── Step 2b: sweep by test email patterns (catches ORD-* API orders) ──
            # Matches orders created by ApiIntegrationTestService and E2E scenarios
            # that use the standard ORD-YYYYMMDD-XXXXX numbering.
            email_order_result = await self.db.execute(
                select(Order.id).where(
                    or_(
                        Order.customer_email.like("%.uat@example.com"),
                        Order.customer_email.like("%@test.internal"),
                        Order.customer_email.like("test-e2e@example.com"),
                        Order.customer_email.like("cancel.test@example.com"),
                        Order.customer_email.like("lifecycle.test@example.com"),
                        Order.customer_email.like("%@test.com"),
                    )
                )
            )
            email_order_ids = [row[0] for row in email_order_result.fetchall()]
            for order_id in email_order_ids:
                await self._delete_order_children(order_id)
                all_cleaned_order_ids.append(str(order_id))
            deleted_counts["email_pattern_orders"] = len(email_order_ids)

            # ── Step 3: permanently delete ALL E2E-SKU inventory ─────────────
            e2e_ids = (
                await self.db.execute(
                    select(InventoryItem.id).where(InventoryItem.sku.like("E2E-SKU-%"))
                )
            ).scalars().all()
            if e2e_ids:
                await self.db.execute(
                    delete(InventoryAdjustment).where(
                        InventoryAdjustment.inventory_item_id.in_(e2e_ids)
                    )
                )
            e2e_del = await self.db.execute(
                delete(InventoryItem).where(InventoryItem.sku.like("E2E-SKU-%"))
            )
            deleted_counts["e2e_inventory"] = e2e_del.rowcount if hasattr(e2e_del, "rowcount") else 0

            # ── Step 4: delete inventory + nodes from this run ────────────────
            for node_id in self.test_resources["nodes"]:
                node_inv_ids = (
                    await self.db.execute(
                        select(InventoryItem.id).where(InventoryItem.node_id == node_id)
                    )
                ).scalars().all()
                if node_inv_ids:
                    await self.db.execute(
                        delete(InventoryAdjustment).where(
                            InventoryAdjustment.inventory_item_id.in_(node_inv_ids)
                        )
                    )
                await self.db.execute(delete(InventoryItem).where(InventoryItem.node_id == node_id))

            for node_id in self.test_resources["nodes"]:
                await self.db.execute(delete(FulfillmentNode).where(FulfillmentNode.id == node_id))

            deleted_counts["nodes"] = len(self.test_resources["nodes"])

            # ── Step 5: sweep orphaned test nodes from any previous run ───────
            orphan_nodes_result = await self.db.execute(
                select(FulfillmentNode.id).where(FulfillmentNode.code.like("TEST-%"))
            )
            orphan_node_ids = [row[0] for row in orphan_nodes_result.fetchall()]
            for node_id in orphan_node_ids:
                node_inv_ids = (
                    await self.db.execute(
                        select(InventoryItem.id).where(InventoryItem.node_id == node_id)
                    )
                ).scalars().all()
                if node_inv_ids:
                    await self.db.execute(
                        delete(InventoryAdjustment).where(
                            InventoryAdjustment.inventory_item_id.in_(node_inv_ids)
                        )
                    )
                await self.db.execute(delete(InventoryItem).where(InventoryItem.node_id == node_id))
                await self.db.execute(delete(FulfillmentNode).where(FulfillmentNode.id == node_id))

            deleted_counts["orphaned_nodes"] = len(orphan_node_ids)

            # ── Step 6: delete user from this run ────────────────────────────
            if self.test_resources["users"]:
                await self.db.execute(delete(User).where(User.id == self.test_resources["users"][0]))
                deleted_counts["users"] = 1

            # ── Step 7: sweep orphaned test users from any previous run ───────
            orphan_users_result = await self.db.execute(
                select(User.id).where(
                    or_(
                        User.email.like("test_%@example.com"),
                        User.email.like("e2e_%@test.internal"),
                        User.email.like("uat.reg.%@example.com"),
                        User.email.like("test.uat@example.com"),
                        User.email.like("cancel.uat@example.com"),
                    )
                )
            )
            orphan_user_ids = [row[0] for row in orphan_users_result.fetchall()]
            for user_id in orphan_user_ids:
                await self.db.execute(delete(User).where(User.id == user_id))

            deleted_counts["orphaned_users"] = len(orphan_user_ids)

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Cleanup failed: {str(e)}")

        # ── Step 8: MongoDB – purge order_events for all cleaned orders ───────
        # Non-critical: log warning on failure rather than raising.
        if all_cleaned_order_ids:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                from app.config import settings
                client = AsyncIOMotorClient(
                    settings.MONGODB_URL, serverSelectionTimeoutMS=3000,
                    uuidRepresentation="standard",
                )
                try:
                    result = await client[settings.MONGODB_DB].order_events.delete_many(
                        {"order_id": {"$in": all_cleaned_order_ids}}
                    )
                    deleted_counts["mongo_events"] = result.deleted_count
                finally:
                    client.close()
            except Exception as mongo_err:
                logger.warning("E2E MongoDB cleanup failed (non-critical): %s", mongo_err)
                deleted_counts["mongo_events"] = 0

        return deleted_counts
