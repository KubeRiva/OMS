"""
Learning pipeline — outcome labeling, pattern discovery, performance metrics.
All tasks run in the 'learning' queue at low priority.
"""
import logging
from datetime import datetime, timedelta

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.learning.label_sourcing_outcomes",
    queue="learning",
)
def label_sourcing_outcomes(environment_id: str = ""):
    """
    Hourly: find delivered orders with sourcing_outcomes docs and compute outcome_score.

    outcome_score = (
        0.4 * delivery_score   (1.0 if ≤24h, 0.5 if ≤48h, 0.2 if ≤72h, 0.0 if >72h)
        + 0.3 * cost_score     (1.0 if variance ≤5%, 0.7 if ≤15%, 0.3 if ≤25%, 0.0 if >25%)
        + 0.2 * (1 - backorder)
        + 0.1 * (1 - returned)
    )
    """
    import asyncio
    from app.workers.env_utils import get_env_mongo_ai_db

    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.config import settings

        mongo_ai_db = get_env_mongo_ai_db(environment_id)
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        try:
            db = client[mongo_ai_db]
            # Find outcomes that have delivery data but haven't been labeled yet
            cursor = db.sourcing_outcomes.find(
                {
                    "actual_delivery_hours": {"$exists": True, "$ne": None},
                    "outcome_score": {"$exists": False},
                },
                limit=500,
            )
            docs = await cursor.to_list(length=500)
            labeled = 0

            for doc in docs:
                delivery_hours = doc.get("actual_delivery_hours") or 999
                if delivery_hours <= 24:
                    delivery_score = 1.0
                elif delivery_hours <= 48:
                    delivery_score = 0.5
                elif delivery_hours <= 72:
                    delivery_score = 0.2
                else:
                    delivery_score = 0.0

                cost_variance = abs(doc.get("cost_variance_pct") or 0)
                if cost_variance <= 5:
                    cost_score = 1.0
                elif cost_variance <= 15:
                    cost_score = 0.7
                elif cost_variance <= 25:
                    cost_score = 0.3
                else:
                    cost_score = 0.0

                backorder = 1.0 if doc.get("was_backordered") else 0.0
                returned = 1.0 if doc.get("was_returned") else 0.0

                outcome_score = round(
                    0.4 * delivery_score
                    + 0.3 * cost_score
                    + 0.2 * (1 - backorder)
                    + 0.1 * (1 - returned),
                    4,
                )

                label_update: dict = {
                    "outcome_score": outcome_score,
                    "labeled_at": datetime.utcnow(),
                }
                # Carry brand_slug forward if present (for pattern grouping)
                if doc.get("brand_slug"):
                    label_update["brand_slug"] = doc["brand_slug"]
                if doc.get("brand_id"):
                    label_update["brand_id"] = doc["brand_id"]

                await db.sourcing_outcomes.update_one(
                    {"_id": doc["_id"]},
                    {"$set": label_update},
                )
                labeled += 1

            if labeled:
                logger.info(f"label_sourcing_outcomes: labeled {labeled} outcomes")

        finally:
            client.close()

    asyncio.run(_run())


@celery_app.task(
    name="app.workers.learning.discover_patterns",
    queue="learning",
)
def discover_patterns(environment_id: str = ""):
    """
    Nightly: aggregate labeled outcomes into sourcing_patterns by cluster key,
    then generate AI proposals for clusters where AI_ADAPTIVE shows a
    statistically significant advantage over DISTANCE_OPTIMAL.

    Cluster key = brand_slug|channel|region|amount_bucket|fulfillment_type

    Delegates to PatternDiscoveryService for aggregation + proposal generation.
    """
    import asyncio
    from app.workers.env_utils import get_env_db_url, get_env_mongo_ai_db

    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from app.config import settings
        from app.services.pattern_discovery import PatternDiscoveryService

        # Import all models so SQLAlchemy mapper metadata is complete (includes ai_models)
        from app.models.postgres import (  # noqa
            order_models, inventory_models, node_models,
            sourcing_rule_models, connector_models, auth_models, ai_models, lifecycle_models,
            b2b_models, brand_models,
        )

        db_url = get_env_db_url(environment_id)
        mongo_ai_db = get_env_mongo_ai_db(environment_id)
        mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            db = mongo_client[mongo_ai_db]
            async with factory() as session:
                service = PatternDiscoveryService()
                result = await service.run(db, session)

            logger.info(
                f"discover_patterns: updated {result['clusters_updated']} clusters, "
                f"created {result['proposals_created']} AI proposals"
            )
        finally:
            mongo_client.close()
            await engine.dispose()

    asyncio.run(_run())


