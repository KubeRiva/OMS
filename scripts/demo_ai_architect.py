"""
AI Architect Demo Seed Script
==============================
Seeds realistic sourcing_outcomes data and triggers the learning pipeline
so the AI Architect UI has patterns, proposals, and metrics to display.

Usage (from project root):
    docker exec oms_api python scripts/demo_ai_architect.py

What it does:
  1. Seeds ~150 labeled sourcing_outcomes across 4 clusters
     - DISTANCE_OPTIMAL baseline (lower outcome scores)
     - AI_ADAPTIVE treatment (higher outcome scores for 2 clusters)
  2. Runs label_sourcing_outcomes  → computes outcome_score on any unlabeled docs
  3. Runs update_node_performance   → fills Node Performance tab
  4. Runs discover_patterns         → generates patterns + pending proposals
  5. Prints a summary of what was created
"""
import asyncio
import random
import sys
from datetime import datetime, timedelta

MONGO_URL = "mongodb://oms_user:oms_pass@mongodb:27017/oms_events?authSource=admin"
MONGO_DB  = "oms_ai_learning"  # AI learning DB (separate from oms_events)

# Real node IDs from the database (seeded by the app)
NODES = [
    {"node_id": "e064e3a8-65a0-463b-ac77-45430939081d", "node_name": "LA Beverly Hills Store"},
    {"node_id": "17811524-d9de-4a44-8b1a-481fb1ede490", "node_name": "SF Dark Store"},
    {"node_id": "f79b9958-eeca-4952-923d-570895981025", "node_name": "West Coast DC"},
    {"node_id": "4bef54f0-2d8a-4ab9-9f28-8a3dc1f049c4", "node_name": "Chicago Downtown Store"},
    {"node_id": "e1d6e65f-13da-49d0-9852-bb2a2a76e6d8", "node_name": "Miami Beach Store"},
    {"node_id": "775d394f-1980-48bd-b3a7-b16e0502bedf", "node_name": "Midwest DC"},
    {"node_id": "91f441b4-82ce-4b8a-a90c-f377d825d35e", "node_name": "NYC Flagship Store"},
    {"node_id": "06e3acb9-1029-4da6-b59d-9215791ca65f", "node_name": "East Coast DC"},
]

# Clusters to seed: (channel, region, amount_bucket, fulfillment_type)
# For 2 clusters AI_ADAPTIVE clearly wins; for 1 cluster it's a toss-up; for 1 it loses.
CLUSTERS = [
    {
        "channel": "WEB", "region": "CA", "amount_bucket": "100-250",
        "fulfillment_type": "SHIP_TO_HOME",
        "cluster_key": "WEB|CA|100-250|SHIP_TO_HOME",
        # West Coast DC + SF Dark Store perform best for CA web orders
        "ai_best_node": "f79b9958-eeca-4952-923d-570895981025",   # West Coast DC
        "baseline_best_node": "e064e3a8-65a0-463b-ac77-45430939081d",  # LA Store
        "ai_outcome_mean": 0.82,    # AI picks faster node → higher score
        "baseline_outcome_mean": 0.63,
        "n_ai": 55, "n_baseline": 65,
    },
    {
        "channel": "WEB", "region": "NY", "amount_bucket": "100-250",
        "fulfillment_type": "SHIP_TO_HOME",
        "cluster_key": "WEB|NY|100-250|SHIP_TO_HOME",
        # East Coast DC is best for NY; AI figures this out
        "ai_best_node": "06e3acb9-1029-4da6-b59d-9215791ca65f",   # East Coast DC
        "baseline_best_node": "775d394f-1980-48bd-b3a7-b16e0502bedf",  # Midwest DC
        "ai_outcome_mean": 0.79,
        "baseline_outcome_mean": 0.58,
        "n_ai": 40, "n_baseline": 70,
    },
    {
        "channel": "MOBILE", "region": "TX", "amount_bucket": "50-100",
        "fulfillment_type": "SHIP_TO_HOME",
        "cluster_key": "MOBILE|TX|50-100|SHIP_TO_HOME",
        # Toss-up — not enough improvement for a proposal
        "ai_best_node": "775d394f-1980-48bd-b3a7-b16e0502bedf",   # Midwest DC
        "baseline_best_node": "775d394f-1980-48bd-b3a7-b16e0502bedf",
        "ai_outcome_mean": 0.71,
        "baseline_outcome_mean": 0.67,
        "n_ai": 20, "n_baseline": 30,  # Not enough samples for proposal
    },
    {
        "channel": "POS", "region": "IL", "amount_bucket": "0-50",
        "fulfillment_type": "STORE_PICKUP",
        "cluster_key": "POS|IL|0-50|STORE_PICKUP",
        # DISTANCE_OPTIMAL wins for in-store pickup (no AI advantage)
        "ai_best_node": "4bef54f0-2d8a-4ab9-9f28-8a3dc1f049c4",   # Chicago Store
        "baseline_best_node": "4bef54f0-2d8a-4ab9-9f28-8a3dc1f049c4",
        "ai_outcome_mean": 0.66,
        "baseline_outcome_mean": 0.72,
        "n_ai": 25, "n_baseline": 45,
    },
]


