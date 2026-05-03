"""
Pattern Discovery Service — Phase 3 of the AI-native OMS.

Aggregates labeled sourcing outcomes into pattern clusters and generates
AI proposals when AI_ADAPTIVE shows a statistically significant advantage
over the DISTANCE_OPTIMAL baseline.

Proposal generation thresholds:
  MIN_CLUSTER_SAMPLES = 50    — total labeled outcomes needed in cluster
  MIN_AI_SAMPLES = 10         — AI_ADAPTIVE-specific samples needed
  MIN_IMPROVEMENT_PCT = 10.0  — AI must outperform baseline by ≥10%

Safety: proposals are always PENDING. Nothing is applied without human approval.
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MIN_CLUSTER_SAMPLES = 50
MIN_AI_SAMPLES = 10
MIN_IMPROVEMENT_PCT = 10.0  # AI must beat DISTANCE_OPTIMAL by this % to qualify


class PatternDiscoveryService:
    """
    Aggregates labeled sourcing outcomes into cluster patterns and generates
    sourcing rule proposals for human review.

    Designed to run inside an asyncio.run() wrapper from the Celery task.
    All public methods are non-raising — failures are logged and operation continues.
    """

    async def run(self, mongo_db, pg_session) -> dict:
        """
        Full discovery pipeline: aggregate patterns → compare strategies → propose rules.
        Returns a summary dict with counts.
        """
        clusters_updated = 0
        proposals_created = 0

        try:
            clusters_updated = await self._aggregate_patterns(mongo_db)
        except Exception as exc:
            logger.error(f"PatternDiscovery: aggregation failed: {exc}")

        try:
            proposals_created = await self._generate_proposals(mongo_db, pg_session)
        except Exception as exc:
            logger.error(f"PatternDiscovery: proposal generation failed: {exc}")

        return {
            "clusters_updated": clusters_updated,
            "proposals_created": proposals_created,
        }

    # ------------------------------------------------------------------
    # Private: aggregation
    # ------------------------------------------------------------------

    async def _aggregate_patterns(self, db) -> int:
        """
        Group all labeled outcomes by (cluster_key, node_id) and upsert into
        the sourcing_patterns MongoDB collection.
        Returns count of clusters updated.
        """
        pipeline = [
            {
                "$match": {
                    "outcome_score": {"$exists": True},
                    "cluster_key": {"$exists": True},
                }
            },
            {
                "$group": {
                    "_id": {
                        "cluster_key": "$cluster_key",
                        "node_id": "$node_id",
                    },
                    "avg_outcome_score": {"$avg": "$outcome_score"},
                    "avg_delivery_hours": {"$avg": "$actual_delivery_hours"},
                    "avg_cost": {"$avg": "$predicted_cost"},
                    "selection_count": {"$sum": 1},
                    "node_name": {"$first": "$node_name"},
                    "channel": {"$first": "$channel"},
                    "region": {"$first": "$region"},
                    "amount_bucket": {"$first": "$amount_bucket"},
                    "fulfillment_type": {"$first": "$fulfillment_type"},
                }
            },
            {"$sort": {"avg_outcome_score": -1}},
        ]
        results = await db.sourcing_outcomes.aggregate(pipeline).to_list(length=10000)

        # Group row results into cluster documents
        clusters: dict = {}
        for r in results:
            ck = r["_id"]["cluster_key"]
            if ck not in clusters:
                clusters[ck] = {
                    "cluster_key": ck,
                    "channel": r.get("channel"),
                    "region": r.get("region"),
                    "amount_bucket": r.get("amount_bucket"),
                    "fulfillment_type": r.get("fulfillment_type"),
                    "node_performance": [],
                    "sample_count": 0,
                    "computed_at": datetime.utcnow(),
                }
            clusters[ck]["node_performance"].append({
                "node_id": r["_id"]["node_id"],
                "node_name": r.get("node_name"),
                "avg_outcome_score": round(r["avg_outcome_score"], 4),
                "avg_delivery_hours": round(r.get("avg_delivery_hours") or 0, 1),
                "avg_cost": round(r.get("avg_cost") or 0, 2),
                "selection_count": r["selection_count"],
            })
            clusters[ck]["sample_count"] += r["selection_count"]

        # Sort node_performance desc and upsert each cluster
        for ck, cluster in clusters.items():
            sorted_nodes = sorted(
                cluster["node_performance"],
                key=lambda n: n["avg_outcome_score"],
                reverse=True,
            )
            cluster["node_performance"] = sorted_nodes
            cluster["best_node_id"] = sorted_nodes[0]["node_id"] if sorted_nodes else None
            cluster["computed_at"] = datetime.utcnow()

            await db.sourcing_patterns.replace_one(
                {"cluster_key": ck},
                cluster,
                upsert=True,
            )

        return len(clusters)

    # ------------------------------------------------------------------
    # Private: strategy comparison
    # ------------------------------------------------------------------

    async def _compare_strategies(self, db) -> list[dict]:
        """
        Compare AI_ADAPTIVE vs DISTANCE_OPTIMAL outcome scores per cluster.
        Returns qualifying clusters where AI shows a statistically meaningful advantage.
        """
        pipeline = [
            {
                "$match": {
                    "outcome_score": {"$exists": True},
                    "cluster_key": {"$exists": True},
                    "strategy_used": {"$in": ["AI_ADAPTIVE", "DISTANCE_OPTIMAL"]},
                }
            },
            {
                "$group": {
                    "_id": {
                        "cluster_key": "$cluster_key",
                        "strategy_used": "$strategy_used",
                    },
                    "avg_outcome_score": {"$avg": "$outcome_score"},
                    "sample_count": {"$sum": 1},
                    "channel": {"$first": "$channel"},
                    "region": {"$first": "$region"},
                    "amount_bucket": {"$first": "$amount_bucket"},
                    "fulfillment_type": {"$first": "$fulfillment_type"},
                }
            },
        ]
        results = await db.sourcing_outcomes.aggregate(pipeline).to_list(length=5000)

        # Pivot: cluster_key → { strategy → {avg_score, samples}, metadata }
        by_cluster: dict = {}
        for r in results:
            ck = r["_id"]["cluster_key"]
            strategy = r["_id"]["strategy_used"]
            if ck not in by_cluster:
                by_cluster[ck] = {
                    "cluster_key": ck,
                    "channel": r.get("channel"),
                    "region": r.get("region"),
                    "amount_bucket": r.get("amount_bucket"),
                    "fulfillment_type": r.get("fulfillment_type"),
                }
            by_cluster[ck][strategy] = {
                "avg_outcome_score": r["avg_outcome_score"],
                "sample_count": r["sample_count"],
            }

        # Filter: keep only clusters where AI is meaningfully better
        qualifying = []
        for ck, data in by_cluster.items():
            ai_data = data.get("AI_ADAPTIVE")
            baseline_data = data.get("DISTANCE_OPTIMAL")

            if not ai_data or not baseline_data:
                continue  # Need both strategies to compare

            ai_score = ai_data["avg_outcome_score"]
            baseline_score = baseline_data["avg_outcome_score"]
            ai_samples = ai_data["sample_count"]
            total_samples = ai_samples + baseline_data["sample_count"]

            if total_samples < MIN_CLUSTER_SAMPLES:
                continue
            if ai_samples < MIN_AI_SAMPLES:
                continue

            if baseline_score > 0:
                improvement_pct = (ai_score - baseline_score) / baseline_score * 100
            else:
                improvement_pct = 100.0 if ai_score > 0 else 0.0

            if improvement_pct < MIN_IMPROVEMENT_PCT:
                continue

            qualifying.append({
                "cluster_key": ck,
                "channel": data.get("channel"),
                "region": data.get("region"),
                "amount_bucket": data.get("amount_bucket"),
                "fulfillment_type": data.get("fulfillment_type"),
                "ai_avg_score": round(ai_score, 4),
                "baseline_avg_score": round(baseline_score, 4),
                "improvement_pct": round(improvement_pct, 1),
                "ai_samples": ai_samples,
                "baseline_samples": baseline_data["sample_count"],
                "total_samples": total_samples,
            })

        return qualifying

    # ------------------------------------------------------------------
    # Private: proposal generation
    # ------------------------------------------------------------------

    async def _generate_proposals(self, db, session) -> int:
        """
        For each qualifying cluster, create a pending AIProposal sourcing rule
        if one does not already exist for that cluster.
        Returns count of new proposals created.
        """
        qualifying = await self._compare_strategies(db)
        if not qualifying:
            return 0

        from app.models.postgres.ai_models import AIProposal, ProposalType, ProposalStatus
        from sqlalchemy import select

        created = 0
        for item in qualifying:
            ck = item["cluster_key"]

            # Skip if a pending or approved proposal already covers this cluster
            existing_result = await session.execute(
                select(AIProposal).where(
                    AIProposal.proposal_type == ProposalType.SOURCING_RULE,
                    AIProposal.status.in_([ProposalStatus.PENDING, ProposalStatus.APPROVED]),
                    AIProposal.title.like(f"%{ck}%"),
                )
            )
            if existing_result.scalar_one_or_none():
                logger.debug(f"PatternDiscovery: skipping duplicate proposal for cluster {ck}")
                continue

            conditions = self._build_conditions(item)
            proposal_data = {
                "name": f"AI Adaptive Sourcing — {ck}",
                "description": (
                    f"Apply AI_ADAPTIVE strategy for orders matching cluster: {ck}. "
                    f"Based on {item['ai_samples']} AI-sourced orders vs "
                    f"{item['baseline_samples']} baseline orders."
                ),
                "priority": 50,  # Higher priority than default 100
                "strategy": "AI_ADAPTIVE",
                "conditions": conditions,
                "max_split_nodes": 3,
                "is_active": False,   # Starts inactive — admin enables after reviewing
                "cluster_key": ck,   # Stored for deduplication lookup
            }

            # Confidence: function of both improvement margin and sample size
            improvement_confidence = min(item["improvement_pct"] / 50, 0.6)  # cap at 0.6 at 50% improvement
            sample_confidence = min(item["ai_samples"] / 100, 0.4)           # cap at 0.4 at 100 samples
            confidence = round(improvement_confidence + sample_confidence, 3)

            proposal = AIProposal(
                proposal_type=ProposalType.SOURCING_RULE,
                title=(
                    f"Use AI_ADAPTIVE for {ck} cluster "
                    f"({item['improvement_pct']:.1f}% better outcomes)"
                ),
                description=(
                    f"Pattern discovery found that the AI_ADAPTIVE sourcing strategy achieves "
                    f"{item['improvement_pct']:.1f}% better outcome scores than DISTANCE_OPTIMAL "
                    f"for orders in the '{ck}' cluster."
                ),
                rationale=(
                    f"Analysis of {item['total_samples']} labeled orders in cluster '{ck}':\n"
                    f"• AI_ADAPTIVE avg outcome score: {item['ai_avg_score']:.3f} "
                    f"({item['ai_samples']} orders)\n"
                    f"• DISTANCE_OPTIMAL avg outcome score: {item['baseline_avg_score']:.3f} "
                    f"({item['baseline_samples']} orders)\n"
                    f"• Improvement: +{item['improvement_pct']:.1f}%\n\n"
                    f"Thresholds met: "
                    f"≥{MIN_CLUSTER_SAMPLES} total samples ({item['total_samples']} ✓), "
                    f"≥{MIN_AI_SAMPLES} AI samples ({item['ai_samples']} ✓), "
                    f"≥{MIN_IMPROVEMENT_PCT}% improvement ({item['improvement_pct']:.1f}% ✓)."
                ),
                confidence_score=confidence,
                proposal_data=proposal_data,
                status=ProposalStatus.PENDING,
                generated_by="learning_worker/pattern_discovery",
            )
            session.add(proposal)
            created += 1
            logger.info(
                f"PatternDiscovery: proposal created for cluster '{ck}' — "
                f"AI {item['ai_avg_score']:.3f} vs baseline {item['baseline_avg_score']:.3f} "
                f"(+{item['improvement_pct']:.1f}%, {item['total_samples']} samples)"
            )

        if created:
            await session.commit()

        return created

    # ------------------------------------------------------------------
    # Private: condition builder
    # ------------------------------------------------------------------

    def _build_conditions(self, cluster: dict) -> list[dict]:
        """Build sourcing rule conditions from a cluster's feature dimensions."""
        conditions = []

        channel = cluster.get("channel")
        if channel and channel not in ("", "UNKNOWN"):
            conditions.append({"field": "channel", "operator": "EQUALS", "value": channel})

        fulfillment_type = cluster.get("fulfillment_type")
        if fulfillment_type and fulfillment_type not in ("", "UNKNOWN"):
            conditions.append({
                "field": "fulfillment_type",
                "operator": "EQUALS",
                "value": fulfillment_type,
            })

        region = cluster.get("region")
        if region and region not in ("", "UNKNOWN"):
            conditions.append({
                "field": "shipping_state",
                "operator": "EQUALS",
                "value": region,
            })

        amount_bucket = cluster.get("amount_bucket")
        if amount_bucket and amount_bucket != "UNKNOWN":
            low, high = self._parse_amount_bucket(amount_bucket)
            if low is not None:
                conditions.append({
                    "field": "total_amount",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": low,
                })
            if high is not None:
                conditions.append({
                    "field": "total_amount",
                    "operator": "LESS_THAN",
                    "value": high,
                })

        return conditions

    def _parse_amount_bucket(self, bucket: str) -> tuple[Optional[float], Optional[float]]:
        """Parse '100-250' → (100.0, 250.0), '500+' → (500.0, None)."""
        try:
            if "+" in bucket:
                return float(bucket.replace("+", "")), None
            if "-" in bucket:
                parts = bucket.split("-", 1)
                return float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            pass
        return None, None
