"""
PDF comparison utility for detecting changes between document versions.

This module provides functionality to compare two PDF documents and generate
LLM-friendly difference reports for impact analysis on analytical functions.

PDFs are automatically preprocessed in-place if red text is detected:
- If red text exists: first page and red text are removed, original PDF is overwritten
- If no red text: PDF is processed as-is
"""

import difflib
import os
import re
import shutil
import tempfile
from datetime import datetime
from typing import Dict, List, Tuple

import fitz  # PyMuPDF


def _int_to_rgb(color_int: int) -> Tuple[float, float, float]:
    """
    Convert PyMuPDF integer color to RGB tuple (0–1).

    Args:
        color_int: Integer representation of color from PyMuPDF

    Returns:
        Tuple of (r, g, b) values in range 0-1
    """
    r = ((color_int >> 16) & 255) / 255
    g = ((color_int >> 8) & 255) / 255
    b = (color_int & 255) / 255
    return (r, g, b)


def _is_red(color: Tuple[float, float, float]) -> bool:
    """
    Check if a color is red (tolerant to minor variations).

    Args:
        color: RGB tuple (r, g, b) in range 0-1

    Returns:
        True if color is predominantly red
    """
    r, g, b = color
    return r > 0.7 and g < 0.3 and b < 0.3


def _has_red_text(pdf_path: str) -> bool:
    """
    Detect if a PDF contains any red text.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        True if red text is found, False otherwise
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False

    has_red = False

    for page in doc:
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    color = span.get("color")
                    if isinstance(color, int):
                        color = _int_to_rgb(color)
                    if color and _is_red(color):
                        has_red = True
                        break
                if has_red:
                    break
            if has_red:
                break
        if has_red:
            break

    doc.close()
    return has_red


def _preprocess_pdf_inplace(pdf_path: str) -> None:
    """
    Preprocess a PDF in-place by removing first page and red text.
    Overwrites the original file.

    Args:
        pdf_path: Path to the PDF file to preprocess (will be overwritten)
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise FileNotFoundError(f"Failed to open PDF: {pdf_path}. Error: {str(e)}")

    if len(doc) == 0:
        doc.close()
        raise ValueError(f"PDF file is empty: {pdf_path}")

    # Remove first page
    if len(doc) > 0:
        doc.delete_page(0)

    # Remove red text from all remaining pages
    for page in doc:
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    color = span.get("color")
                    if isinstance(color, int):
                        color = _int_to_rgb(color)
                    if color and _is_red(color):
                        rect = fitz.Rect(span["bbox"])
                        page.add_redact_annot(rect)
        page.apply_redactions()

    # Save to a temporary file first (required to avoid incremental save restriction)
    temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_fd)

    try:
        doc.save(temp_path, garbage=4, deflate=True)
        doc.close()

        # Replace original file with the processed version
        shutil.move(temp_path, pdf_path)
    except Exception as e:
        # Clean up temp file if something goes wrong
        doc.close()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e


def _extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract clean text from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Clean text extracted from the PDF
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise FileNotFoundError(f"Failed to open PDF: {pdf_path}. Error: {str(e)}")

    if len(doc) == 0:
        doc.close()
        raise ValueError(f"PDF file is empty: {pdf_path}")

    all_text = []

    for page in doc:
        text = page.get_text("text")
        text = text.strip()
        if text:
            all_text.append(text)

    doc.close()

    # Join all pages with blank lines
    full_text = "\n\n".join(all_text)

    return full_text


def _clean_text(text: str) -> str:
    """
    Clean and normalize text from PDF extraction.

    Args:
        text: Raw text from PDF

    Returns:
        Cleaned text with normalized whitespace and removed hyphenation
    """
    # Remove hyphenation at line breaks (e.g., "regu-\nlation" → "regulation")
    text = re.sub(r"-\n", "", text)

    # Replace line breaks within paragraphs with a space
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    # Normalize multiple spaces to single space
    text = re.sub(r" +", " ", text)

    return text


def _split_text(text: str, mode: str = "sentence") -> List[str]:
    """
    Split text into segments for comparison.

    Args:
        text: Text to split
        mode: Split mode - "sentence", "paragraph", or "line"

    Returns:
        List of text segments
    """
    if mode == "sentence":
        # Split on sentence boundaries (., !, ?)
        segments = re.split(r"(?<=[.!?]) +", text)
    elif mode == "paragraph":
        # Split on paragraph breaks (double newlines or more)
        segments = re.split(r"\n\n+", text)
    elif mode == "line":
        # Split on single newlines
        segments = text.split("\n")
    else:
        raise ValueError(
            f"Invalid split_mode: {mode}. Must be 'sentence', 'paragraph', or 'line'"
        )

    # Filter out empty segments
    segments = [s.strip() for s in segments if s.strip()]

    return segments