def _make_outcome_doc(cluster: dict, strategy: str, outcome_mean: float, best_node: dict) -> dict:
    """Build one labeled sourcing_outcomes document."""
    import uuid

    # Vary the node slightly — best node gets 70% of allocations, others share 30%
    if random.random() < 0.70:
        node = best_node
    else:
        node = random.choice(NODES)

    # Vary outcome around the mean (std dev 0.10)
    outcome = max(0.0, min(1.0, random.gauss(outcome_mean, 0.10)))
    outcome = round(outcome, 4)

    # Back-calculate components that feel realistic
    delivery_hrs = 20 + random.gauss(0, 8) if outcome > 0.7 else 36 + random.gauss(0, 12)
    delivery_hrs = max(4, round(abs(delivery_hrs), 1))

    cost_variance = random.gauss(3, 5) if outcome > 0.7 else random.gauss(12, 8)
    cost_variance = round(abs(cost_variance), 1)

    was_backordered = random.random() < (0.04 if outcome > 0.7 else 0.15)
    was_returned    = random.random() < (0.02 if outcome > 0.7 else 0.08)

    sourced_at = datetime.utcnow() - timedelta(days=random.randint(1, 60))
    delivered_at = sourced_at + timedelta(hours=delivery_hrs)

    ai_score = round(random.uniform(0.6, 0.95), 3) if strategy in ("AI_ADAPTIVE", "AI_HYBRID") else None

    doc = {
        "order_id": str(uuid.uuid4()),
        "allocation_id": str(uuid.uuid4()),
        "node_id": node["node_id"],
        "node_name": node["node_name"],
        "sku": f"SKU-DEMO-{random.randint(1000, 9999)}",
        "strategy_used": strategy,
        "rule_applied": f"Demo Rule ({strategy})",
        "sourcing_score": round(random.uniform(0.5, 0.95), 3),
        "predicted_cost": round(random.uniform(5, 25), 2),
        "predicted_distance_miles": round(random.uniform(10, 400), 1),
        "actual_cost": round(random.uniform(5, 28), 2),
        "actual_delivery_hours": delivery_hrs,
        "cost_variance_pct": cost_variance,
        "was_backordered": was_backordered,
        "was_returned": was_returned,
        "channel": cluster["channel"],
        "region": cluster["region"],
        "amount_bucket": cluster["amount_bucket"],
        "fulfillment_type": cluster["fulfillment_type"],
        "cluster_key": cluster["cluster_key"],
        "sourced_at": sourced_at.isoformat(),
        "outcome_score": outcome,
        "labeled_at": delivered_at.isoformat(),
        "experiment_id": None,
        "_demo": True,  # tag so we can clean up later
    }
    if ai_score is not None:
        doc["ai_score"] = ai_score
        doc["ai_reasoning"] = f"{node['node_name']} has strong historical performance for {cluster['cluster_key']} orders"

    return doc


