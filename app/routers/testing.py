"""
E2E Testing Router
Provides endpoints for running and managing end-to-end tests.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin
from app.services.e2e_testing import E2ETestService, TestFlowResult, TestFlowStatus


# Response Models
class TestFlowResultResponse(BaseModel):
    name: str
    status: TestFlowStatus
    duration_ms: float
    message: str
    created_resources: Dict[str, Any]
    errors: List[str]

    class Config:
        from_attributes = True


class TestRunResponse(BaseModel):
    test_id: str
    status: str
    total_tests: int
    passed: int
    failed: int
    total_duration_ms: float
    results: List[TestFlowResultResponse]


class CleanupResponse(BaseModel):
    message: str
    deleted_resources: Dict[str, int]


router = APIRouter(prefix="/testing/e2e", tags=["Testing"], dependencies=[Depends(require_superadmin)])


@router.post("/run", response_model=TestRunResponse)
async def run_e2e_tests():
    """
    Run comprehensive end-to-end tests.

    Creates test data, runs workflow tests, and returns results.
    Test data is NOT automatically cleaned up - use /cleanup endpoint.
    """
    from app.database.postgres import async_session_factory
    import uuid
    import time

    test_id = str(uuid.uuid4())
    start_time = time.time()

    async with async_session_factory() as db:
        try:
            service = E2ETestService(db)
            results = await service.run_all_tests()
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("E2E test execution error: %s", exc)
            raise HTTPException(status_code=500, detail="Test execution failed")

    passed = sum(1 for r in results if r.status == TestFlowStatus.PASSED)
    failed = sum(1 for r in results if r.status == TestFlowStatus.FAILED)
    duration = (time.time() - start_time) * 1000

    return TestRunResponse(
        test_id=test_id,
        status="completed",
        total_tests=len(results),
        passed=passed,
        failed=failed,
        total_duration_ms=duration,
        results=[
            TestFlowResultResponse(
                name=r.name,
                status=r.status,
                duration_ms=r.duration_ms,
                message=r.message,
                created_resources=r.created_resources,
                errors=r.errors,
            )
            for r in results
        ],
    )


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_test_data(db: AsyncSession = Depends(get_db)):
    """
    Clean up test data from the last test run.
    
    WARNING: This will delete all test resources that were created.
    """
    try:
        service = E2ETestService(db)
        # Note: This is a simplified cleanup that works with fresh service
        # For production, would need to track test resources from the run
        # For now, we'll provide a message
        return CleanupResponse(
            message="Cleanup endpoint requires test tracking implementation. Use the /run endpoint with auto-cleanup parameter for automatic cleanup.",
            deleted_resources={},
        )
    except Exception as e:
        logger.exception("E2E cleanup error: %s", e)
        raise HTTPException(status_code=500, detail="Cleanup failed")


@router.get("/health")
async def test_health(db: AsyncSession = Depends(get_db)):
    """Check if testing service is available."""
    try:
        # Simple DB check
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "message": "Testing service ready"}
    except Exception as e:
        logger.exception("Testing health check error: %s", e)
        raise HTTPException(status_code=503, detail="Testing service unavailable")


@router.post("/run-with-cleanup", response_model=Dict[str, Any])
async def run_tests_with_cleanup():
    """
    Run comprehensive tests and automatically clean up test data.

    Uses independent DB sessions for the test run and cleanup so that
    cleanup always commits even when the test run raises an exception.
    """
    from app.database.postgres import async_session_factory
    import uuid
    import time

    test_id = str(uuid.uuid4())
    start_time = time.time()

    results = []
    test_error: str | None = None

    # ── Session 1: run tests ───────────────────────────────────────────────
    async with async_session_factory() as test_session:
        try:
            service = E2ETestService(test_session)
            results = await service.run_all_tests()
            await test_session.commit()
        except Exception as exc:
            await test_session.rollback()
            test_error = str(exc)

    test_duration = (time.time() - start_time) * 1000

    # ── Session 2: cleanup (always runs, regardless of test outcome) ───────
    deleted: Dict[str, int] = {}
    cleanup_error: str | None = None
    cleanup_start = time.time()

    async with async_session_factory() as cleanup_session:
        try:
            cleanup_service = E2ETestService(cleanup_session)
            deleted = await cleanup_service.cleanup()
            await cleanup_session.commit()
        except Exception as exc:
            await cleanup_session.rollback()
            cleanup_error = str(exc)

    cleanup_duration = (time.time() - cleanup_start) * 1000

    if test_error:
        logger.error("E2E run-with-cleanup test error: %s%s", test_error,
                     f" | cleanup error: {cleanup_error}" if cleanup_error else "")
        raise HTTPException(status_code=500, detail="Test execution failed")

    passed = sum(1 for r in results if r.status == TestFlowStatus.PASSED)
    failed = sum(1 for r in results if r.status == TestFlowStatus.FAILED)

    return {
        "test_id": test_id,
        "status": "completed",
        "total_tests": len(results),
        "passed": passed,
        "failed": failed,
        "test_duration_ms": test_duration,
        "cleanup_duration_ms": cleanup_duration,
        "total_duration_ms": test_duration + cleanup_duration,
        "deleted_resources": deleted,
        "results": [
            {
                "name": r.name,
                "status": r.status.value,
                "duration_ms": r.duration_ms,
                "message": r.message,
                "created_resources": r.created_resources,
                "errors": r.errors,
            }
            for r in results
        ],
    }


@router.post("/run-api", response_model=Dict[str, Any])
async def run_api_integration_tests():
    """
    Run API integration tests server-side using httpx.

    Mirrors the run_e2e.sh test suite (AUTH, ORDERS, INVENTORY, ANALYTICS,
    SEARCH, AI, RBAC, SECURITY).  All test data is cleaned up after the run.
    """
    from app.services.api_integration_testing import ApiIntegrationTestService

    service = ApiIntegrationTestService()
    run = await service.run_all()

    return {
        "test_id": run.test_id,
        "status": run.status,
        "total_tests": run.total_tests,
        "passed": run.passed,
        "failed": run.failed,
        "skipped": run.skipped,
        "total_duration_ms": run.total_duration_ms,
        "cleanup_duration_ms": run.cleanup_duration_ms,
        "deleted_resources": run.deleted_resources,
        "results": [
            {
                "id": r.id,
                "desc": r.desc,
                "group": r.group,
                "status": r.status,
                "note": r.note,
                "duration_ms": r.duration_ms,
            }
            for r in run.results
        ],
    }
