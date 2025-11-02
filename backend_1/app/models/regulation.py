"""
Pydantic models for regulatory monitoring and change tracking.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Regulation(BaseModel):
    """Model for a regulatory document"""

    id: str
    title: str
    url: str
    category: Optional[str] = None
    date: Optional[str] = None
    summary: Optional[str] = None
    topics: Optional[List[str]] = None
    latest_pdf_url: Optional[str] = None
    latest_pdf_date: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RegulationCreate(BaseModel):
    """Model for creating a new regulation"""

    id: str
    title: str
    url: str
    category: Optional[str] = None
    date: Optional[str] = None
    summary: Optional[str] = None
    topics: Optional[List[str]] = None
    latest_pdf_url: Optional[str] = None
    latest_pdf_date: Optional[str] = None


class RegulationHistory(BaseModel):
    """Model for a regulation PDF version history entry"""

    id: str
    regulation_id: str
    pdf_url: str
    pdf_date: Optional[str] = None
    document_title: Optional[str] = None
    created_at: Optional[datetime] = None


class RegulationHistoryCreate(BaseModel):
    """Model for creating a regulation history entry"""

    id: str
    regulation_id: str
    pdf_url: str
    pdf_date: Optional[str] = None
    document_title: Optional[str] = None


class RegulationChange(BaseModel):
    """Model for a detected regulatory change"""

    id: str
    regulation_id: str
    old_pdf_url: Optional[str] = None
    new_pdf_url: Optional[str] = None
    old_pdf_date: Optional[str] = None
    new_pdf_date: Optional[str] = None
    comparison_report: Optional[str] = None
    key_changes: Optional[str] = None
    impact_analysis: Optional[str] = None
    alert_id: Optional[str] = None
    created_at: Optional[datetime] = None


class RegulationChangeCreate(BaseModel):
    """Model for creating a regulation change entry"""

    id: str
    regulation_id: str
    old_pdf_url: Optional[str] = None
    new_pdf_url: Optional[str] = None
    old_pdf_date: Optional[str] = None
    new_pdf_date: Optional[str] = None
    comparison_report: Optional[str] = None
    key_changes: Optional[str] = None
    impact_analysis: Optional[str] = None
    alert_id: Optional[str] = None


class RegulationSyncRequest(BaseModel):
    """Request model for triggering regulation sync"""

    url: str = Field(
        description="MAS regulations search URL to scrape",
        example="https://www.mas.gov.sg/regulation/regulations-and-guidance?page=1&rows=All",
    )
    force_update: bool = Field(
        default=False,
        description="Force update all regulations even if dates match",
    )


class RegulationUpdateSummary(BaseModel):
    """Summary of a single regulation update"""

    regulation_id: str
    title: str
    old_date: Optional[str] = None
    new_date: str
    severity: str
    key_changes: Optional[List[str]] = None


class RegulationSyncResponse(BaseModel):
    """Response model for regulation sync operation"""

    total_scraped: int = Field(description="Total regulations scraped from MAS")
    new_regulations: int = Field(description="Number of new regulations added")
    updated_regulations: int = Field(description="Number of regulations with updates")
    unchanged: int = Field(description="Number of unchanged regulations")
    alerts_created: int = Field(description="Number of alerts generated")
    errors: int = Field(default=0, description="Number of errors encountered")
    updates: List[RegulationUpdateSummary] = Field(
        default_factory=list, description="Details of updated regulations"
    )
    error_messages: List[str] = Field(
        default_factory=list, description="Error messages if any"
    )