async def seed_outcomes(db) -> int:
    """Insert demo sourcing_outcomes documents. Skip if demo data already exists."""
    existing = await db.sourcing_outcomes.count_documents({"_demo": True})
    if existing > 0:
        print(f"  Demo outcomes already exist ({existing} docs). Skipping seed.")
        print("  To re-seed, run:  docker exec oms_mongodb mongosh 'mongodb://oms_user:oms_pass@localhost/oms_ai_learning?authSource=admin' --eval \"db.sourcing_outcomes.deleteMany({_demo:true})\"")
        return existing

    docs = []
    best_node_by_id = {n["node_id"]: n for n in NODES}

    for cluster in CLUSTERS:
        ai_node   = best_node_by_id[cluster["ai_best_node"]]
        base_node = best_node_by_id[cluster["baseline_best_node"]]

        for _ in range(cluster["n_ai"]):
            docs.append(_make_outcome_doc(cluster, "AI_ADAPTIVE", cluster["ai_outcome_mean"], ai_node))

        for _ in range(cluster["n_baseline"]):
            docs.append(_make_outcome_doc(cluster, "DISTANCE_OPTIMAL", cluster["baseline_outcome_mean"], base_node))

    await db.sourcing_outcomes.insert_many(docs)
    print(f"  Inserted {len(docs)} demo sourcing_outcomes documents")
    return len(docs)


async def run_learning_tasks(db, pg_session) -> dict:
    """Run all three learning tasks inline (same logic as Celery tasks)."""
    from app.services.pattern_discovery import PatternDiscoveryService
    from app.workers.learning import update_node_performance as _unp_task

    # ── 1. label_sourcing_outcomes (inline) ──────────────────────────────────
    # All our demo docs are already labeled, but run it to catch any real docs
    cursor = db.sourcing_outcomes.find(
        {"actual_delivery_hours": {"$exists": True}, "outcome_score": {"$exists": False}},
        limit=500,
    )
    unlabeled = await cursor.to_list(length=500)
    labeled_count = 0
    for doc in unlabeled:
        dh = doc.get("actual_delivery_hours") or 999
        ds = 1.0 if dh <= 24 else (0.5 if dh <= 48 else (0.2 if dh <= 72 else 0.0))
        cv = abs(doc.get("cost_variance_pct") or 0)
        cs = 1.0 if cv <= 5 else (0.7 if cv <= 15 else (0.3 if cv <= 25 else 0.0))
        bo = 1.0 if doc.get("was_backordered") else 0.0
        rt = 1.0 if doc.get("was_returned")    else 0.0
        score = round(0.4*ds + 0.3*cs + 0.2*(1-bo) + 0.1*(1-rt), 4)
        await db.sourcing_outcomes.update_one(
            {"_id": doc["_id"]},
            {"$set": {"outcome_score": score, "labeled_at": datetime.utcnow().isoformat()}},
        )
        labeled_count += 1
    print(f"  label_sourcing_outcomes: labeled {labeled_count} previously unlabeled docs")

    # ── 2. update_node_performance ────────────────────────────────────────────
    now = datetime.utcnow()
    updated_nodes = set()
    for period_days in (7, 30):
        cutoff = (now - timedelta(days=period_days)).isoformat()
        pipeline = [
            {"$match": {"outcome_score": {"$exists": True}, "sourced_at": {"$gte": cutoff}}},
            {"$group": {
                "_id": "$node_id",
                "node_name": {"$first": "$node_name"},
                "orders_fulfilled": {"$sum": 1},
                "avg_outcome_score": {"$avg": "$outcome_score"},
                "avg_delivery_hours": {"$avg": "$actual_delivery_hours"},
                "avg_cost_actual": {"$avg": "$actual_cost"},
                "backorder_count": {"$sum": {"$cond": [{"$eq": ["$was_backordered", True]}, 1, 0]}},
                "return_count":    {"$sum": {"$cond": [{"$eq": ["$was_returned",    True]}, 1, 0]}},
            }},
        ]
        results = await db.sourcing_outcomes.aggregate(pipeline).to_list(length=1000)
        for r in results:
            count = r["orders_fulfilled"]
            metrics = {
                "node_id": r["_id"],
                "node_name": r.get("node_name"),
                "period_days": period_days,
                "orders_fulfilled": count,
                "avg_outcome_score": round(r.get("avg_outcome_score") or 0, 4),
                "avg_delivery_hours": round(r.get("avg_delivery_hours") or 0, 1),
                "avg_cost_actual": round(r.get("avg_cost_actual") or 0, 2),
                "backorder_rate_pct": round(r["backorder_count"] / count * 100, 1) if count else 0,
                "return_rate_pct": round(r["return_count"] / count * 100, 1) if count else 0,
                "computed_at": now,
            }
            await db.node_performance_metrics.replace_one(
                {"node_id": r["_id"], "period_days": period_days},
                metrics,
                upsert=True,
            )
            updated_nodes.add(r["_id"])
    print(f"  update_node_performance: refreshed metrics for {len(updated_nodes)} nodes (7d + 30d)")

    # ── 3. discover_patterns → creates proposals ──────────────────────────────
    service = PatternDiscoveryService()
    result = await service.run(db, pg_session)
    print(f"  discover_patterns: updated {result['clusters_updated']} clusters, "
          f"created {result['proposals_created']} proposals")

    return result


