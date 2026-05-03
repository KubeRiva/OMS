"""
Sourcing Rules Engine — the intelligence core of the OMS.

Implements 5 strategies:
  1. DISTANCE_OPTIMAL   – minimize distance from customer to fulfillment node
  2. COST_OPTIMAL       – minimize total fulfillment cost (shipping + handling)
  3. STORE_NEAREST      – like DISTANCE_OPTIMAL but restricted to retail stores
  4. INVENTORY_RESERVATION – prefer nodes with highest inventory availability
  5. LEAST_COST_SPLIT   – allow splitting across multiple nodes to minimize cost
                          while still meeting all quantities

Architecture:
  1. RuleSelector:   pick the highest-priority matching SourcingRule
  2. NodeFilter:     apply rule's node-type and capability filters
  3. NodeScorer:     score each candidate node per strategy
  4. SplitAlgorithm: for LEAST_COST_SPLIT, greedily assign SKUs to nodes
"""
import logging
import random
import time
from dataclasses import dataclass, field
from math import radians, cos, sin, asin, sqrt
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.postgres.inventory_models import InventoryItem
from app.models.postgres.node_models import FulfillmentNode, NodeStatus, NodeType
from app.models.postgres.order_models import (
    FulfillmentAllocation, Order, OrderItem, AllocationStatus, OrderStatus,
)
from app.models.postgres.sourcing_rule_models import (
    ConditionOperator, SourcingRule, SourcingStrategy,
)
from app.services.ai_sourcing import AISourcingAdvisor, AIAdvisorResult
from app.schemas.sourcing_rules import SourcingResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Earth radius in km
    φ1, φ2 = radians(lat1), radians(lat2)
    Δφ = radians(lat2 - lat1)
    Δλ = radians(lon2 - lon1)
    a = sin(Δφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(Δλ / 2) ** 2
    return R * 2 * asin(sqrt(a))


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_km(lat1, lon1, lat2, lon2) * 0.621371


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class NodeCandidate:
    node: FulfillmentNode
    inventory_by_sku: dict[str, int] = field(default_factory=dict)  # sku -> available qty
    distance_miles: float = 0.0
    estimated_cost: float = 0.0
    score: float = 0.0

    def can_fulfill_sku(self, sku: str, qty: int) -> bool:
        return self.inventory_by_sku.get(sku, 0) >= qty


@dataclass
class AllocationDecision:
    node_id: str
    node_code: str
    sku: str
    quantity: int
    score: float
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

def _evaluate_condition(order: Order, condition: dict) -> bool:
    """Evaluate a single sourcing condition against an order."""
    field_name = condition.get("field", "")
    operator = condition.get("operator", "")
    value = condition.get("value")

    # Resolve order field value
    field_map = {
        "channel": order.channel.value if order.channel else None,
        "fulfillment_type": order.fulfillment_type.value if order.fulfillment_type else None,
        "status": order.status.value if order.status else None,
        "total_amount": float(order.total_amount or 0),
        "currency": order.currency,
        "customer_email": order.customer_email,
        "shipping_country": order.shipping_country,
        "shipping_state": order.shipping_state,
    }
    order_value = field_map.get(field_name)
    if order_value is None:
        return False

    try:
        if operator == ConditionOperator.EQUALS:
            return str(order_value) == str(value)
        elif operator == ConditionOperator.NOT_EQUALS:
            return str(order_value) != str(value)
        elif operator == ConditionOperator.GREATER_THAN:
            return float(order_value) > float(value)
        elif operator == ConditionOperator.LESS_THAN:
            return float(order_value) < float(value)
        elif operator == ConditionOperator.GREATER_THAN_OR_EQUAL:
            return float(order_value) >= float(value)
        elif operator == ConditionOperator.LESS_THAN_OR_EQUAL:
            return float(order_value) <= float(value)
        elif operator == ConditionOperator.IN:
            return str(order_value) in [str(v) for v in (value if isinstance(value, list) else [value])]
        elif operator == ConditionOperator.NOT_IN:
            return str(order_value) not in [str(v) for v in (value if isinstance(value, list) else [value])]
        elif operator == ConditionOperator.CONTAINS:
            return str(value).lower() in str(order_value).lower()
        elif operator == ConditionOperator.STARTS_WITH:
            return str(order_value).lower().startswith(str(value).lower())
    except (TypeError, ValueError):
        return False
    return False


def _rule_matches(rule: SourcingRule, order: Order) -> bool:
    """Return True if ALL conditions in the rule match the order."""
    conditions = rule.conditions or []
    if not conditions:
        return True  # No conditions → always matches (catch-all)
    # Guard against old-format dict conditions (pre-migration data)
    if isinstance(conditions, dict):
        return True  # Can't evaluate old format — treat as catch-all
    dict_conditions = [c for c in conditions if isinstance(c, dict)]
    if not dict_conditions:
        return True
    return all(_evaluate_condition(order, c) for c in dict_conditions)


# ---------------------------------------------------------------------------
# Node filter
# ---------------------------------------------------------------------------

def _filter_nodes(
    candidates: list[FulfillmentNode],
    rule: Optional[SourcingRule],
    order: Order,
) -> list[FulfillmentNode]:
    """Apply rule-based node filters."""
    filtered = [n for n in candidates if n.status == NodeStatus.ACTIVE]

    if rule:
        if rule.allowed_node_types:
            allowed = set(rule.allowed_node_types)
            filtered = [n for n in filtered if n.node_type.value in allowed]

        if rule.excluded_node_ids:
            excluded = set(str(nid) for nid in rule.excluded_node_ids)
            filtered = [n for n in filtered if str(n.id) not in excluded]

        if rule.required_capabilities:
            cap_map = {
                "can_ship": "can_ship",
                "can_pickup": "can_pickup",
                "can_curbside": "can_curbside",
                "can_same_day": "can_same_day",
            }
            for cap in rule.required_capabilities:
                attr = cap_map.get(cap)
                if attr:
                    filtered = [n for n in filtered if getattr(n, attr, False)]

    # Apply fulfillment-type capability filter
    ft = order.fulfillment_type.value if order.fulfillment_type else ""
    if ft in ("STORE_PICKUP", "CURBSIDE_PICKUP"):
        filtered = [n for n in filtered if n.can_pickup or n.can_curbside]
    elif ft == "SAME_DAY_DELIVERY":
        filtered = [n for n in filtered if n.can_same_day]
    elif ft in ("SHIP_TO_HOME", "SHIP_FROM_STORE"):
        filtered = [n for n in filtered if n.can_ship]

    # Capacity filter
    filtered = [
        n for n in filtered
        if n.current_daily_orders < n.daily_order_capacity
    ]

    return filtered


# ---------------------------------------------------------------------------
# Node scorer
# ---------------------------------------------------------------------------

def _score_nodes(
    candidates: list[NodeCandidate],
    strategy: SourcingStrategy,
    rule: Optional[SourcingRule],
) -> list[NodeCandidate]:
    """Score each candidate node (higher = better). Returns sorted list."""
    if not candidates:
        return []

    max_dist = max((c.distance_miles for c in candidates), default=1) or 1
    max_cost = max((c.estimated_cost for c in candidates), default=1) or 1
    max_inv = max((sum(c.inventory_by_sku.values()) for c in candidates), default=1) or 1

    cost_w = (rule.cost_weight if rule else 0.5)
    dist_w = (rule.distance_weight if rule else 0.5)

    for c in candidates:
        inv_total = sum(c.inventory_by_sku.values())
        dist_norm = 1 - (c.distance_miles / max_dist)   # 1 = closest
        cost_norm = 1 - (c.estimated_cost / max_cost)  # 1 = cheapest
        inv_norm = inv_total / max_inv                  # 1 = most inventory

        if strategy == SourcingStrategy.DISTANCE_OPTIMAL:
            c.score = dist_norm * 0.7 + inv_norm * 0.3
        elif strategy == SourcingStrategy.COST_OPTIMAL:
            c.score = cost_norm * cost_w + dist_norm * dist_w
        elif strategy == SourcingStrategy.STORE_NEAREST:
            # Same as distance but restricted to stores (already filtered)
            c.score = dist_norm * 0.8 + inv_norm * 0.2
        elif strategy == SourcingStrategy.INVENTORY_RESERVATION:
            c.score = inv_norm * 0.8 + dist_norm * 0.2
        elif strategy == SourcingStrategy.LEAST_COST_SPLIT:
            # Per-node score used by split algorithm
            c.score = cost_norm * 0.6 + inv_norm * 0.4

    return sorted(candidates, key=lambda c: c.score, reverse=True)


# ---------------------------------------------------------------------------
# Split fulfillment algorithm
# ---------------------------------------------------------------------------

def _compute_split_allocations(
    items: list[OrderItem],
    candidates: list[NodeCandidate],
    max_nodes: int,
) -> list[AllocationDecision]:
    """
    Greedy least-cost split:
      For each SKU (sorted by difficulty = fewest nodes can fulfill),
      assign as much as possible from the cheapest node that has stock,
      repeating until the full quantity is covered or we run out of nodes.
    """
    decisions: list[AllocationDecision] = []
    # Use quantity_backordered if available (for partial re-sourcing), otherwise use full quantity
    # For backorder re-sourcing, items should already be filtered to only those with backordered > 0
    remaining: dict[str, int] = {
        item.sku: (item.quantity_backordered if hasattr(item, 'quantity_backordered') and item.quantity_backordered > 0 else item.quantity)
        for item in items
    }
    used_nodes: set[str] = set()

    # Sort SKUs: hardest to fulfill first (fewest candidates with stock)
    def fulfillability(sku):
        return sum(1 for c in candidates if c.inventory_by_sku.get(sku, 0) > 0)

    skus_sorted = sorted(remaining.keys(), key=fulfillability)

    for sku in skus_sorted:
        qty_needed = remaining[sku]
        if qty_needed <= 0:
            continue

        # Sort candidates by score (already done), attempt allocation
        for candidate in candidates:
            if qty_needed <= 0:
                break
            node_id = str(candidate.node.id)

            # Enforce max_nodes limit
            if len(used_nodes) >= max_nodes and node_id not in used_nodes:
                continue

            available = candidate.inventory_by_sku.get(sku, 0)
            if available <= 0:
                continue

            alloc_qty = min(available, qty_needed)
            decisions.append(AllocationDecision(
                node_id=node_id,
                node_code=candidate.node.code,
                sku=sku,
                quantity=alloc_qty,
                score=candidate.score,
                metadata={
                    "distance_miles": round(candidate.distance_miles, 2),
                    "estimated_cost": round(candidate.estimated_cost, 2),
                    "strategy": "LEAST_COST_SPLIT",
                },
            ))
            candidate.inventory_by_sku[sku] = available - alloc_qty
            qty_needed -= alloc_qty
            used_nodes.add(node_id)

        remaining[sku] = qty_needed

    return decisions


# ---------------------------------------------------------------------------
# Sourcing Engine
# ---------------------------------------------------------------------------

class SourcingEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def source_order(
        self,
        order: Order,
        force_strategy: Optional[SourcingStrategy] = None,
        skip_rule: bool = False,
    ) -> SourcingResult:
        t0 = time.time()
        # Capture IDs eagerly — after a rollback SQLAlchemy expires all attributes
        # and accessing order.id would trigger a lazy load (MissingGreenlet in async).
        _order_id = str(order.id)
        _order_number = order.order_number
        logger.info(f"Sourcing order {_order_id} ({_order_number})")

        # CRITICAL: Lock order to prevent concurrent sourcing conflicts
        result = await self.db.execute(
            select(Order)
            .with_for_update()  # Pessimistic lock
            .where(Order.id == order.id)
        )
        order = result.scalar_one()
        # Refresh line items with lock held
        await self.db.refresh(order, ['line_items'])

        # CRITICAL: Do not allow re-sourcing if order is already in fulfillment pipeline
        # (SOURCED, PICKING, PACKING, READY_TO_SHIP, SHIPPED, PARTIALLY_DELIVERED, etc)
        # This prevents the order from reverting to BACKORDERED mid-fulfillment
        if order.status in (
            OrderStatus.SOURCED,
            OrderStatus.PICKING,
            OrderStatus.PACKING,
            OrderStatus.READY_TO_SHIP,
            OrderStatus.SHIPPED,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.PARTIALLY_DELIVERED,
        ):
            logger.warning(
                f"Order {order.id} is already in sourcing pipeline ({order.status}); "
                f"skipping to prevent state reversion"
            )
            # Return empty result
            return SourcingResult(
                order_id=order.id,
                rule_applied=None,
                strategy_used=SourcingStrategy.DISTANCE_OPTIMAL,
                allocations=[],
                total_split_nodes=0,
                sourcing_score=0.0,
                processing_time_ms=(time.time() - t0) * 1000,
            )

        # 1. Select sourcing rule (skip when running E2E/test pipelines)
        rule = None if skip_rule else await self._select_rule(order)
        strategy = force_strategy or (rule.strategy if rule else SourcingStrategy.DISTANCE_OPTIMAL)

        # Check if this is a backorder re-sourcing (has backordered items)
        has_backorders = any(
            item.quantity_backordered and item.quantity_backordered > 0
            for item in order.line_items
        )
        
        # For backorder re-sourcing, force split allocation to use available inventory across multiple nodes
        if has_backorders and not force_strategy:
            logger.info(f"Backorder re-sourcing detected for {order.id}; forcing LEAST_COST_SPLIT strategy")
            strategy = SourcingStrategy.LEAST_COST_SPLIT

        # 1b. A/B experiment traffic splitting — may override strategy
        experiment_id: Optional[str] = None
        if not has_backorders and not force_strategy:
            experiment_id, strategy = await self._check_experiment(order, strategy)

        # 2. For STORE_NEAREST, restrict to retail stores
        allowed_node_types = None
        if strategy == SourcingStrategy.STORE_NEAREST:
            allowed_node_types = [NodeType.RETAIL_STORE, NodeType.DARK_STORE]

        # 3. Load all active nodes with inventory
        node_candidates = await self._build_candidates(order, rule, allowed_node_types)

        # 3b. If pickup_node_id is set, restrict sourcing to that specific node
        if order.pickup_node_id:
            pinned = [c for c in node_candidates if str(c.node.id) == str(order.pickup_node_id)]
            if pinned:
                node_candidates = pinned
                logger.info(f"Order {order.id}: pinned to pickup_node_id={order.pickup_node_id}")
            else:
                logger.warning(
                    f"Order {order.id}: pickup_node_id={order.pickup_node_id} not found in "
                    f"eligible candidates; falling back to all candidates"
                )

        if not node_candidates:
            logger.warning(f"No candidates found for order {order.id}")
            return SourcingResult(
                order_id=order.id,
                rule_applied=rule.name if rule else None,
                strategy_used=strategy,
                allocations=[],
                total_split_nodes=0,
                sourcing_score=0.0,
                processing_time_ms=(time.time() - t0) * 1000,
            )

        # 4. Score nodes (rule-based baseline)
        node_candidates = _score_nodes(node_candidates, strategy, rule)

        # 4b. AI scoring overlay for AI_ADAPTIVE / AI_HYBRID strategies
        ai_result: Optional[AIAdvisorResult] = None
        effective_strategy = strategy  # May fall back to DISTANCE_OPTIMAL

        if strategy in (SourcingStrategy.AI_ADAPTIVE, SourcingStrategy.AI_HYBRID):
            # Compute cluster features for context lookup
            amount = float(order.total_amount or 0)
            if amount < 50:
                amount_bucket = "0-50"
            elif amount < 100:
                amount_bucket = "50-100"
            elif amount < 250:
                amount_bucket = "100-250"
            elif amount < 500:
                amount_bucket = "250-500"
            else:
                amount_bucket = "500+"

            channel = order.channel.value if order.channel else "WEB"
            region = order.shipping_state or "UNKNOWN"
            ft = order.fulfillment_type.value if order.fulfillment_type else "SHIP_TO_HOME"

            advisor = AISourcingAdvisor()
            ai_result = await advisor.score_nodes(
                order=order,
                candidates=node_candidates,
                channel=channel,
                region=region,
                amount_bucket=amount_bucket,
                fulfillment_type=ft,
            )

            if ai_result.fallback_used:
                logger.info(
                    f"Order {order.id}: AI sourcing falling back to DISTANCE_OPTIMAL — "
                    f"{ai_result.fallback_reason}"
                )
                # Re-score with DISTANCE_OPTIMAL if we haven't already
                effective_strategy = SourcingStrategy.DISTANCE_OPTIMAL
                node_candidates = _score_nodes(node_candidates, effective_strategy, rule)
            else:
                # Blend AI score into node candidates
                ai_weight = (
                    1.0 if strategy == SourcingStrategy.AI_ADAPTIVE else 0.6
                )
                rule_weight = 1.0 - ai_weight

                ai_scores_by_node = {s.node_id: s for s in ai_result.scores}
                for c in node_candidates:
                    nid = str(c.node.id)
                    ai_s = ai_scores_by_node.get(nid)
                    if ai_s:
                        # Blend: AI weight * ai_score + rule_weight * rule_score
                        c.score = round(ai_weight * ai_s.ai_score + rule_weight * c.score, 4)
                    # If KubeAI didn't score this node, keep rule-based score unchanged

                # Re-sort by blended scores
                node_candidates = sorted(node_candidates, key=lambda c: c.score, reverse=True)
                logger.info(
                    f"Order {order.id}: AI scoring applied "
                    f"(strategy={strategy.value}, ai_confidence={ai_result.ai_confidence:.2f}, "
                    f"pattern_samples={ai_result.pattern_sample_size})"
                )

        # 5. Build allocation decisions
        # For backorder re-sourcing, only allocate items with actual backordered quantities
        items = order.line_items
        if has_backorders:
            items = [
                item for item in items
                if hasattr(item, 'quantity_backordered') and item.quantity_backordered > 0
            ]
        
        # CRITICAL FIX: Filter to only items that have inventory available
        # This allows partial allocation: if WIDGET-A has 1 unit and WIDGET-B has 0,
        # allocate the 1 unit of WIDGET-A instead of trying both and failing
        skus_with_inventory = set()
        for candidate in node_candidates:
            for sku, qty in candidate.inventory_by_sku.items():
                if qty > 0:
                    skus_with_inventory.add(sku)
        
        # CRITICAL: Separate items into those with available inventory vs those without
        items_with_inventory = [item for item in items if item.sku in skus_with_inventory]
        items_without_inventory = [item for item in items if item.sku not in skus_with_inventory]
        
        max_split = rule.max_split_nodes if rule else (3 if has_backorders else 1)

        # Attempt to allocate items that have available inventory
        if items_with_inventory:
            if strategy == SourcingStrategy.LEAST_COST_SPLIT:
                decisions = _compute_split_allocations(items_with_inventory, node_candidates, max_nodes=max_split)
            else:
                # Single-node: pick top-scored node that can cover available items
                decisions = self._single_node_allocation(items_with_inventory, node_candidates)
        else:
            decisions = []
        
        # Items without inventory will be marked as BACKORDERED in _persist_allocations
        logger.info(f"Order {_order_id}: {len(items_with_inventory)} items with inventory, {len(items_without_inventory)} items backordered from start")

        # 6. Persist allocations (within transaction)
        try:
            await self._persist_allocations(order, decisions, rule)
        except Exception as e:
            # Rollback on any persistence failure — after rollback SQLAlchemy expires
            # all ORM attributes, so use the pre-captured _order_id string.
            await self.db.rollback()
            logger.error(f"Allocation persistence failed for order {_order_id}: {e}")
            raise

        elapsed = (time.time() - t0) * 1000
        avg_score = sum(d.score for d in decisions) / max(len(decisions), 1)

        # Build decision trail: which nodes were evaluated and which were selected
        selected_node_ids = {d.node_id for d in decisions}
        ai_scores_map = (
            {s.node_id: s for s in ai_result.scores}
            if ai_result and not ai_result.fallback_used
            else {}
        )
        candidates_evaluated = []
        for c in node_candidates:
            nid = str(c.node.id)
            entry = {
                "node_id": nid,
                "node_code": c.node.code,
                "node_name": c.node.name,
                "node_type": c.node.node_type.value,
                "distance_miles": round(c.distance_miles, 2),
                "estimated_cost": round(c.estimated_cost, 2),
                "inventory_available": sum(c.inventory_by_sku.values()),
                "score": round(c.score, 4),
                "selected": nid in selected_node_ids,
            }
            if nid in ai_scores_map:
                ai_s = ai_scores_map[nid]
                entry["ai_score"] = round(ai_s.ai_score, 4)
                entry["ai_reasoning"] = ai_s.reasoning
            candidates_evaluated.append(entry)

        # Build rule details for audit trail
        reported_strategy = (effective_strategy if ai_result else strategy).value
        if rule:
            rule_details = {
                "id": str(rule.id),
                "name": rule.name,
                "priority": rule.priority,
                "strategy": reported_strategy,
                "conditions": rule.conditions or [],
                "max_split_nodes": rule.max_split_nodes,
                "max_distance_km": rule.max_distance_km,
                "allowed_node_types": rule.allowed_node_types or [],
                "required_capabilities": rule.required_capabilities or [],
            }
        else:
            rule_details = {
                "name": "Default (no rule matched)",
                "strategy": reported_strategy,
                "conditions": [],
                "max_split_nodes": 1,
            }

        # Append AI metadata if AI strategy was attempted
        if ai_result:
            rule_details["ai_sourcing"] = {
                "requested_strategy": strategy.value,
                "fallback_used": ai_result.fallback_used,
                "fallback_reason": ai_result.fallback_reason,
                "pattern_sample_size": ai_result.pattern_sample_size,
                "ai_confidence": round(ai_result.ai_confidence, 4),
                "model": ai_result.model_used,
            }

        # Append experiment tag to audit trail if this order was experiment-routed
        if experiment_id:
            rule_details["experiment_id"] = experiment_id

        # Build allocation list — include allocation_id for learning pipeline lookup
        # After _persist_allocations, the FulfillmentAllocation rows are flushed to DB.
        # Re-query them by (order_id, node_id, sku) to capture the auto-generated UUIDs.
        alloc_id_map: dict[tuple, str] = {}
        try:
            alloc_rows = await self.db.execute(
                select(FulfillmentAllocation).where(
                    FulfillmentAllocation.order_id == order.id
                )
            )
            for alloc_row in alloc_rows.scalars().all():
                key = (str(alloc_row.node_id), alloc_row.sku)
                alloc_id_map[key] = str(alloc_row.id)
        except Exception:
            pass  # allocation_id will be empty string if lookup fails

        allocation_list = []
        for d in decisions:
            alloc_id = alloc_id_map.get((d.node_id, d.sku), "")
            ai_s = ai_scores_map.get(d.node_id)
            alloc_entry = {
                "allocation_id": alloc_id,
                "node_id": d.node_id,
                "node_code": d.node_code,
                "sku": d.sku,
                "quantity": d.quantity,
                "score": round(d.score, 4),
                "metadata": d.metadata,
            }
            if ai_s:
                alloc_entry["ai_score"] = round(ai_s.ai_score, 4)
                alloc_entry["ai_reasoning"] = ai_s.reasoning
            allocation_list.append(alloc_entry)

        result = SourcingResult(
            order_id=order.id,
            rule_applied=rule.name if rule else None,
            strategy_used=effective_strategy if ai_result else strategy,
            allocations=allocation_list,
            total_split_nodes=len(set(d.node_id for d in decisions)),
            sourcing_score=round(avg_score, 4),
            processing_time_ms=round(elapsed, 2),
            rule_details=rule_details,
            candidates_evaluated=candidates_evaluated,
            experiment_id=experiment_id,
        )
        logger.info(
            f"Sourced order {order.id}: {len(decisions)} allocations across "
            f"{result.total_split_nodes} nodes in {elapsed:.1f}ms"
        )
        return result

    # ------------------------------------------------------------------ helpers

    async def _check_experiment(
        self,
        order: Order,
        current_strategy: SourcingStrategy,
    ) -> tuple[Optional[str], SourcingStrategy]:
        """
        Check if a running A/B experiment applies to this order.
        Returns (experiment_id, strategy_to_use).

        Traffic split: traffic_split_pct % go to strategy_b, rest to strategy_a.
        If multiple experiments match, the first (by created_at) wins.
        Non-fatal: any error returns (None, current_strategy).
        """
        try:
            from app.models.postgres.ai_models import AIExperiment, ExperimentStatus
            result = await self.db.execute(
                select(AIExperiment)
                .where(AIExperiment.status == ExperimentStatus.RUNNING)
                .order_by(AIExperiment.started_at.asc())
            )
            experiments = result.scalars().all()

            order_channel = order.channel.value if order.channel else ""
            order_ft = order.fulfillment_type.value if order.fulfillment_type else ""
            order_amount = float(order.total_amount or 0)
            order_region = order.shipping_state or ""

            for exp in experiments:
                fc = exp.filter_conditions or {}
                # Check filter_conditions: all specified keys must match
                if fc.get("channel") and fc["channel"] != order_channel:
                    continue
                if fc.get("fulfillment_type") and fc["fulfillment_type"] != order_ft:
                    continue
                if fc.get("region") and fc["region"] != order_region:
                    continue
                if fc.get("amount_min") is not None and order_amount < float(fc["amount_min"]):
                    continue
                if fc.get("amount_max") is not None and order_amount >= float(fc["amount_max"]):
                    continue

                # This experiment matches — randomly assign arm
                exp_id = str(exp.id)
                if random.random() * 100 < exp.traffic_split_pct:
                    # Route to strategy_b
                    try:
                        override = SourcingStrategy(exp.strategy_b)
                        logger.info(
                            f"Experiment {exp_id}: order {order.id} → strategy_b ({exp.strategy_b})"
                        )
                        return exp_id, override
                    except ValueError:
                        pass
                else:
                    # Route to strategy_a (keep current strategy)
                    logger.debug(
                        f"Experiment {exp_id}: order {order.id} → strategy_a ({exp.strategy_a})"
                    )
                    return exp_id, current_strategy

        except Exception as exc:
            logger.warning(f"_check_experiment failed (non-fatal): {exc}")

        return None, current_strategy

    async def _select_rule(self, order: Order) -> Optional[SourcingRule]:
        result = await self.db.execute(
            select(SourcingRule)
            .where(SourcingRule.is_active == True)
            .order_by(SourcingRule.priority.asc())
        )
        rules = result.scalars().all()
        for rule in rules:
            if _rule_matches(rule, order):
                logger.debug(f"Rule matched: {rule.name} (priority {rule.priority})")
                return rule
        logger.debug("No rule matched; using default strategy")
        return None

    async def _build_candidates(
        self,
        order: Order,
        rule: Optional[SourcingRule],
        allowed_node_types: Optional[list] = None,
    ) -> list[NodeCandidate]:
        """Load nodes + their inventory and build NodeCandidate objects."""
        node_query = select(FulfillmentNode).where(FulfillmentNode.status == NodeStatus.ACTIVE)
        if allowed_node_types:
            node_query = node_query.where(FulfillmentNode.node_type.in_(allowed_node_types))

        node_result = await self.db.execute(node_query)
        all_nodes = node_result.scalars().all()
        # Apply rule filters
        filtered_nodes = _filter_nodes(all_nodes, rule, order)
        if not filtered_nodes:
            return []

        # Load inventory for all needed SKUs at once
        skus = [item.sku for item in order.line_items]
        node_ids = [n.id for n in filtered_nodes]

        inv_result = await self.db.execute(
            select(InventoryItem).where(
                and_(
                    InventoryItem.node_id.in_(node_ids),
                    InventoryItem.sku.in_(skus),
                    InventoryItem.is_active == True,
                )
            )
        )
        inventory_rows = inv_result.scalars().all()

        # Build node_id -> {sku: qty} map
        inv_map: dict[str, dict[str, int]] = {}
        for inv in inventory_rows:
            nid = str(inv.node_id)
            if nid not in inv_map:
                inv_map[nid] = {}
            inv_map[nid][inv.sku] = inv.quantity_available

        # Customer location
        cust_lat = order.shipping_latitude
        cust_lon = order.shipping_longitude
        if cust_lat is None or cust_lon is None:
            logger.warning(
                f"Order {order.id} has no shipping coordinates; "
                "distances will be estimated from geographic center of US"
            )
            cust_lat = 39.5  # Geographic center of the contiguous US
            cust_lon = -98.35

        candidates = []
        for node in filtered_nodes:
            inv_by_sku = inv_map.get(str(node.id), {})
            # Skip nodes with no relevant inventory
            if not any(inv_by_sku.get(s, 0) > 0 for s in skus):
                continue

            dist_miles = haversine_miles(cust_lat, cust_lon, node.latitude, node.longitude)

            # Estimate shipping cost: base rate + per-mile rate * multiplier
            base_cost = 5.0
            per_mile_rate = 0.03
            est_cost = (base_cost + per_mile_rate * dist_miles) * node.shipping_cost_multiplier

            # Distance filter (max_distance_km stored in rule, convert miles → km for comparison)
            if rule and rule.max_distance_km and dist_miles > rule.max_distance_km * 0.621371:
                continue

            candidates.append(NodeCandidate(
                node=node,
                inventory_by_sku=inv_by_sku,
                distance_miles=dist_miles,
                estimated_cost=est_cost,
            ))

        return candidates

    def _single_node_allocation(
        self,
        items: list[OrderItem],
        candidates: list[NodeCandidate],
    ) -> list[AllocationDecision]:
        """Pick the highest-scored node that can fulfill all items, or fall back to split."""
        # For partial re-sourcing, use backordered quantity if available
        def get_qty_to_allocate(item):
            return (item.quantity_backordered if hasattr(item, 'quantity_backordered') and item.quantity_backordered > 0 
                    else item.quantity)
        
        for candidate in candidates:
            if all(
                candidate.inventory_by_sku.get(item.sku, 0) >= get_qty_to_allocate(item)
                for item in items
            ):
                return [
                    AllocationDecision(
                        node_id=str(candidate.node.id),
                        node_code=candidate.node.code,
                        sku=item.sku,
                        quantity=get_qty_to_allocate(item),
                        score=candidate.score,
                        metadata={
                            "distance_miles": round(candidate.distance_miles, 2),
                            "estimated_cost": round(candidate.estimated_cost, 2),
                            "strategy": "single_node",
                        },
                    )
                    for item in items
                ]

        # Fallback: split across best candidates
        logger.info("No single node can fulfill all items; falling back to split")
        return _compute_split_allocations(items, candidates, max_nodes=3)

    async def _persist_allocations(
        self,
        order: Order,
        decisions: list[AllocationDecision],
        rule: Optional[SourcingRule],
    ):
        """Write FulfillmentAllocation rows and update order status.
        
        Prevents duplicate allocations by checking if order items already have
        sufficient total allocation for their full quantity.
        """
        if not decisions:
            return

        # Group decisions by (node_id, sku) to find matching order items
        item_map = {item.sku: item for item in order.line_items}

        # Check for existing allocations to calculate how much more quantity each item needs
        existing_allocations = await self.db.execute(
            select(FulfillmentAllocation).where(
                FulfillmentAllocation.order_id == order.id
            )
        )
        existing_allocs_list = existing_allocations.scalars().all()
        
        # Calculate quantity already allocated per SKU
        allocated_by_sku = {}
        for alloc in existing_allocs_list:
            if alloc.sku not in allocated_by_sku:
                allocated_by_sku[alloc.sku] = 0
            allocated_by_sku[alloc.sku] += alloc.quantity_allocated

        new_allocations = []
        
        for decision in decisions:
            item = item_map.get(decision.sku)
            if not item:
                logger.warning(f"No order item found for SKU {decision.sku} in order {order.id}")
                continue
            
            # Calculate how much more quantity this item needs
            already_allocated = allocated_by_sku.get(decision.sku, 0)
            needed = item.quantity - already_allocated
            
            # Skip if item already has enough allocation
            if needed <= 0:
                logger.info(
                    f"Order {order.id} item {decision.sku}: already has {already_allocated} "
                    f"allocated (needs {item.quantity}) - skipping duplicate allocation"
                )
                continue
            
            # Allocate only what's needed (don't exceed item quantity)
            quantity_to_allocate = min(decision.quantity, needed)
            
            alloc = FulfillmentAllocation(
                order_id=order.id,
                order_item_id=item.id if item else None,
                node_id=decision.node_id,
                sku=decision.sku,
                quantity_allocated=quantity_to_allocate,
                status=AllocationStatus.ALLOCATED,
                sourcing_score=decision.score,
                sourcing_metadata=decision.metadata,
            )
            self.db.add(alloc)
            new_allocations.append(alloc)
            allocated_by_sku[decision.sku] = already_allocated + quantity_to_allocate

        # Flush new allocations to database BEFORE updating counters via SQL
        # Critical: _update_item_counters uses SQL to SUM from fulfillment_allocations,
        # so new allocations must be persisted first
        await self.db.flush()

        # Update order_items counters to match actual allocations
        await self._update_item_counters(order)

        # Determine final status based on allocation completeness
        fully_allocated = all(
            item.quantity_allocated >= item.quantity 
            for item in order.line_items
        )
        
        from app.models.postgres.order_models import OrderStatus
        from datetime import datetime
        
        if fully_allocated:
            # Order is fully allocated - clear backorder flags and move to SOURCED
            order.status = OrderStatus.SOURCED
            for item in order.line_items:
                if item.quantity_backordered:
                    logger.info(f"Clearing backordered flag for {item.sku} (was {item.quantity_backordered})")
                    item.quantity_backordered = 0
        else:
            # Partial allocation - stay in BACKORDERED
            order.status = OrderStatus.BACKORDERED
            # Update backordered quantities
            for item in order.line_items:
                unallocated = item.quantity - item.quantity_allocated
                if unallocated > 0:
                    item.quantity_backordered = unallocated
                    logger.info(f"Updated {item.sku} backordered count to {unallocated}")
        
        if rule:
            order.sourcing_rule_id = rule.id
        order.sourcing_completed_at = datetime.utcnow()

        # Reserve inventory based on allocations actually created (not original decisions)
        await self._reserve_inventory_from_allocations(new_allocations)

        await self.db.flush()

    async def _reserve_inventory_from_allocations(self, allocations: list[FulfillmentAllocation]):
        """Decrement quantity_available and increment quantity_reserved based on actual allocations.
        
        CRITICAL: Checks inventory availability before reserving to prevent over-allocation.
        Raises exception if insufficient inventory remains (prevents concurrent depletion).
        """
        for alloc in allocations:
            result = await self.db.execute(
                select(InventoryItem)
                .with_for_update()  # Lock inventory row
                .where(
                    and_(
                        InventoryItem.node_id == alloc.node_id,
                        InventoryItem.sku == alloc.sku,
                    )
                )
            )
            inv = result.scalar_one_or_none()
            if not inv:
                logger.warning(f"Inventory item not found for {alloc.sku} at {alloc.node_id}")
                continue
            
            # Check if reservation would exceed on-hand quantity
            new_reserved = inv.quantity_reserved + alloc.quantity_allocated
            if new_reserved > inv.quantity_on_hand:
                logger.error(
                    f"INVENTORY CONFLICT: Cannot reserve {alloc.quantity_allocated} of {alloc.sku} "
                    f"at {alloc.node_id}; would exceed on-hand "
                    f"({new_reserved} > {inv.quantity_on_hand}). "
                    f"Current: reserved={inv.quantity_reserved}, on_hand={inv.quantity_on_hand}. "
                    f"Order: {alloc.order_id}"
                )
                raise Exception(
                    f"Insufficient inventory for {alloc.sku} at {alloc.node_id}: "
                    f"would allocate {new_reserved} but only {inv.quantity_on_hand} on hand"
                )
            
            inv.quantity_reserved = new_reserved
            inv.quantity_available = max(0, inv.quantity_on_hand - inv.quantity_reserved)
            logger.info(
                f"Reserved {alloc.quantity_allocated} of {alloc.sku} at {inv.node_id}; "
                f"available now {inv.quantity_available} (on_hand={inv.quantity_on_hand}, "
                f"reserved={inv.quantity_reserved})"
            )

    async def _update_item_counters(self, order: Order):
        """Recalculate order_items counters atomically using SQL.
        
        CRITICAL: Uses direct SQL UPDATE to make counter synchronization atomic
        and prevent race conditions when multiple sourcing tasks run concurrently.
        This ensures quantity_allocated stays in sync with fulfillment_allocations.
        """
        # Use raw SQL for atomic update - sum allocations and update in one transaction
        from sqlalchemy import text
        
        await self.db.execute(
            text(
                """
                UPDATE order_items 
                SET quantity_allocated = COALESCE(
                    (SELECT SUM(quantity_allocated)
                     FROM fulfillment_allocations
                     WHERE order_item_id = order_items.id),
                    0
                )
                WHERE order_id = :order_id
                """
            ),
            {"order_id": order.id}
        )
        
        # CRITICAL: Expire all items to force fresh load from DB
        # The refresh alone may not clear SQLAlchemy's expired state tracking
        for item in order.line_items:
            self.db.expunge(item)
        
        # Refresh order_items to get updated values from database
        await self.db.refresh(order, ['line_items'])
        
        for item in order.line_items:
            alloc_result = await self.db.execute(
                select(FulfillmentAllocation)
                .where(FulfillmentAllocation.order_item_id == item.id)
            )
            allocs = alloc_result.scalars().all()
            logger.debug(
                f"Synchronized {item.sku}: quantity_allocated={item.quantity_allocated} "
                f"from {len(allocs)} allocations"
            )

    async def validate_and_repair_order(self, order: Order) -> dict:
        """Validate order counters and repair any mismatches.
        
        Returns a dict with:
        - is_valid: bool - whether counters match allocations
        - issues: list - any issues found
        - repaired: bool - whether repairs were made
        """
        issues = []
        
        # Get all allocations for this order
        allocations = await self.db.execute(
            select(FulfillmentAllocation).where(
                FulfillmentAllocation.order_id == order.id
            )
        )
        
        alloc_by_sku = {}
        for alloc in allocations.scalars().all():
            if alloc.sku not in alloc_by_sku:
                alloc_by_sku[alloc.sku] = {"count": 0, "total": 0}
            alloc_by_sku[alloc.sku]["count"] += 1
            alloc_by_sku[alloc.sku]["total"] += alloc.quantity_allocated
        
        # Check each line item
        repaired = False
        for item in order.line_items:
            expected_allocated = alloc_by_sku.get(item.sku, {}).get("total", 0)
            
            if item.quantity_allocated != expected_allocated:
                issues.append({
                    "type": "counter_mismatch",
                    "sku": item.sku,
                    "order_item_allocated": item.quantity_allocated,
                    "actual_allocations": expected_allocated,
                })
                
                # Auto-repair
                item.quantity_allocated = expected_allocated
                repaired = True
                logger.warning(
                    f"Repaired counter mismatch for {item.sku} in order {order.id}: "
                    f"{item.quantity_allocated} -> {expected_allocated}"
                )
        
        is_valid = len(issues) == 0
        return {
            "is_valid": is_valid,
            "issues": issues,
            "repaired": repaired,
        }

