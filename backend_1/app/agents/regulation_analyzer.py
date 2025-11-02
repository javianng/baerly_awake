"""
LLM agent for analyzing regulatory changes and their compliance impact.

This module provides an agent that analyzes PDF comparison reports
to identify key changes, assess their impact, and assign severity levels.
"""

import os
from typing import List

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

load_dotenv()
MODEL = "openai/gpt-oss-120b"


class RegulationAnalysisOutput(BaseModel):
    """Structured output for regulation change analysis"""

    key_changes: List[str] = Field(
        description="List of key changes identified in the regulation update (3-7 bullet points)",
        min_items=1,
        max_items=10,
    )
    impact_analysis: str = Field(
        description="Detailed analysis of the compliance and operational impact of these changes"
    )
    severity: str = Field(
        description="Severity level of the changes: 'high', 'medium', or 'low'",
        pattern="^(high|medium|low)$",
    )
    affected_areas: List[str] = Field(
        description="List of affected compliance areas (e.g., KYC, Transaction Monitoring, AML, etc.)",
        default_factory=list,
    )


def analyze_regulation_changes(
    comparison_report: str, regulation_title: str
) -> RegulationAnalysisOutput:
    """
    Analyze regulatory changes using an LLM to identify key changes and assess impact.

    This function takes a PDF comparison report and uses an LLM to:
    1. Extract key changes from the comparison
    2. Assess the compliance impact
    3. Assign a severity level (high/medium/low)
    4. Identify affected compliance areas

    Args:
        comparison_report: The full PDF comparison report string from compare_pdf_documents()
        regulation_title: The title of the regulation being analyzed

    Returns:
        RegulationAnalysisOutput containing key_changes, impact_analysis, severity, and affected_areas

    Example:
        >>> comparison = compare_pdf_documents(new_pdf, old_pdf)
        >>> analysis = analyze_regulation_changes(comparison, "MAS Notice 626")
        >>> print(analysis.severity)
        "high"
        >>> print(analysis.key_changes)
        ["Updated customer due diligence thresholds from $50,000 to $25,000", ...]
    """
    # Initialize LangChain chat model
    llm = ChatOpenAI(
        model=MODEL,
        api_key=os.getenv("GROQ_API_KEY"),
        base_url=os.getenv("GROQ_API_BASE"),
        temperature=0.3,  # Lower temperature for more consistent analysis
    )

    # Create structured output parser
    structured_llm = llm.with_structured_output(RegulationAnalysisOutput)

    # Create prompt template
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are an expert regulatory compliance analyst specializing in financial services and AML regulations.

Your task is to analyze changes between two versions of a regulatory document and provide:
1. A concise list of key changes (3-7 bullet points focusing on material changes)
2. A detailed impact analysis explaining how these changes affect compliance operations
3. A severity assessment (high/medium/low) based on:
   - HIGH: Material changes to obligations, thresholds, deadlines, or prohibited activities
   - MEDIUM: Clarifications, process updates, or expanded guidance
   - LOW: Minor wording changes, formatting, or non-material updates
4. Affected compliance areas (e.g., KYC, Transaction Monitoring, Customer Due Diligence, Sanctions, etc.)

Focus on changes that impact:
- Regulatory obligations (must/shall/required/prohibited)
- Numerical thresholds or limits
- Deadlines and timeframes
- Scope of application (who/what is covered)
- New requirements or prohibitions
- Changes to risk assessments or due diligence

Ignore purely cosmetic changes like formatting, typos, or rewording that doesn't change meaning.""",
            ),
            (
                "user",
                """Analyze the following regulatory change for: {regulation_title}

PDF COMPARISON REPORT:
{comparison_report}

Provide a structured analysis of the key changes, their impact, and severity.""",
            ),
        ]
    )

    # Create chain
    chain = prompt | structured_llm

    # Invoke chain to get analysis
    result = chain.invoke(
        {
            "regulation_title": regulation_title,
            "comparison_report": comparison_report,
        }
    )

    # Ensure result is RegulationAnalysisOutput
    if isinstance(result, dict):
        return RegulationAnalysisOutput(**result)
    elif isinstance(result, RegulationAnalysisOutput):
        return result
    else:
        raise TypeError(f"Unexpected result type from chain.invoke: {type(result)}")


def format_key_changes_for_storage(key_changes: List[str]) -> str:
    """
    Format the key changes list as a nicely formatted string for database storage.

    Args:
        key_changes: List of key change strings

    Returns:
        Formatted string with bullet points

    Example:
        >>> changes = ["Change 1", "Change 2", "Change 3"]
        >>> formatted = format_key_changes_for_storage(changes)
        >>> print(formatted)
        • Change 1
        • Change 2
        • Change 3
    """
    return "\n".join([f"• {change}" for change in key_changes])