async def print_summary(db, pg_session):
    """Print a summary of what was created."""
    from sqlalchemy import select, text
    from app.models.postgres.ai_models import AIProposal, ProposalStatus

    # MongoDB counts
    total_outcomes = await db.sourcing_outcomes.count_documents({})
    labeled        = await db.sourcing_outcomes.count_documents({"outcome_score": {"$exists": True}})
    patterns       = await db.sourcing_patterns.count_documents({})
    node_metrics   = await db.node_performance_metrics.count_documents({})

    # PostgreSQL proposals
    result = await pg_session.execute(
        select(AIProposal).where(AIProposal.status == ProposalStatus.PENDING)
        .order_by(AIProposal.confidence_score.desc())
    )
    proposals = result.scalars().all()

    print("\n" + "="*60)
    print("  AI ARCHITECT DEMO — SUMMARY")
    print("="*60)
    print(f"  sourcing_outcomes:       {total_outcomes:>4} total  ({labeled} labeled)")
    print(f"  sourcing_patterns:       {patterns:>4} clusters")
    print(f"  node_performance_metrics:{node_metrics:>4} entries")
    print(f"  pending AI proposals:    {len(proposals):>4}")

    if proposals:
        print("\n  PENDING PROPOSALS (highest confidence first):")
        for p in proposals:
            print(f"    [{p.confidence_score:.2f}] {p.title[:70]}")

    print("\n  WHAT TO DO NOW:")
    print("  1. Open the app at http://localhost:3001")
    print("  2. Go to AI Architect in the sidebar (superadmin required)")
    print("  3. Proposals tab  → see the auto-generated proposals, approve + apply one")
    print("  4. Patterns tab   → see cluster rankings and top nodes per order type")
    print("  5. Node Perf tab  → see rolling 7d/30d metrics per node")
    print("  6. Experiments tab → create a new A/B experiment to test AI_ADAPTIVE")
    print("="*60)


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    # Import all models so SQLAlchemy mapper is complete
    from app.models.postgres import (  # noqa
        order_models, inventory_models, node_models,
        sourcing_rule_models, connector_models, auth_models, ai_models,
    )
    from app.config import settings

    print("AI Architect Demo Seeder")
    print("-" * 40)

    # MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = mongo_client[MONGO_DB]

    # PostgreSQL
    engine  = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # 1. Seed outcomes
        print("\n[1/4] Seeding sourcing_outcomes...")
        await seed_outcomes(db)

        # 2. Run learning tasks
        print("\n[2/4] Running learning pipeline...")
        async with factory() as session:
            await run_learning_tasks(db, session)

        # 3. Print summary
        print("\n[3/4] Summary:")
        async with factory() as session:
            await print_summary(db, session)

    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        mongo_client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
