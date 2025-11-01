import re
from datetime import datetime
from typing import Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def standardize_date(date_str: str) -> str:
    """
    Standardize date string to 'DD MMM YYYY' format.

    Args:
        date_str: Date string in various formats (e.g., "1 Jan 2024", "01 January 2024", "30 Jun 2025")

    Returns:
        Standardized date string in 'DD MMM YYYY' format (e.g., "01 Jan 2024")
        Returns original string if parsing fails
    """
    if not date_str or date_str == "Previous Version":
        return date_str

    # Common date formats to try
    formats = [
        "%d %B %Y",  # 01 January 2024
        "%d %b %Y",  # 01 Jan 2024
        "%-d %B %Y",  # 1 January 2024 (Unix)
        "%-d %b %Y",  # 1 Jan 2024 (Unix)
        "%#d %B %Y",  # 1 January 2024 (Windows)
        "%#d %b %Y",  # 1 Jan 2024 (Windows)
    ]

    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str.strip(), fmt)
            # Return in standardized format: DD MMM YYYY
            return parsed_date.strftime("%d %b %Y")
        except ValueError:
            continue

    # If all formats fail, return original
    return date_str


def mas_regulations_scraper(url: str) -> List[Dict]:
    """
    Scrapes regulations and guidance from MAS search results page.

    Args:
        url: The URL of the MAS regulations and guidance search page

    Returns:
        A list of regulation items, each containing:
        - title: Title of the regulation
        - url: Link to the regulation page
        - category: Category/tag of the regulation
        - date: Publication/update date
        - summary: Brief summary
        - topics: List of related topics
        - consultation_fields: Optional consultation information

    Example:
        >>> items = mas_regulations_scraper("https://www.mas.gov.sg/regulation/regulations-and-guidance?topics=Anti-Money%20Laundering&page=1&rows=All")
        >>> (len(items))
        136
    """
    # Setup Chrome driver in headless mode
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=0,0")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=chrome_options
    )
    driver.get(url)
    html_content = driver.page_source
    driver.quit()

    # Prettify the HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    base_url = "https://www.mas.gov.sg"

    items = []
    for li in soup.find_all("li", class_="mas-search-page__result"):
        # title + link
        a = li.select_one(".ola-field-title a.mas-link") or li.find(
            "a", class_="mas-link"
        )
        title = a.get_text(" ", strip=True) if a else None
        href = urljoin(base_url, a["href"]) if a and a.has_attr("href") else None

        # category / tag
        tag_el = li.select_one(".mas-tag__text")
        category = tag_el.get_text(strip=True) if tag_el else None

        # date (try to find a DD Month YYYY pattern inside ancillaries)
        date = None
        anc = li.select_one(".mas-ancillaries")
        if anc:
            text = anc.get_text(" ", strip=True)
            m = re.search(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}", text)
            date = standardize_date(m.group(0)) if m else text.strip()

        # summary / body
        body_p = li.select_one(".mas-search-card__body p")
        summary = body_p.get_text(" ", strip=True) if body_p else None

        # topics / footer tags (may be multiple)
        topics = []
        for foot_a in li.select("footer a.mas-link .mas-link__text"):
            t = foot_a.get_text(" ", strip=True)
            if t and t not in topics:
                topics.append(t)

        # consultation fields (optional)
        consultation = {}
        for cf in li.select(".consultation-field"):
            label = cf.contents[0].strip() if cf.contents else ""
            span = cf.select_one("span")
            if span:
                consultation[label.rstrip(":")] = span.get_text(" ", strip=True)

        items.append(
            {
                "title": title,
                "url": href,
                "category": category,
                "date": date,
                "summary": summary,
                "topics": topics,
                "consultation_fields": consultation or None,
            }
        )

    return items


