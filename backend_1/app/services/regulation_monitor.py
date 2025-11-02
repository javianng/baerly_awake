"""
Regulation monitoring service for detecting and analyzing regulatory changes.

This service orchestrates the entire regulatory update workflow:
1. Scrapes MAS regulations
2. Detects changes by comparing dates
3. Downloads and compares PDFs
4. Analyzes changes using LLM
5. Stores results and generates alerts
"""

import logging
import os
import tempfile
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx
from app.agents.regulation_analyzer import (
    analyze_regulation_changes,
    format_key_changes_for_storage,
)
from app.database.connection import PostgresDatabase
from app.services.mas_scraper import regulation_history_scraper, regulations_scraper
from app.services.pdf_comparison import compare_pdf_documents

logger = logging.getLogger(__name__)


class RegulationMonitorService:
    """Service for monitoring MAS regulations and detecting changes"""

    @staticmethod
    async def download_pdf_to_temp(url: str) -> Optional[str]:
        """
        Download a PDF from URL to a temporary file.

        Args:
            url: URL of the PDF to download

        Returns:
            Path to the temporary file, or None if download fails

        Note:
            Caller is responsible for cleaning up the temporary file
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()

                # Create temporary file
                temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
                os.close(temp_fd)

                # Write PDF content
                with open(temp_path, "wb") as f:
                    f.write(response.content)

                logger.info(f"Downloaded PDF from {url} to {temp_path}")
                return temp_path

        except Exception as e:
            logger.error(f"Failed to download PDF from {url}: {e}")
            return None

    @staticmethod
    def parse_date_for_comparison(date_str: str) -> Optional[datetime]:
        """
        Parse a date string to datetime for comparison.
        Handles the standardized format from mas_scraper (DD MMM YYYY).

        Args:
            date_str: Date string in 'DD MMM YYYY' format

        Returns:
            datetime object or None if parsing fails
        """
        if not date_str or date_str == "Previous Version":
            return None

        try:
            return datetime.strptime(date_str.strip(), "%d %b %Y")
        except ValueError:
            # Try alternative formats
            try:
                return datetime.strptime(date_str.strip(), "%d %B %Y")
            except ValueError:
                logger.warning(f"Could not parse date: {date_str}")
                return None

    @staticmethod
    async def process_new_regulation(item: Dict) -> str:
        """
        Process and store a new regulation.

        Args:
            item: Regulation item from regulations_scraper

        Returns:
            ID of the created regulation
        """
        regulation_id = str(uuid.uuid4())

        # Fetch history to get PDF versions
        try:
            history_entries = regulation_history_scraper(item["url"], item["category"])
        except Exception as e:
            logger.error(f"Failed to fetch history for {item['title']}: {e}")
            history_entries = []

        # Extract latest PDF info from history
        latest_pdf_url = None
        latest_pdf_date = None
        if history_entries:
            latest_entry = history_entries[0]
            latest_pdf_url = (
                latest_entry["documents"][0]["url"]
                if latest_entry.get("documents")
                else None
            )
            latest_pdf_date = latest_entry.get("date")

        # Insert regulation
        regulation_data = {
            "id": regulation_id,
            "title": item["title"],
            "url": item["url"],
            "category": item["category"],
            "date": item["date"],
            "summary": item["summary"],
            "topics": item["topics"],
            "latest_pdf_url": latest_pdf_url,
            "latest_pdf_date": latest_pdf_date,
            "last_checked_at": datetime.utcnow(),
        }

        await PostgresDatabase.insert_regulation(regulation_data)
        logger.info(f"Inserted new regulation: {item['title']}")

        # Store history entries
        for entry in history_entries:
            for doc in entry.get("documents", []):
                history_id = str(uuid.uuid4())
                history_data = {
                    "id": history_id,
                    "regulation_id": regulation_id,
                    "pdf_url": doc["url"],
                    "pdf_date": entry["date"],
                    "document_title": doc["title"],
                }
                await PostgresDatabase.insert_regulation_history(history_data)

        return regulation_id

    @staticmethod
    async def detect_and_process_change(
        regulation: Dict, new_item: Dict
    ) -> Optional[Dict]:
        """
        Detect and process a regulation change.

        Args:
            regulation: Existing regulation from database
            new_item: New regulation data from scraper

        Returns:
            Change summary dict if change detected and processed, None otherwise
        """
        regulation_id = regulation["id"]
        old_date = regulation["latest_pdf_date"]
        new_date = new_item["date"]

        # Parse and compare dates
        old_date_parsed = RegulationMonitorService.parse_date_for_comparison(old_date)
        new_date_parsed = RegulationMonitorService.parse_date_for_comparison(new_date)

        # If dates are the same or can't be compared, skip
        if not new_date_parsed or (
            old_date_parsed and new_date_parsed <= old_date_parsed
        ):
            logger.info(f"No date change detected for {regulation['title']}")
            # Update last_checked_at anyway
            await PostgresDatabase.update_regulation(
                regulation_id, {"last_checked_at": datetime.utcnow()}
            )
            return None

        logger.info(
            f"Change detected for {regulation['title']}: {old_date} -> {new_date}"
        )

        # Fetch updated history
        try:
            history_entries = regulation_history_scraper(
                new_item["url"], new_item["category"]
            )
        except Exception as e:
            logger.error(f"Failed to fetch history for {regulation['title']}: {e}")
            return None

        if not history_entries:
            logger.warning(f"No history entries found for {regulation['title']}")
            return None

        # Find old and new PDFs
        latest_entry = history_entries[0]
        new_pdf_url = (
            latest_entry["documents"][0]["url"]
            if latest_entry.get("documents")
            else None
        )
        new_pdf_date = latest_entry.get("date")

        # Find old PDF by matching date
        old_pdf_url = regulation["latest_pdf_url"]

        if not new_pdf_url or not old_pdf_url:
            logger.warning(
                f"Missing PDF URLs for comparison: old={old_pdf_url}, new={new_pdf_url}"
            )
            return None

        # Download PDFs
        logger.info(f"Downloading PDFs for comparison...")
        old_pdf_path = await RegulationMonitorService.download_pdf_to_temp(old_pdf_url)
        new_pdf_path = await RegulationMonitorService.download_pdf_to_temp(new_pdf_url)

        if not old_pdf_path or not new_pdf_path:
            logger.error("Failed to download PDFs for comparison")
            return None

        try:
            # Compare PDFs
            logger.info(f"Comparing PDFs...")
            comparison_report = compare_pdf_documents(new_pdf_path, old_pdf_path)

            # Analyze changes with LLM
            logger.info(f"Analyzing changes with LLM...")
            analysis = analyze_regulation_changes(
                comparison_report, regulation["title"]
            )

            # Format key changes for storage
            key_changes_text = format_key_changes_for_storage(analysis.key_changes)

            # Create alert
            alert_id = str(uuid.uuid4())
            alert_message = f"Regulatory Update: {regulation['title']}\n\nKey Changes:\n{key_changes_text}"

            alert_data = {
                "id": alert_id,
                "transaction_id": "N/A",  # Not transaction-specific
                "alert_type": "regulatory_update",
                "severity": analysis.severity,
                "message": alert_message,
                "timestamp": datetime.utcnow(),
                "status": "active",
                "assigned_to": "Compliance",
            }
            await PostgresDatabase.insert_alert(alert_data)
            logger.info(f"Created alert {alert_id} for regulatory change")

            # Store change record
            change_id = str(uuid.uuid4())
            change_data = {
                "id": change_id,
                "regulation_id": regulation_id,
                "old_pdf_url": old_pdf_url,
                "new_pdf_url": new_pdf_url,
                "old_pdf_date": old_date,
                "new_pdf_date": new_pdf_date,
                "comparison_report": comparison_report,
                "key_changes": key_changes_text,
                "impact_analysis": analysis.impact_analysis,
                "alert_id": alert_id,
            }
            await PostgresDatabase.insert_regulation_change(change_data)

            # Update regulation with new PDF info
            await PostgresDatabase.update_regulation(
                regulation_id,
                {
                    "latest_pdf_url": new_pdf_url,
                    "latest_pdf_date": new_pdf_date,
                    "date": new_date,
                    "last_checked_at": datetime.utcnow(),
                },
            )

            # Store new history entries
            for entry in history_entries:
                for doc in entry.get("documents", []):
                    # Check if this history entry already exists
                    existing = await PostgresDatabase.get_regulation_history_by_date(
                        regulation_id, entry["date"]
                    )
                    if not existing:
                        history_id = str(uuid.uuid4())
                        history_data = {
                            "id": history_id,
                            "regulation_id": regulation_id,
                            "pdf_url": doc["url"],
                            "pdf_date": entry["date"],
                            "document_title": doc["title"],
                        }
                        await PostgresDatabase.insert_regulation_history(history_data)

            return {
                "regulation_id": regulation_id,
                "title": regulation["title"],
                "old_date": old_date,
                "new_date": new_pdf_date,
                "severity": analysis.severity,
                "key_changes": analysis.key_changes,
            }

        finally:
            # Clean up temporary files
            try:
                if old_pdf_path and os.path.exists(old_pdf_path):
                    os.remove(old_pdf_path)
                if new_pdf_path and os.path.exists(new_pdf_path):
                    os.remove(new_pdf_path)
                logger.info("Cleaned up temporary PDF files")
            except Exception as e:
                logger.error(f"Failed to clean up temp files: {e}")

    @staticmethod
    async def sync_regulations(url: str, force_update: bool = False) -> Dict:
        """
        Main sync function to scrape regulations and detect changes.

        Args:
            url: MAS regulations search URL
            force_update: If True, force update all regulations regardless of date

        Returns:
            Summary dict with sync statistics

        Example:
            >>> summary = await sync_regulations(
            ...     "https://www.mas.gov.sg/regulation/regulations-and-guidance?page=1&rows=All"
            ... )
            >>> print(summary)
            {
                "total_scraped": 136,
                "new_regulations": 5,
                "updated_regulations": 3,
                "unchanged": 128,
                "alerts_created": 3,
                "updates": [...]
            }
        """
        logger.info(f"Starting regulation sync from {url}")

        # Scrape regulations
        try:
            items = regulations_scraper(url)
            logger.info(f"Scraped {len(items)} regulations")
        except Exception as e:
            logger.error(f"Failed to scrape regulations: {e}")
            return {
                "total_scraped": 0,
                "new_regulations": 0,
                "updated_regulations": 0,
                "unchanged": 0,
                "alerts_created": 0,
                "errors": 1,
                "error_messages": [str(e)],
                "updates": [],
            }

        new_count = 0
        updated_count = 0
        unchanged_count = 0
        error_count = 0
        updates = []
        error_messages = []

        # Process each regulation
        for item in items:
            try:
                # Check if regulation exists
                existing = await PostgresDatabase.get_regulation_by_title_and_category(
                    item["title"], item["category"]
                )

                if not existing:
                    # New regulation
                    await RegulationMonitorService.process_new_regulation(item)
                    new_count += 1
                else:
                    # Existing regulation - check for changes
                    change_summary = (
                        await RegulationMonitorService.detect_and_process_change(
                            existing, item
                        )
                    )

                    if change_summary:
                        updated_count += 1
                        updates.append(change_summary)
                    else:
                        unchanged_count += 1

            except Exception as e:
                logger.error(
                    f"Error processing regulation {item.get('title', 'Unknown')}: {e}"
                )
                error_count += 1
                error_messages.append(f"{item.get('title', 'Unknown')}: {str(e)}")

        logger.info(
            f"Sync complete: {new_count} new, {updated_count} updated, "
            f"{unchanged_count} unchanged, {error_count} errors"
        )

        return {
            "total_scraped": len(items),
            "new_regulations": new_count,
            "updated_regulations": updated_count,
            "unchanged": unchanged_count,
            "alerts_created": len(updates),
            "errors": error_count,
            "error_messages": error_messages,
            "updates": updates,
        }