@celery_app.task(
    name="app.workers.learning.update_node_performance",
    queue="learning",
)
def update_node_performance(environment_id: str = ""):
    """
    Every 4 hours: compute rolling 7-day and 30-day node performance metrics.
    """
    import asyncio
    from app.workers.env_utils import get_env_mongo_ai_db

    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        from app.config import settings

        mongo_ai_db = get_env_mongo_ai_db(environment_id)
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        try:
            db = client[mongo_ai_db]
            now = datetime.utcnow()

            for period_days in (7, 30):
                cutoff = (now - timedelta(days=period_days)).isoformat()
                pipeline = [
                    {
                        "$match": {
                            "outcome_score": {"$exists": True},
                            "sourced_at": {"$gte": cutoff},
                        }
                    },
                    {
                        "$group": {
                            "_id": "$node_id",
                            "node_name": {"$first": "$node_name"},
                            "orders_fulfilled": {"$sum": 1},
                            "avg_outcome_score": {"$avg": "$outcome_score"},
                            "avg_delivery_hours": {"$avg": "$actual_delivery_hours"},
                            "avg_cost_actual": {"$avg": "$actual_cost"},
                            "backorder_count": {
                                "$sum": {"$cond": [{"$eq": ["$was_backordered", True]}, 1, 0]}
                            },
                            "return_count": {
                                "$sum": {"$cond": [{"$eq": ["$was_returned", True]}, 1, 0]}
                            },
                        }
                    },
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

            logger.info("update_node_performance: metrics refreshed for 7d and 30d windows")

        finally:
            client.close()

    asyncio.run(_run())


@celery_app.task(
    name="app.workers.learning.evaluate_ai_experiments",
    queue="learning",
)
def evaluate_ai_experiments(environment_id: str = ""):
    """
    Daily: evaluate running A/B experiments.

    For each running AIExperiment:
      1. Query labeled sourcing_outcomes grouped by strategy arm for this experiment.
      2. If each arm has ≥ MIN_SAMPLES_PER_ARM labeled outcomes:
         - Compare avg_outcome_score between strategy_a and strategy_b.
         - If the better arm leads by ≥ MIN_SCORE_DIFF, declare it winner.
         - Mark experiment COMPLETED with winner + results.
         - Generate a PENDING AIProposal to promote the winning strategy.
    """
    import asyncio
    from app.workers.env_utils import get_env_db_url, get_env_mongo_ai_db

    MIN_SAMPLES_PER_ARM = 200  # Require more data per arm for statistical reliability
    MIN_SCORE_DIFF = 0.05  # Absolute outcome score difference required

    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from sqlalchemy import select
        from app.config import settings
        from app.models.postgres.ai_models import (
            AIExperiment, ExperimentStatus, AIProposal, ProposalType, ProposalStatus,
        )
        from app.models.postgres import (  # noqa
            order_models, inventory_models, node_models,
            sourcing_rule_models, connector_models, auth_models, ai_models, lifecycle_models,
            b2b_models, brand_models,
        )

        db_url = get_env_db_url(environment_id)
        mongo_ai_db = get_env_mongo_ai_db(environment_id)
        mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            db = mongo_client[settings.MONGODB_AI_DB]
            async with factory() as session:
                # Load all running experiments
                result = await session.execute(
                    select(AIExperiment).where(
                        AIExperiment.status == ExperimentStatus.RUNNING
                    )
                )
                experiments = result.scalars().all()
                if not experiments:
                    logger.info("evaluate_ai_experiments: no running experiments")
                    return

                evaluated = 0
                for exp in experiments:
                    exp_id = str(exp.id)
                    try:
                        # Aggregate labeled outcomes for this experiment by strategy arm
                        pipeline = [
                            {
                                "$match": {
                                    "experiment_id": exp_id,
                                    "outcome_score": {"$exists": True},
                                }
                            },
                            {
                                "$group": {
                                    "_id": "$strategy_used",
                                    "count": {"$sum": 1},
                                    "avg_outcome_score": {"$avg": "$outcome_score"},
                                    "avg_delivery_hours": {"$avg": "$actual_delivery_hours"},
                                }
                            },
                        ]
                        arm_results = await db.sourcing_outcomes.aggregate(pipeline).to_list(length=10)
                        by_strategy = {r["_id"]: r for r in arm_results}

                        a_data = by_strategy.get(exp.strategy_a)
                        b_data = by_strategy.get(exp.strategy_b)

                        if not a_data or not b_data:
                            logger.debug(f"Experiment {exp_id}: insufficient arm data yet")
                            continue

                        a_count = a_data["count"]
                        b_count = b_data["count"]

                        if a_count < MIN_SAMPLES_PER_ARM or b_count < MIN_SAMPLES_PER_ARM:
                            logger.debug(
                                f"Experiment {exp_id}: not enough samples "
                                f"(a={a_count}, b={b_count}, need {MIN_SAMPLES_PER_ARM} each)"
                            )
                            continue

                        a_score = a_data["avg_outcome_score"]
                        b_score = b_data["avg_outcome_score"]
                        diff = abs(a_score - b_score)

                        if diff < MIN_SCORE_DIFF:
                            logger.info(
                                f"Experiment {exp_id}: no significant winner yet "
                                f"(a={a_score:.4f}, b={b_score:.4f}, diff={diff:.4f})"
                            )
                            continue

                        # Declare winner
                        winner = exp.strategy_b if b_score > a_score else exp.strategy_a
                        winner_score = max(a_score, b_score)
                        loser_score = min(a_score, b_score)
                        improvement_pct = round((winner_score - loser_score) / loser_score * 100, 1) if loser_score > 0 else 0

                        results_data = {
                            exp.strategy_a: {
                                "count": a_count,
                                "avg_outcome_score": round(a_score, 4),
                                "avg_delivery_hours": round(a_data.get("avg_delivery_hours") or 0, 1),
                            },
                            exp.strategy_b: {
                                "count": b_count,
                                "avg_outcome_score": round(b_score, 4),
                                "avg_delivery_hours": round(b_data.get("avg_delivery_hours") or 0, 1),
                            },
                        }

                        exp.status = ExperimentStatus.COMPLETED
                        exp.winner = winner
                        exp.ended_at = datetime.utcnow()
                        exp.results = results_data

                        # Generate proposal to promote the winning strategy
                        proposal = AIProposal(
                            proposal_type=ProposalType.SOURCING_EXPERIMENT,
                            title=f"Promote {winner} from experiment '{exp.name}'",
                            description=(
                                f"A/B experiment '{exp.name}' completed with a statistically "
                                f"significant winner: {winner} (+{improvement_pct}% better outcomes)."
                            ),
                            rationale=(
                                f"Experiment '{exp.name}' results:\n"
                                f"• {exp.strategy_a}: avg_outcome_score={round(a_score, 4)} ({a_count} orders)\n"
                                f"• {exp.strategy_b}: avg_outcome_score={round(b_score, 4)} ({b_count} orders)\n"
                                f"• Winner: {winner} (+{improvement_pct}%)\n\n"
                                f"Threshold: ≥{MIN_SAMPLES_PER_ARM} samples per arm ({a_count}/{b_count} ✓), "
                                f"≥{MIN_SCORE_DIFF:.2f} score diff ({diff:.4f} ✓).\n\n"
                                f"Suggested action: create a sourcing rule using the {winner} strategy "
                                f"for orders matching the experiment's filter conditions."
                            ),
                            confidence_score=min(0.95, 0.5 + improvement_pct / 100),
                            proposal_data={
                                "experiment_id": exp_id,
                                "experiment_name": exp.name,
                                "winner_strategy": winner,
                                "loser_strategy": exp.strategy_a if winner == exp.strategy_b else exp.strategy_b,
                                "improvement_pct": improvement_pct,
                                "filter_conditions": exp.filter_conditions or {},
                                "results": results_data,
                            },
                            status=ProposalStatus.PENDING,
                            generated_by="learning_worker/evaluate_ai_experiments",
                        )
                        session.add(proposal)
                        evaluated += 1

                        logger.info(
                            f"Experiment {exp_id} '{exp.name}': winner={winner} "
                            f"(+{improvement_pct}%), proposal created"
                        )

                    except Exception as exc:
                        logger.error(f"evaluate_ai_experiments: error on experiment {exp_id}: {exc}")

                if evaluated:
                    await session.commit()

                logger.info(f"evaluate_ai_experiments: evaluated {len(experiments)} experiments, {evaluated} completed with proposals")

        finally:
            mongo_client.close()
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Fan-out beat tasks — dispatch per-environment work to the learning queue
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.learning.label_sourcing_outcomes_fanout",
    queue="learning",
)
def label_sourcing_outcomes_fanout():
    """Beat task: dispatch label_sourcing_outcomes to every active environment."""
    from app.workers.env_utils import list_active_environment_ids
    for env_id in list_active_environment_ids():
        label_sourcing_outcomes.delay(env_id)


@celery_app.task(
    name="app.workers.learning.discover_patterns_fanout",
    queue="learning",
)
def discover_patterns_fanout():
    """Beat task: dispatch discover_patterns to every active environment."""
    from app.workers.env_utils import list_active_environment_ids
    for env_id in list_active_environment_ids():
        discover_patterns.delay(env_id)


@celery_app.task(
    name="app.workers.learning.update_node_performance_fanout",
    queue="learning",
)
def update_node_performance_fanout():
    """Beat task: dispatch update_node_performance to every active environment."""
    from app.workers.env_utils import list_active_environment_ids
    for env_id in list_active_environment_ids():
        update_node_performance.delay(env_id)


@celery_app.task(
    name="app.workers.learning.evaluate_ai_experiments_fanout",
    queue="learning",
)
def evaluate_ai_experiments_fanout():
    """Beat task: dispatch evaluate_ai_experiments to every active environment."""
    from app.workers.env_utils import list_active_environment_ids
    for env_id in list_active_environment_ids():
        evaluate_ai_experiments.delay(env_id)
