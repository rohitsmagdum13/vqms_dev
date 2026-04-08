"""Portal dashboard API routes.

GET /dashboard/kpis — Returns KPI counts for the vendor dashboard (Step P2).
GET /queries — Returns list of queries for a specific vendor.
GET /queries/{query_id} — Returns a single query's details.

These endpoints support the Angular portal frontend. The KPIs are
queried directly from PostgreSQL (workflow.case_execution table).

# TODO: Add Redis 5-min cache for KPIs as per solution flow doc
# (redis key: vqms:dashboard:<vendor_id>, TTL: 300 seconds)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from src.db.connection import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/kpis")
async def get_dashboard_kpis(
    x_vendor_id: str | None = Header(default=None),
) -> dict:
    """Return KPI counts for the vendor's portal dashboard.

    Queries workflow.case_execution to count open and resolved queries.
    Returns zeros if the database is not connected (graceful degradation).

    # TODO: Add Redis 5-min cache for KPIs as per solution flow doc
    """
    if not x_vendor_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Vendor-ID header.",
        )

    engine = get_engine()
    if engine is None:
        # Database not connected — return zeros instead of failing
        logger.warning(
            "Database not connected — returning zero KPIs",
            extra={"vendor_id": x_vendor_id},
        )
        return {
            "vendor_id": x_vendor_id,
            "open_queries": 0,
            "resolved_queries": 0,
            "avg_resolution_hours": 0,
        }

    try:
        async with engine.connect() as conn:
            # Count open queries for this vendor
            open_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE vendor_id = :vid AND status IN ('new', 'analyzing', 'routing', "
                    "'drafting', 'validating', 'sending', 'awaiting_human_review', "
                    "'awaiting_team_resolution')"
                ),
                {"vid": x_vendor_id},
            )
            open_count = open_result.scalar() or 0

            # Count resolved/closed queries for this vendor
            resolved_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE vendor_id = :vid AND status IN ('resolved', 'closed')"
                ),
                {"vid": x_vendor_id},
            )
            resolved_count = resolved_result.scalar() or 0

            # Average resolution time is a stub for now
            # TODO: Calculate from completed_at - created_at when we have real data
            avg_hours = 0

        return {
            "vendor_id": x_vendor_id,
            "open_queries": open_count,
            "resolved_queries": resolved_count,
            "avg_resolution_hours": avg_hours,
        }

    except Exception:
        logger.warning(
            "Failed to query KPIs — returning zeros",
            extra={"vendor_id": x_vendor_id},
            exc_info=True,
        )
        return {
            "vendor_id": x_vendor_id,
            "open_queries": 0,
            "resolved_queries": 0,
            "avg_resolution_hours": 0,
        }


@router.get("/queries")
async def list_queries(
    x_vendor_id: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List queries for a specific vendor.

    Returns the most recent queries from workflow.case_execution,
    ordered by created_at descending. Used by the portal dashboard
    table (Step P2).
    """
    if not x_vendor_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Vendor-ID header.",
        )

    engine = get_engine()
    if engine is None:
        logger.warning(
            "Database not connected — returning empty query list",
            extra={"vendor_id": x_vendor_id},
        )
        return {"vendor_id": x_vendor_id, "queries": [], "total": 0}

    try:
        async with engine.connect() as conn:
            # Get total count
            count_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM workflow.case_execution "
                    "WHERE vendor_id = :vid"
                ),
                {"vid": x_vendor_id},
            )
            total = count_result.scalar() or 0

            # Get paginated results
            rows = await conn.execute(
                text(
                    "SELECT query_id, correlation_id, status, source, "
                    "created_at, updated_at "
                    "FROM workflow.case_execution "
                    "WHERE vendor_id = :vid "
                    "ORDER BY created_at DESC "
                    "LIMIT :lim OFFSET :off"
                ),
                {"vid": x_vendor_id, "lim": limit, "off": offset},
            )

            queries = []
            for row in rows:
                queries.append({
                    "query_id": row.query_id,
                    "correlation_id": row.correlation_id,
                    "status": row.status,
                    "source": row.source,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                })

        return {"vendor_id": x_vendor_id, "queries": queries, "total": total}

    except Exception:
        logger.warning(
            "Failed to list queries — returning empty list",
            extra={"vendor_id": x_vendor_id},
            exc_info=True,
        )
        return {"vendor_id": x_vendor_id, "queries": [], "total": 0}


@router.get("/queries/{query_id}")
async def get_query_detail(
    query_id: str,
    x_vendor_id: str | None = Header(default=None),
) -> dict:
    """Get details for a single query by query_id.

    Validates that the query belongs to the requesting vendor
    (vendor_id from header must match the stored vendor_id).
    """
    if not x_vendor_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Vendor-ID header.",
        )

    engine = get_engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Database not connected.",
        )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT query_id, execution_id, correlation_id, status, "
                    "source, vendor_id, selected_path, "
                    "created_at, updated_at, completed_at "
                    "FROM workflow.case_execution "
                    "WHERE query_id = :qid"
                ),
                {"qid": query_id},
            )
            row = result.first()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Query {query_id} not found.",
            )

        # Verify the query belongs to this vendor
        if row.vendor_id != x_vendor_id:
            raise HTTPException(
                status_code=403,
                detail="Query does not belong to this vendor.",
            )

        return {
            "query_id": row.query_id,
            "execution_id": row.execution_id,
            "correlation_id": row.correlation_id,
            "status": row.status,
            "source": row.source,
            "vendor_id": row.vendor_id,
            "selected_path": row.selected_path,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }

    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "Failed to get query detail",
            extra={"query_id": query_id},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve query details.",
        ) from None
