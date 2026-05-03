"""
AI Sourcing Advisor — Phase 2 of the AI-native OMS.

Uses KubeAI to score fulfillment node candidates using:
  - Historical sourcing patterns (from MongoDB sourcing_patterns)
  - Rolling node performance metrics (from MongoDB node_performance_metrics)
  - Order context (channel, region, amount, fulfillment type)

Fallback to DISTANCE_OPTIMAL when:
  - Best matching pattern has fewer than MIN_PATTERN_SAMPLES samples
  - KubeAI response is invalid, empty, or times out
  - All AI scores are below MIN_CONFIDENCE_THRESHOLD

The AI score is NOT a replacement — it blends with the existing rule-based score.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Thresholds
MIN_PATTERN_SAMPLES = 10      # Require this many historical samples before trusting patterns
MIN_CONFIDENCE_THRESHOLD = 0.4  # If max AI score < this, fall back to rule-based

# Score blending weights (AI_ADAPTIVE and AI_HYBRID differ only in blend ratio)
ADAPTIVE_AI_WEIGHT = 1.0      # AI_ADAPTIVE: pure AI score (KubeAI is primary)
HYBRID_AI_WEIGHT = 0.6        # AI_HYBRID: 60% AI + 40% rule-based


@dataclass
class AINodeScore:
    node_id: str
    ai_score: float          # 0.0 – 1.0
    reasoning: str
    confidence: float = 1.0  # Internal confidence in the score


@dataclass
class AIAdvisorResult:
    scores: list[AINodeScore]
    fallback_used: bool
    fallback_reason: str
    pattern_sample_size: int
    ai_confidence: float       # Average confidence across all scores
    model_used: str = "claude-haiku-4-5-20251001"


class AISourcingAdvisor:
    """
    Wraps the KubeAI API call for node scoring.
    All public methods are async-safe and non-raising — failures return fallback_used=True.
    """

    def __init__(self):
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    async def score_nodes(
        self,
        order,                   # app.models.postgres.order_models.Order
        candidates: list,        # list[NodeCandidate]
        channel: str,
        region: str,
        amount_bucket: str,
        fulfillment_type: str,
    ) -> AIAdvisorResult:
        """
        Score each candidate node for the given order using KubeAI.
        Returns an AIAdvisorResult — always succeeds (uses fallback on error).
        """
        if not self._api_key:
            return AIAdvisorResult(
                scores=[], fallback_used=True,
                fallback_reason="ANTHROPIC_API_KEY not configured",
                pattern_sample_size=0, ai_confidence=0.0,
            )

        # 1. Fetch context from MongoDB
        patterns, node_metrics, sample_size = await self._fetch_context(
            channel, region, amount_bucket, fulfillment_type,
            [str(c.node.id) for c in candidates],
        )

        # 2. Confidence check: not enough historical data
        if sample_size < MIN_PATTERN_SAMPLES:
            return AIAdvisorResult(
                scores=[], fallback_used=True,
                fallback_reason=f"Insufficient pattern data (samples={sample_size}, need {MIN_PATTERN_SAMPLES})",
                pattern_sample_size=sample_size, ai_confidence=0.0,
            )

        # 3. Build the prompt
        prompt = self._build_prompt(order, candidates, patterns, node_metrics, channel, region)

        # 4. Call KubeAI
        try:
            raw_scores = await self._call_kubeai(prompt)
        except Exception as exc:
            logger.warning(f"AISourcingAdvisor KubeAI call failed: {exc}")
            return AIAdvisorResult(
                scores=[], fallback_used=True,
                fallback_reason=f"KubeAI API error: {type(exc).__name__}",
                pattern_sample_size=sample_size, ai_confidence=0.0,
            )

        if not raw_scores:
            return AIAdvisorResult(
                scores=[], fallback_used=True,
                fallback_reason="KubeAI returned empty or unparseable response",
                pattern_sample_size=sample_size, ai_confidence=0.0,
            )

        # 5. Validate scores
        ai_node_scores = []
        for item in raw_scores:
            node_id = str(item.get("node_id", ""))
            score = float(item.get("score", 0.0))
            reason = str(item.get("reason", ""))
            # Clamp score to [0, 1]
            score = max(0.0, min(1.0, score))
            ai_node_scores.append(AINodeScore(node_id=node_id, ai_score=score, reasoning=reason))

        if not ai_node_scores:
            return AIAdvisorResult(
                scores=[], fallback_used=True,
                fallback_reason="No valid node scores in KubeAI response",
                pattern_sample_size=sample_size, ai_confidence=0.0,
            )

        max_score = max(s.ai_score for s in ai_node_scores)
        if max_score < MIN_CONFIDENCE_THRESHOLD:
            return AIAdvisorResult(
                scores=ai_node_scores, fallback_used=True,
                fallback_reason=f"Max AI score too low ({max_score:.2f} < {MIN_CONFIDENCE_THRESHOLD})",
                pattern_sample_size=sample_size, ai_confidence=max_score,
            )

        avg_confidence = sum(s.ai_score for s in ai_node_scores) / len(ai_node_scores)
        return AIAdvisorResult(
            scores=ai_node_scores, fallback_used=False,
            fallback_reason="",
            pattern_sample_size=sample_size, ai_confidence=avg_confidence,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_context(
        self,
        channel: str,
        region: str,
        amount_bucket: str,
        fulfillment_type: str,
        candidate_node_ids: list[str],
    ) -> tuple[list[dict], list[dict], int]:
        """Fetch matching patterns and node metrics from MongoDB.

        Creates a short-lived Motor client per call because this method runs
        inside a Celery worker (asyncio.run context), where the app-level
        shared MongoDB client is not initialized.
        """
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            from app.config import settings

            client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=3000)
            try:
                db = client[settings.MONGODB_AI_DB]

                # Look for the matching cluster pattern (exact + relaxed fallbacks)
                cluster_key = f"{channel}|{region}|{amount_bucket}|{fulfillment_type}"
                pattern_doc = await db.sourcing_patterns.find_one({"cluster_key": cluster_key})

                # Relaxed fallback: same channel + fulfillment_type, any region/amount
                patterns = []
                sample_size = 0
                if pattern_doc:
                    patterns.append(pattern_doc)
                    sample_size = pattern_doc.get("sample_count", 0)
                else:
                    # Broader match: channel + fulfillment_type only
                    cursor = db.sourcing_patterns.find(
                        {"channel": channel, "fulfillment_type": fulfillment_type},
                        limit=3,
                    ).sort("sample_count", -1)
                    broader = await cursor.to_list(length=3)
                    patterns = broader
                    sample_size = sum(p.get("sample_count", 0) for p in broader)

                # Node performance metrics (7-day window for responsiveness)
                node_metrics = []
                if candidate_node_ids:
                    cursor = db.node_performance_metrics.find(
                        {"node_id": {"$in": candidate_node_ids}, "period_days": 7}
                    )
                    node_metrics = await cursor.to_list(length=50)

                return patterns, node_metrics, sample_size
            finally:
                client.close()

        except Exception as exc:
            logger.warning(f"AISourcingAdvisor: MongoDB context fetch failed: {exc}")
            return [], [], 0

    def _build_prompt(
        self,
        order,
        candidates: list,
        patterns: list[dict],
        node_metrics: list[dict],
        channel: str,
        region: str,
    ) -> str:
        """Build the structured KubeAI prompt for node scoring."""
        # Serialize candidates
        cand_list = []
        for c in candidates:
            cand_list.append({
                "node_id": str(c.node.id),
                "node_name": c.node.name,
                "node_type": c.node.node_type.value,
                "distance_miles": round(c.distance_miles, 1),
                "estimated_cost": round(c.estimated_cost, 2),
                "inventory_available": sum(c.inventory_by_sku.values()),
            })

        # Serialize patterns (keep small — top 3)
        pattern_summaries = []
        for p in patterns[:3]:
            top_nodes = p.get("node_performance", [])[:3]
            pattern_summaries.append({
                "cluster": p.get("cluster_key"),
                "samples": p.get("sample_count", 0),
                "top_nodes": [
                    {
                        "node_id": n.get("node_id"),
                        "node_name": n.get("node_name"),
                        "avg_outcome_score": n.get("avg_outcome_score"),
                        "avg_delivery_hours": n.get("avg_delivery_hours"),
                        "selections": n.get("selection_count"),
                    }
                    for n in top_nodes
                ],
            })

        # Serialize node metrics (keep small)
        metrics_by_node = {m["node_id"]: m for m in node_metrics}
        metric_summaries = []
        for c in candidates:
            nid = str(c.node.id)
            m = metrics_by_node.get(nid, {})
            if m:
                metric_summaries.append({
                    "node_id": nid,
                    "node_name": c.node.name,
                    "orders_7d": m.get("orders_fulfilled"),
                    "avg_outcome_score_7d": m.get("avg_outcome_score"),
                    "avg_delivery_hours_7d": m.get("avg_delivery_hours"),
                    "backorder_rate_pct": m.get("backorder_rate_pct"),
                })

        amount = float(order.total_amount or 0)
        order_summary = {
            "channel": channel,
            "fulfillment_type": order.fulfillment_type.value if order.fulfillment_type else "SHIP_TO_HOME",
            "customer_region": region,
            "order_amount": f"${amount:.2f}",
            "sku_count": len(order.line_items),
        }

        return f"""You are an OMS sourcing engine scoring fulfillment nodes for an order.
