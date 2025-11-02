"""
API routes for regulatory monitoring and change tracking.
"""

import logging
from typing import List, Optional

from app.database.connection import PostgresDatabase
from app.models.regulation import (
    Regulation,
    RegulationChange,
    RegulationHistory,
    RegulationSyncRequest,
    RegulationSyncResponse,
)
from app.services.regulation_monitor import RegulationMonitorService
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sync", response_model=RegulationSyncResponse)
async def sync_regulations(request: RegulationSyncRequest):
    """
    Trigger manual synchronization of MAS regulations.

    This endpoint:
    1. Scrapes regulations from the provided MAS URL
    2. Detects new regulations and updates to existing ones
    3. Compares PDFs when changes are detected
    4. Analyzes changes using LLM
    5. Creates alerts for significant changes
    6. Stores all data in the database

    **Example URLs:**
    - All regulations: https://www.mas.gov.sg/regulation/regulations-and-guidance?page=1&rows=All
    - Specific topic: https://www.mas.gov.sg/regulation/regulations-and-guidance?topics=Anti-Money%20Laundering&page=1&rows=All

    Returns:
        Summary of the sync operation including counts and details of updates
    """
    try:
        summary = await RegulationMonitorService.sync_regulations(
            request.url, request.force_update
        )

        return RegulationSyncResponse(**summary)

    except Exception as e:
        logger.error(f"Error during regulation sync: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.get("/", response_model=List[Regulation])
async def get_regulations(
    category: Optional[str] = Query(
        None, description="Filter by category (Notices, Guidelines, Circulars, etc.)"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """
    Get all regulations with optional filtering and pagination.

    Args:
        category: Optional category filter (Notices, Guidelines, Circulars)
        limit: Maximum number of results (default 100, max 1000)
        offset: Number of results to skip for pagination

    Returns:
        List of regulations matching the criteria
    """
    try:
        regulations = await PostgresDatabase.get_all_regulations(
            category=category, limit=limit, offset=offset
        )
        return regulations
    except Exception as e:
        logger.error(f"Error fetching regulations: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch regulations: {str(e)}"
        )


@router.get("/{regulation_id}", response_model=Regulation)
async def get_regulation(regulation_id: str):
    """
    Get a specific regulation by ID.

    Args:
        regulation_id: Unique identifier of the regulation

    Returns:
        The regulation details
    """
    try:
        regulation = await PostgresDatabase.get_regulation(regulation_id)

        if not regulation:
            raise HTTPException(status_code=404, detail="Regulation not found")

        return regulation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching regulation {regulation_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch regulation: {str(e)}"
        )


@router.get("/{regulation_id}/history", response_model=List[RegulationHistory])
async def get_regulation_history(regulation_id: str):
    """
    Get the PDF version history for a specific regulation.

    This shows all historical versions of the regulation PDF
    that have been tracked, ordered by date (newest first).

    Args:
        regulation_id: Unique identifier of the regulation

    Returns:
        List of historical PDF versions
    """
    try:
        # Verify regulation exists
        regulation = await PostgresDatabase.get_regulation(regulation_id)
        if not regulation:
            raise HTTPException(status_code=404, detail="Regulation not found")

        history = await PostgresDatabase.get_regulation_history(regulation_id)
        return history
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching regulation history for {regulation_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch history: {str(e)}"
        )


@router.get("/{regulation_id}/changes", response_model=List[RegulationChange])
async def get_regulation_changes(regulation_id: str):
    """
    Get all detected changes for a specific regulation.

    This shows the history of detected changes, including:
    - PDF comparison reports
    - LLM-generated key changes analysis
    - Impact assessments
    - Associated alerts

    Args:
        regulation_id: Unique identifier of the regulation

    Returns:
        List of change records, ordered by detection date (newest first)
    """
    try:
        # Verify regulation exists
        regulation = await PostgresDatabase.get_regulation(regulation_id)
        if not regulation:
            raise HTTPException(status_code=404, detail="Regulation not found")

        changes = await PostgresDatabase.get_regulation_changes(regulation_id)
        return changes
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching regulation changes for {regulation_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch changes: {str(e)}"
        )


@router.get("/{regulation_id}/latest-analysis")
async def get_latest_analysis(regulation_id: str):
    """
    Get the most recent change analysis for a regulation.

    This is a convenience endpoint that returns just the latest
    change detection with full analysis details.

    Args:
        regulation_id: Unique identifier of the regulation

    Returns:
        The most recent RegulationChange record or 404 if no changes exist
    """
    try:
        # Verify regulation exists
        regulation = await PostgresDatabase.get_regulation(regulation_id)
        if not regulation:
            raise HTTPException(status_code=404, detail="Regulation not found")

        changes = await PostgresDatabase.get_regulation_changes(regulation_id)

        if not changes:
            raise HTTPException(
                status_code=404, detail="No change analysis found for this regulation"
            )

        return changes[0]  # First item is most recent due to ORDER BY created_at DESC
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching latest analysis for {regulation_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch analysis: {str(e)}"
        )


@router.get("/changes/all", response_model=List[RegulationChange])
async def get_all_changes(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """
    Get all regulation changes across all regulations.

    This provides a global view of all detected regulatory changes,
    ordered by detection date (newest first).

    Args:
        limit: Maximum number of results (default 50, max 500)
        offset: Number of results to skip for pagination

    Returns:
        List of all regulation changes
    """
    try:
        changes = await PostgresDatabase.get_all_regulation_changes(
            limit=limit, offset=offset
        )
        return changes
    except Exception as e:
        logger.error(f"Error fetching all regulation changes: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch changes: {str(e)}"
        )