def _detect_impact_indicators(text: str) -> Dict[str, bool]:
    """
    Detect indicators that suggest this change might be impactful.

    Args:
        text: Text to analyze

    Returns:
        Dictionary of impact indicator flags
    """
    indicators = {
        "contains_number": bool(re.search(r"\d+", text)),
        "contains_obligation": bool(
            re.search(
                r"\b(must|shall|required|mandatory|obligated|prohibited|forbidden|cannot|must not)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "contains_temporal": bool(
            re.search(
                r"\b(day|days|week|weeks|month|months|year|years|deadline|immediately|forthwith|within)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "contains_scope": bool(
            re.search(
                r"\b(all|any|each|every|none|no|only|solely|exclusively)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "contains_threshold": bool(
            re.search(
                r"\b(threshold|limit|maximum|minimum|exceed|below|above|at least|no more than)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "contains_financial": bool(
            re.search(
                r"[$€£¥]\s*[\d,]+|\b\d+\s*(dollars|euros|pounds|yen|USD|EUR|GBP|JPY|million|billion)\b",
                text,
                re.IGNORECASE,
            )
        ),
    }

    return indicators


def _get_context_window(
    segments: List[str], start_idx: int, end_idx: int, window_size: int = 2
) -> Tuple[str, str]:
    """
    Get context surrounding a change (sentences before and after).

    Args:
        segments: List of all text segments
        start_idx: Start index of the change
        end_idx: End index of the change
        window_size: Number of segments to include before and after

    Returns:
        Tuple of (context_before, context_after)
    """
    # Get context before
    context_start = max(0, start_idx - window_size)
    context_before = (
        " ".join(segments[context_start:start_idx]) if start_idx > 0 else ""
    )

    # Get context after
    context_end = min(len(segments), end_idx + window_size)
    context_after = (
        " ".join(segments[end_idx:context_end]) if end_idx < len(segments) else ""
    )

    # Truncate if too long
    if len(context_before) > 200:
        context_before = "..." + context_before[-200:]
    if len(context_after) > 200:
        context_after = context_after[:200] + "..."

    return context_before, context_after


def _format_change_for_llm(
    change_num: int,
    tag: str,
    old_text: str,
    new_text: str,
    context_before: str,
    context_after: str,
) -> str:
    """
    Format a single change in an LLM-friendly way.

    Args:
        change_num: Change number
        tag: Type of change ("replace", "delete", "insert")
        old_text: Original text (for replace/delete)
        new_text: New text (for replace/insert)
        context_before: Text before the change
        context_after: Text after the change

    Returns:
        Formatted change description
    """
    # Detect impact indicators
    combined_text = f"{old_text} {new_text}"
    indicators = _detect_impact_indicators(combined_text)
    active_indicators = [
        k.replace("contains_", "").replace("_", " ").title()
        for k, v in indicators.items()
        if v
    ]

    # Build the change block
    lines = []
    lines.append(f"\n{'=' * 80}")

    if tag == "replace":
        lines.append(f"[CHANGE {change_num} - REPLACEMENT]")
    elif tag == "delete":
        lines.append(f"[CHANGE {change_num} - DELETION]")
    elif tag == "insert":
        lines.append(f"[CHANGE {change_num} - ADDITION]")

    if active_indicators:
        lines.append(f"Impact Indicators: {', '.join(active_indicators)}")

    lines.append("")

    if tag == "replace":
        lines.append("Changed From:")
        lines.append(f'  "{old_text}"')
        lines.append("")
        lines.append("Changed To:")
        lines.append(f'  "{new_text}"')
    elif tag == "delete":
        lines.append("Removed:")
        lines.append(f'  "{old_text}"')
    elif tag == "insert":
        lines.append("Added:")
        lines.append(f'  "{new_text}"')

    if context_before:
        lines.append("")
        lines.append(f"Context Before: ...{context_before}...")

    if context_after:
        lines.append(f"Context After: ...{context_after}...")

    return "\n".join(lines)


def compare_pdf_documents(
    present_pdf_path: str, past_pdf_path: str, split_mode: str = "sentence"
) -> str:
    """
    Compare two PDF documents and return structured differences as a string.

    This function automatically preprocesses PDFs in-place if red text is detected:
    - If red text exists: removes first page and red text, overwrites original PDF
    - If no red text: processes PDF as-is

    Args:
        present_pdf_path: Path to the newer/current PDF document (may be overwritten)
        past_pdf_path: Path to the older/previous PDF document (may be overwritten)
        split_mode: How to split text for comparison - "sentence" (default),
                   "paragraph", or "line"

    Returns:
        String containing the structured differences (LLM-friendly format)

    Raises:
        FileNotFoundError: If either PDF file cannot be found or opened
        ValueError: If either PDF is empty or split_mode is invalid

    Example:
        >>> from app.utils import compare_pdf_documents
        >>>
        >>> # Automatically preprocesses and compares, returns diff string
        >>> changes = compare_pdf_documents(
        ...     present_pdf_path="test/current_notice.pdf",
        ...     past_pdf_path="test/old_notice.pdf"
        ... )
        >>>
        >>> # Pass to LLM for impact analysis
        >>> llm_response = llm.invoke(
        ...     f"Analyze these changes: {changes}"
        ... )
    """
    preprocessing_info = {"present": False, "past": False}

    # Check and preprocess present PDF if it has red text
    if _has_red_text(present_pdf_path):
        _preprocess_pdf_inplace(present_pdf_path)
        preprocessing_info["present"] = True

    # Check and preprocess past PDF if it has red text
    if _has_red_text(past_pdf_path):
        _preprocess_pdf_inplace(past_pdf_path)
        preprocessing_info["past"] = True

    # Extract text from both PDFs
    try:
        present_text = _extract_text_from_pdf(present_pdf_path)
        past_text = _extract_text_from_pdf(past_pdf_path)
    except Exception as e:
        raise Exception(f"Error extracting text from PDFs: {str(e)}")

    # Clean the text
    present_text = _clean_text(present_text)
    past_text = _clean_text(past_text)

    # Split into segments
    try:
        present_segments = _split_text(present_text, split_mode)
        past_segments = _split_text(past_text, split_mode)
    except ValueError as e:
        raise ValueError(f"Error splitting text: {str(e)}")

    # Compare using difflib
    matcher = difflib.SequenceMatcher(None, past_segments, present_segments)

    # Collect changes
    changes = []
    change_counts = {"additions": 0, "deletions": 0, "replacements": 0}
    change_num = 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        old_text = " ".join(past_segments[i1:i2])
        new_text = " ".join(present_segments[j1:j2])

        # Get context windows
        if tag == "delete":
            context_before, context_after = _get_context_window(past_segments, i1, i2)
            change_counts["deletions"] += 1
        elif tag == "insert":
            context_before, context_after = _get_context_window(
                present_segments, j1, j2
            )
            change_counts["additions"] += 1
        else:  # replace
            # Use present segments for context
            context_before, context_after = _get_context_window(
                present_segments, j1, j2
            )
            change_counts["replacements"] += 1

        # Format the change
        change_text = _format_change_for_llm(
            change_num=change_num,
            tag=tag,
            old_text=old_text,
            new_text=new_text,
            context_before=context_before,
            context_after=context_after,
        )

        changes.append(change_text)
        change_num += 1

    # Build the final report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("DOCUMENT COMPARISON REPORT")
    report_lines.append("=" * 80)
    report_lines.append(f"Present Document: {present_pdf_path}")
    report_lines.append(f"Past Document: {past_pdf_path}")
    report_lines.append(
        f"Comparison Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    report_lines.append(f"Comparison Mode: {split_mode}-level")

    # Add preprocessing info if applicable
    if preprocessing_info["present"] or preprocessing_info["past"]:
        report_lines.append("")
        report_lines.append("PREPROCESSING APPLIED (PDFs modified in-place):")
        if preprocessing_info["present"]:
            report_lines.append("  - Present PDF: first page removed, red text removed")
        if preprocessing_info["past"]:
            report_lines.append("  - Past PDF: first page removed, red text removed")

    report_lines.append("")

    total_changes = sum(change_counts.values())
    report_lines.append("SUMMARY")
    report_lines.append("-" * 80)
    report_lines.append(f"Total Changes: {total_changes}")
    report_lines.append(f"  - Additions: {change_counts['additions']}")
    report_lines.append(f"  - Deletions: {change_counts['deletions']}")
    report_lines.append(f"  - Replacements: {change_counts['replacements']}")
    report_lines.append("")

    if total_changes == 0:
        report_lines.append("No changes detected between the two documents.")
    else:
        report_lines.append("DETAILED CHANGES")
        report_lines.append("=" * 80)
        report_lines.extend(changes)

    report_lines.append("\n" + "=" * 80)
    report_lines.append("END OF REPORT")
    report_lines.append("=" * 80)

    return "\n".join(report_lines)
