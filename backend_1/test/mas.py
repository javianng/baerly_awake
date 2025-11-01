import re
from typing import Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


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
        >>> print(len(items))
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
            date = m.group(0) if m else text.strip()

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


def notice_history_scraper(url: str) -> List[Dict]:
    """
    Scrapes the amendment history from a MAS notice page.

    Args:
        url: The URL of the MAS notice page to scrape

    Returns:
        A list of amendment entries, each containing:
        - date: The date of the amendment
        - documents: List of documents with title and url

    Example:
        >>> entries = notice_history_scraper("https://www.mas.gov.sg/regulation/notices/notice-314")
        >>> print(entries)
        [
            {
                "date": "01 Jan 2024",
                "documents": [
                    {
                        "title": "Amendment Notice",
                        "url": "/path/to/document.pdf"
                    }
                ]
            }
        ]
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

    soup = BeautifulSoup(html_content, "html.parser")

    base_url = "https://www.mas.gov.sg"

    # Find the description list containing amendment notes
    dl = soup.find("dl", class_="mas-description-list")

    if not dl:
        return []

    # Find all div elements that contain dt/dd pairs
    amendment_entries = []

    for div in dl.find_all("div", recursive=False):
        dt = div.find("dt")
        dd = div.find("dd")

        if dt and dd:
            # Extract date
            date = dt.get_text(strip=True)

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

                document = {"title": title, "url": doc_url}

                documents.append(document)

            # Only add entry if it has documents
            if documents:
                amendment_entries.append({"date": date, "documents": documents})

    return amendment_entries


def extract_current_document_url(url: str) -> str:
    """
    Extracts the PDF document URL from a MAS notice page.

    This function navigates to a MAS notice page, locates the "View Notice" button,
    and extracts the direct URL to the current PDF document. It uses Selenium to
    render JavaScript-heavy pages and BeautifulSoup to parse the resulting HTML.

    Args:
        url: The URL of the MAS notice page (e.g., "https://www.mas.gov.sg/regulation/notices/notice-314")

    Returns:
        The full URL to the current PDF document on the MAS website

    Raises:
        AttributeError: If the expected HTML structure ("View Notice" button or link) is not found
        KeyError: If the link element doesn't have an 'href' attribute

    Example:
        >>> pdf_url = extract_current_document_url("https://www.mas.gov.sg/regulation/notices/notice-314")
        >>> print(pdf_url)
        "https://www.mas.gov.sg/-/media/MAS/Notices/PDF/Notice-314.pdf"
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

    soup = BeautifulSoup(html_content, "html.parser")

    strong_tag = soup.find(
        "strong", string="View Notice"
    )  # Locate the "View Notice" button
    pdf_link = strong_tag.parent.find(
        "a", class_="mas-link"
    )  # Navigate to the parent element and find the actual link with class "mas-link"
    href = pdf_link[
        "href"
    ]  # Extract the href attribute containing the relative path to the PDF

    return f"https://www.mas.gov.sg{href}"


def combined_notice_scraper(url: str) -> List[Dict]:
    """
    Scrapes the amendment history from a MAS notice page and replaces the most recent
    entry's documents with the current document URL.

    This function combines the functionality of notice_history_scraper and
    extract_current_document_url to provide a complete history where the most recent
    entry always points to the current/latest document via the "View Notice" button.

    Args:
        url: The URL of the MAS notice page to scrape

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
        >>> print(entries[0])
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
    # Get the full amendment history
    history_entries = notice_history_scraper(url)

    # If there are no history entries, return empty list
    if not history_entries:
        return []

    # Get the current document URL
    current_url = extract_current_document_url(url)

    # Replace the most recent entry's documents with the current document
    history_entries[0]["documents"] = [{"title": "Current Notice", "url": current_url}]

    return history_entries