Score each node 0.0–1.0 (higher = better fit). Use the historical data to identify which nodes consistently perform well for similar orders.

ORDER:
{json.dumps(order_summary, indent=2)}

HISTORICAL PATTERNS (similar orders):
{json.dumps(pattern_summaries, indent=2)}

NODE PERFORMANCE (last 7 days):
{json.dumps(metric_summaries, indent=2)}

CANDIDATES:
{json.dumps(cand_list, indent=2)}

Scoring guidance:
- Prefer nodes with high historical avg_outcome_score for this order type
- Penalize nodes with high backorder_rate_pct or slow avg_delivery_hours
- Consider distance and cost as secondary factors
- If a node has no historical data, score it based on distance/cost/inventory only

Respond ONLY with a JSON array, no other text:
[{{"node_id": "...", "score": 0.0, "reason": "one sentence"}}]"""

    async def _call_kubeai(self, prompt: str) -> list[dict]:
        """Call KubeAI and parse the JSON response. Returns empty list on any error."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        try:
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",  # Haiku: fast + cheap for structured scoring
                max_tokens=1024,
                timeout=10.0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()

            # Extract JSON array from response
            start = text.find("[")
            end = text.rfind("]") + 1
            if start == -1 or end == 0:
                logger.warning(f"AISourcingAdvisor: no JSON array in response: {text[:200]}")
                return []

            return json.loads(text[start:end])

        except json.JSONDecodeError as exc:
            logger.warning(f"AISourcingAdvisor: JSON parse error: {exc}")
            return []
        finally:
            await client.close()