def regulation_history_scraper(url: str, category: str) -> List[Dict]:
    """
    Efficiently scrapes the amendment history from a MAS notice page and replaces the
    most recent entry's documents with the current document URL.

    This optimized function loads the page only once and extracts both the amendment
    history and current document URL from the same HTML content, making it approximately
    2x faster than calling regulation_history_scraper and extract_current_document_url separately.

    Args:
        url: The URL of the MAS notice page to scrape
        category: Category of the regulation ("Notices", "Guidelines", etc.)

    Returns:
        A list of amendment entries, each containing:
        - date: The date of the amendment
        - documents: List of documents with title and url

        The most recent entry (first in list) will have its documents replaced with
        a single document containing:
        - title: "Current Notice"
        - url: The current document URL from the "View Notice" button

    Example:
        >>> entries = combined_notice_scraper("https://www.mas.gov.sg/regulation/notices/notice-314")
        >>> (entries[0])
        {
            "date": "01 Jan 2024",
            "documents": [
                {
                    "title": "Current Notice",
                    "url": "https://www.mas.gov.sg/-/media/MAS/Notices/PDF/Notice-314.pdf"
                }
            ]
        }
    """

    def _fetch_page_html(url: str) -> str:
        """Fetch HTML content from URL using Selenium."""
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=0,0")
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        driver.get(url)
        html_content = driver.page_source
        driver.quit()
        return html_content

    def _extract_amendment_history(soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """Extract amendment history from the page."""
        dl = soup.find("dl", class_="mas-description-list")

        if not dl:
            return []

        amendment_entries = []
        for div in dl.find_all("div", recursive=False):
            dt = div.find("dt")
            dd = div.find("dd")

            if dt and dd:
                # Extract date and standardize format
                date = standardize_date(dt.get_text(strip=True))

                # Extract all PDF links from dd
                documents = []
                for link in dd.find_all("a", class_="mas-link"):
                    # Extract title
                    title_span = link.find("span", class_="mas-link__text")
                    title = title_span.get_text(strip=True) if title_span else ""

                    # Extract URL
                    doc_url = link.get("href", "")
                    if doc_url:
                        doc_url = urljoin(base_url, doc_url)

                    documents.append({"title": title, "url": doc_url})

                # Only add entry if it has documents
                if documents:
                    amendment_entries.append({"date": date, "documents": documents})

        return amendment_entries

    def _filter_document_types(
        amendment_entries: List[Dict], exclude_keywords: List[str]
    ) -> None:
        """Remove documents matching certain keywords from amendment entries."""
        for item in amendment_entries:
            if len(item.get("documents", [])) > 1:
                # Create a new list to avoid modification during iteration
                filtered_docs = [
                    doc
                    for doc in item.get("documents", [])
                    if not any(
                        keyword in doc.get("title", "") for keyword in exclude_keywords
                    )
                ]
                item["documents"] = filtered_docs

    def _convert_mmyyyy_to_standard_date(date_str: str) -> str:
        """
        Convert MM/YYYY format to standardized 'DD MMM YYYY' format.

        Args:
            date_str: Date string in MM/YYYY format (e.g., "02/2015")

        Returns:
            Standardized date string in 'DD MMM YYYY' format (e.g., "01 Feb 2015")
            Uses the 1st day of the month as default.
            Returns original string if parsing fails.

        Example:
            >>> _convert_mmyyyy_to_standard_date("02/2015")
            "01 Feb 2015"
        """
        try:
            # Parse MM/YYYY format
            parsed_date = datetime.strptime(date_str.strip(), "%m/%Y")
            # Return in standardized format with day=01
            return parsed_date.strftime("%d %b %Y")
        except ValueError:
            # If parsing fails, return original
            return date_str

    def _extract_current_document_url(soup: BeautifulSoup) -> dict:
        """
        Extract the current document URL and metadata from view button.

        Returns:
            dict: {"url": str, "button_text": str, "document_title": str}
                  or None if not found
        """
        strong_tag = (
            soup.find("strong", string="View Notice")
            or soup.find("strong", string="View Document")
            or soup.find("strong", string="View Circular")
        )

        if strong_tag:
            button_text = strong_tag.get_text(strip=True)
            pdf_link = strong_tag.parent.find("a", class_="mas-link")
            if pdf_link and pdf_link.get("href"):
                href = pdf_link["href"]
                url = f"https://www.mas.gov.sg{href}"

                # Extract document title from the link
                title_span = pdf_link.find("span", class_="mas-link__text")
                document_title = title_span.get_text(strip=True) if title_span else ""

                return {
                    "url": url,
                    "button_text": button_text,
                    "document_title": document_title,
                }

        return None

    def _handle_notices(amendment_entries: List[Dict], current_doc: dict) -> List[Dict]:
        """Handle Notices category: replace first entry with latest notice."""
        amendment_entries[0]["documents"] = [
            {
                "title": current_doc.get("document_title", "Latest Notice"),
                "url": current_doc["url"],
            }
        ]
        return amendment_entries

    def _handle_guidelines(
        amendment_entries: List[Dict], current_doc: dict
    ) -> List[Dict]:
        """Handle Guidelines category: create latest entry and preserve previous."""
        # Extract information from the first entry's first document
        first_doc = amendment_entries[0]["documents"][0]

        # Extract date from the document title (take the latest if multiple)
        date_matches = re.findall(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}", first_doc["title"])
        second_latest_date = (
            standardize_date(date_matches[-1]) if date_matches else "Previous Version"
        )
        second_latest_document_title = first_doc["title"]
        second_latest_document_link = first_doc["url"]

        # Update the first entry with the latest guideline
        amendment_entries[0]["documents"] = [
            {
                "title": current_doc.get("document_title", "Latest Guideline"),
                "url": current_doc["url"],
            }
        ]

        # Insert a second entry for the previous guideline
        amendment_entries.insert(
            1,
            {
                "date": second_latest_date,
                "documents": [
                    {
                        "title": second_latest_document_title,
                        "url": second_latest_document_link,
                    }
                ],
            },
        )

        return amendment_entries

    def _handle_default(amendment_entries: List[Dict], current_doc: dict) -> List[Dict]:
        """Handle default category: replace first entry with current document."""
        amendment_entries[0]["documents"] = [
            {"title": "Current Document", "url": current_doc["url"]}
        ]
        return amendment_entries

    def _handle_circulars(
        amendment_entries: List[Dict], current_doc: dict
    ) -> List[Dict]:
        """
        Handle Circulars category: create a single entry with current circular.

        Circulars have NO amendment history, only the current document.
        Extracts date in MM/YYYY format from the document title and converts it.

        Args:
            amendment_entries: Not used for Circulars (should be empty or ignored)
            current_doc: Dictionary containing url, button_text, and document_title

        Returns:
            List with a single entry containing the current circular
        """
        # Extract date from document title (format: MM/YYYY like "02/2015")
        document_title = current_doc.get("document_title", "")

        # Search for MM/YYYY pattern in the title
        date_match = re.search(r"\b(\d{2})/(\d{4})\b", document_title)

        if date_match:
            mm_yyyy = date_match.group(0)  # e.g., "02/2015"
            standardized_date = _convert_mmyyyy_to_standard_date(mm_yyyy)
        else:
            # Fallback: try to extract from amendment_entries if available
            standardized_date = (
                amendment_entries[0]["date"] if amendment_entries else "Unknown Date"
            )

        # Create single entry with current circular
        return [
            {
                "date": standardized_date,
                "documents": [
                    {
                        "title": document_title or "Latest Circular",
                        "url": current_doc["url"],
                    }
                ],
            }
        ]

    # Main execution flow
    base_url = "https://www.mas.gov.sg"

    # Step 1: Fetch page HTML
    html_content = _fetch_page_html(url)

    # Step 2: Parse HTML
    soup = BeautifulSoup(html_content, "html.parser")

    # Step 3: Extract current document info (needed for all categories)
    current_doc = _extract_current_document_url(soup)

    # Step 4: Extract amendment history
    amendment_entries = _extract_amendment_history(soup, base_url)

    # Step 5: Define all category handlers
    category_handlers = {
        "Notices": _handle_notices,
        "Guidelines": _handle_guidelines,
        "Circulars": _handle_circulars,
    }

    # Step 6: Special handling for Circulars (no amendment history needed)
    if category == "Circulars":
        if current_doc:
            return _handle_circulars(amendment_entries, current_doc)
        return []

    # Step 7: Early return if no history found (for other categories)
    if not amendment_entries:
        return []

    # Step 8: Filter unwanted document types
    _filter_document_types(amendment_entries, ["Amendment", "Cancellation"])

    # Step 9: Apply category-specific logic
    if current_doc:
        handler = category_handlers.get(category, _handle_default)
        amendment_entries = handler(amendment_entries, current_doc)

    return amendment_entries
