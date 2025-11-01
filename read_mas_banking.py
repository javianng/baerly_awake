"""
Parse ALL parts of MAS banking regulations and load into Neo4j using LLM agent,
including temporal versioning for a full audit trail.
"""

import openai
import os
import sys
import re
import html
from neo4j import GraphDatabase
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- NEO4J & APP CONFIGURATION ---
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "singhack"  # <-- Make sure this is your Neo4j password

# OpenRouter Configuration
OPENROUTER_API_BASE = "https://api.groq.com/openai/v1"
MODEL = "groq/compound"  # Use this if you prefer

# File path for the regulations
REGULATIONS_FILE_PATH = "assets/mas-banking-regulations.html"


def get_neo4j_driver():
    """Caches the Neo4j driver."""
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("✅ Neo4j connection successful.")
        return driver
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j. Is it running? Error: {e}")
        return None


def parse_mas_regulations_html(file_path):
    """
    Parses the entire MAS regulations HTML file and extracts ALL parts.
    This parser is from the user's provided script, designed to be comprehensive.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")

        # Find the main legislation content
        legis_div = soup.find("div", {"id": "legis"})
        if not legis_div:
            print("⚠️ Could not find 'legis' div, parsing entire document.")
            legis_div = soup

        parts = []

        # Find all 'part' or 'prov1' divs/tds, which seem to be the main containers
        sections = legis_div.find_all(
            ["td", "div"],
            class_=re.compile(r"^(part|prov1|schedule)$", re.IGNORECASE),
        )

        if not sections:
            print(
                "⚠️ No 'part' or 'prov1' sections found, trying simple <p> tag extraction."
            )
            sections = legis_div.find_all("p")

        print(f"📚 Found {len(sections)} potential sections to parse...")

        current_title = "Unknown Section"
        for idx, section in enumerate(sections):
            # Try to find a header within the section
            header = section.find(class_=re.compile(r"(Hdr|title)", re.IGNORECASE))
            if header:
                current_title = header.get_text(strip=True)

            content = html.unescape(section.get_text(separator=" ", strip=True))

            # Clean up title from content if it's there
            if content.startswith(current_title):
                content = content[len(current_title) :].strip()

            if content and len(content) > 50:
                parts.append(
                    {
                        "title": current_title,
                        "content": content,
                    }
                )

        # Deduplicate based on content similarity
        unique_parts = []
        seen_content_prefixes = set()

        for part in parts:
            content_prefix = part["content"][:200]
            if content_prefix not in seen_content_prefixes:
                unique_parts.append(part)
                seen_content_prefixes.add(content_prefix)

        print(f"\n✅ HTML Parsed Successfully!")
        print(f"   - Found {len(unique_parts)} unique regulatory sections\n")

        return unique_parts

    except FileNotFoundError:
        print(f"❌ Error: Regulations file not found at '{file_path}'")
        return None
    except Exception as e:
        print(f"❌ Error parsing HTML: {e}")
        import traceback

        traceback.print_exc()
        return None


def get_cypher_from_llm(regulatory_section, openrouter_key):
    """
    Calls the OpenRouter LLM to generate a TEMPORAL (versioned) Cypher query
    for a single regulatory section.
    """

    SYSTEM_PROMPT = """You are an expert AML compliance analyst and Neo4j database administrator.
Your task is to read a section of regulatory text and convert it into a valid, idempotent Cypher query to build a **temporal (versioned) knowledge graph**.

---
GRAPH SCHEMA (TEMPORAL):
- Master Rule: (r:Rule {id: "..."})
- Rule Version: (rv:RuleVersion {version_id: "...", valid_from: datetime(), valid_to: datetime() or null, description: "...", text: "..."})
- Concepts: (c:Concept {name: "...", label: "...", definition_text: "..."})
- Constraints: (co:Constraint {constraint_id: "...", type: "...", value: ..., unit: "...", raw_text: "..."})
- Relationships:
  - (r:Rule)-[:HAS_VERSION]->(rv:RuleVersion)
  - (rv_new:RuleVersion)-[:SUPERSEDES]->(rv_old:RuleVersion)
  - (Concept)-[:IS_DEFINED_AS_AGGREGATE_OF]->(Component:Concept)
  - (Concept)-[:EXCLUDES]->(Exclusion:Concept)
  - (rv:RuleVersion)-[:APPLIES_TO]->(c:Concept)
  - (rv:RuleVersion)-[:HAS_CONSTRAINT]->(co:Constraint)
  - (co:Constraint)-[:OF_CONCEPT]->(c:Concept)
---

CRITICAL CYPHER RULES:

1. **Idempotency & Versioning (AUDIT TRAIL):**
   - This is the most important rule. You must generate a query that creates a new version of a rule *only if the details have changed*.
   - **Step 1. Identify/Create Concepts:** `MERGE` all `Concept` nodes first. (e.g., `property_sector_exposure`).
   - **Step 2. Identify/Create Master Rule:** `MERGE` the master `Rule` node (e.g., `r:Rule {id: 'MAS_Reg_8_1'}`).
   - **Step 3. Check for Existing Active Version:**
     - `OPTIONAL MATCH (r)-[:HAS_VERSION]->(rv_old:RuleVersion) WHERE rv_old.valid_to IS NULL`
     - `OPTIONAL MATCH (rv_old)-[:HAS_CONSTRAINT]->(con_old:Constraint)`
   - **Step 4. Conditional Logic (THE CORE):**
     - Use `WITH ... CASE WHEN` to check if the *new* constraint is different from the *old* one.
     - `WITH r, rv_old, con_old, ...`
     - `... CASE WHEN (con_old.value <> 0.35) THEN 'create_v2' ...`
   - **Step 5. Handle all cases:**
     - `WHEN rv_old IS NULL THEN 'create_v1'` (No old version, create v1)
     - `WHEN con_old.value <> new_constraint_details.value OR rv_old.description <> new_description THEN 'create_v2'` (Old version exists and is different)
     - `ELSE 'no_change'` (Old version exists and is identical)
   - **Step 6. Use `FOREACH` to execute logic:**
     - `FOREACH (i IN CASE WHEN action = 'create_v1' THEN [1] ELSE [] END | ... create v1 nodes ...)`
     - `FOREACH (i IN CASE WHEN action = 'create_v2' THEN [1] ELSE [] END | SET rv_old.valid_to = datetime() ... create v2 nodes ...)`

2. **Atomic Transactional Pattern (User's Rule):**
   - Always follow this strict sequence:
     a. `MERGE` a node **only on its unique key** (e.g., `MERGE (r:Rule {id: '...'})`).
     b. `SET` all its properties (e.g., `SET r.description = '...'`).
     c. `WITH` that node (and prior variables).
     d. `MERGE` the next node.
     e. `SET` its properties.
     f. `WITH` all variables.
     g. `MERGE` the relationship(s).
   - **NEVER** `MERGE` on a property that can be `null` (like `valid_to: null`).

3. **Valid Query Termination (User's Rule):**
   - End with a `RETURN` clause.
   - **CRITICAL:** Only return variables that are in scope *before* the `FOREACH` blocks, such as `action` and `r`.
   - **DO NOT** attempt to return variables created *inside* a `FOREACH` block (like `rv_new` or `con_new`) as they will be out of scope.

---

OUTPUT REQUIREMENTS:
- Use `//` comments to separate logical sections.
- Output **only** valid Cypher code inside a ```cypher``` block.
- Do not output any explanation or commentary outside the code block.

---

EXAMPLE QUERY (Handling both v1 creation and v2 update):
```cypher
// 1. Identify Concepts from text
MERGE (c_pse:Concept {name: 'property_sector_exposure'})
SET c_pse.label = 'Property Sector Exposure',
    c_pse.definition_text = 'The aggregate of... (from definition text)'
WITH c_pse
MERGE (c_tea:Concept {name: 'total_eligible_assets'})
SET c_tea.label = 'Total Eligible Assets'
WITH c_pse, c_tea

// 2. Identify Master Rule
MERGE (r:Rule {id: 'MAS_Reg_8_1'})
SET r.description = 'Property sector exposure limit'
WITH r, c_pse, c_tea

// 3. Find current active version (if it exists)
OPTIONAL MATCH (r)-[:HAS_VERSION]->(rv_old:RuleVersion) WHERE rv_old.valid_to IS NULL
OPTIONAL MATCH (rv_old)-[:HAS_CONSTRAINT]->(con_old:Constraint)
WITH r, c_pse, c_tea, rv_old, con_old,
     // Define new values from the text
     { value: 0.35, type: 'MAX_PERCENTAGE_OF' } AS new_constraint_details,
     'Property sector exposure limit shall not exceed 35% of total eligible assets.' AS new_description,
     'PART IV ... 8. (1) ...' AS new_text

// 4. Check if an update is needed (old version exists AND is different, or no old version exists)
WITH r, c_pse, c_tea, rv_old, con_old, new_constraint_details, new_description, new_text,
     CASE 
       WHEN rv_old IS NULL THEN 'create_v1' // No old version, create v1
       WHEN con_old.value <> new_constraint_details.value OR rv_old.description <> new_description THEN 'create_v2' // Old version exists and is different
       ELSE 'no_change' // Old version exists and is identical
     END AS action

// 5. Do nothing if no change
WITH r, c_pse, c_tea, rv_old, con_old, new_constraint_details, new_description, new_text, action
WHERE action <> 'no_change'

// Generate a unique timestamp-based ID for new versions
WITH r, c_pse, c_tea, rv_old, con_old, new_constraint_details, new_description, new_text, action,
     toString(datetime.realtime().epochMillis) AS new_version_suffix

// 6. Create v1 if no old version
WITH r, c_pse, c_tea, rv_old, con_old, new_constraint_details, new_description, new_text, action, new_version_suffix,
     CASE WHEN action = 'create_v1' THEN [1] ELSE [] END AS create_v1_list
FOREACH (i IN create_v1_list |
  MERGE (rv_new:RuleVersion {version_id: r.id + '-v1'})
  SET rv_new.valid_from = datetime(),
      rv_new.valid_to = null,
      rv_new.description = new_description,
      rv_new.text = new_text
      
  MERGE (con_new:Constraint {constraint_id: r.id + '-Constraint-v1'})
  SET con_new.type = new_constraint_details.type,
      con_new.value = new_constraint_details.value,
      con_new.unit = 'percentage',
      con_new.raw_text = new_description

  MERGE (r)-[:HAS_VERSION]->(rv_new)
  MERGE (rv_new)-[:APPLIES_TO]->(c_pse)
  MERGE (rv_new)-[:HAS_CONSTRAINT]->(con_new)
  MERGE (con_new)-[:OF_CONCEPT]->(c_tea)
)

// 7. Create v2 if old version exists and is different
WITH r, c_pse, c_tea, rv_old, con_old, new_constraint_details, new_description, new_text, action, new_version_suffix,
     CASE WHEN action = 'create_v2' THEN [1] ELSE [] END AS create_v2_list
FOREACH (i IN create_v2_list |
  SET rv_old.valid_to = datetime()

  MERGE (rv_new:RuleVersion {version_id: r.id + '-v' + new_version_suffix})
  SET rv_new.valid_from = datetime(),
      rv_new.valid_to = null,
      rv_new.description = new_description,
      rv_new.text = new_text

  MERGE (con_new:Constraint {constraint_id: r.id + '-Constraint-v' + new_version_suffix})
  SET con_new.type = new_constraint_details.type,
      con_new.value = new_constraint_details.value,
      con_new.unit = 'percentage',
      con_new.raw_text = new_description
      
  MERGE (r)-[:HAS_VERSION]->(rv_new)
  MERGE (rv_new)-[:SUPERSEDES]->(rv_old)
  MERGE (rv_new)-[:APPLIES_TO]->(c_pse)
  MERGE (rv_new)-[:HAS_CONSTRAINT]->(con_new)
  MERGE (con_new)-[:OF_CONCEPT]->(c_tea)
)

// 8. Return the action taken and the master rule ID
RETURN action, r.id AS rule_id
```

---
USER REQUEST:
Title: "{title}"
Content: "{content}"
---
CYPHER QUERY:
"""

    client = openai.OpenAI(
        api_key=openrouter_key,
        base_url=OPENROUTER_API_BASE,
    )

    try:
        title = regulatory_section.get("title", "Unknown")
        content = regulatory_section.get("content", "")

        print(f"   🤖 Analyzing: {title[:60]}...")

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f'Title: "{title}"\n\nContent: "{content}"',
                },
            ],
            temperature=0.0,
        )

        content_result = response.choices[0].message.content
        if not content_result:
            print("      ⚠️  LLM returned empty response")
            return None

        cypher_query = content_result.strip()

        # Clean up the LLM's response
        if "```cypher" in cypher_query:
            cypher_query = cypher_query.split("```cypher")[1].split("```")[0].strip()
        elif "```" in cypher_query:
            # Fallback for just ```
            cypher_query = cypher_query.split("```", 1)[1].rsplit("```", 1)[0].strip()

        print(f"      ✅ Generated Cypher")
        return cypher_query

    except Exception as e:
        print(f"      ❌ Error calling LLM: {e}")
        return None


def execute_cypher(tx, cypher_query):
    """Execute a Cypher query."""
    tx.run(cypher_query)


def main():
    print("\n" + "=" * 70)
    print("🤖 AGENTIC REGULATORY INGESTION (Temporal Version)")
    print("=" * 70 + "\n")

    # 1. Load API Key
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key or openrouter_key == "YOUR_API_KEY_GOES_HERE":
        print("❌ OPENROUTER_API_KEY not found in .env file.")
        sys.exit(1)
    print("✅ OPENROUTER_API_KEY loaded.")

    # 2. Connect to Neo4j
    driver = get_neo4j_driver()
    if not driver:
        sys.exit(1)

    # 3. Parse ALL parts of the HTML
    print(f"\n📖 Parsing '{REGULATIONS_FILE_PATH}'...")
    regulatory_sections = parse_mas_regulations_html(REGULATIONS_FILE_PATH)

    if not regulatory_sections:
        print("❌ Failed to parse regulations.")
        driver.close()
        sys.exit(1)

    print(f"\n🔄 Processing {len(regulatory_sections)} sections...\n")

    # 4. Process each section
    successful = 0
    failed = 0
    skipped = 0

    for idx, section in enumerate(regulatory_sections, 1):
        print(f"--- Section {idx}/{len(regulatory_sections)} ---")
        print(f"TITLE: {section['title']}")

        # Generate Cypher
        cypher_query = get_cypher_from_llm(section, openrouter_key)

        if not cypher_query:
            print(f"      ⚠️  Skipping (no Cypher generated)")
            failed += 1
            print("-" * (len(section["title"]) + 8) + "\n")
            continue

        # Execute in Neo4j
        try:
            with driver.session() as session:
                result = session.execute_write(execute_cypher, cypher_query)
                print(f"      ✅ Loaded into Neo4j")
                successful += 1
        except Exception as e:
            print(f"      ❌ Neo4j Error: {e}")
            print(
                f"      --- Failing Cypher: ---\n{cypher_query}\n-------------------------"
            )
            failed += 1

        print("-" * (len(section["title"]) + 8) + "\n")

    # 5. Summary
    print("\n" + "=" * 70)
    print(f"✅ COMPLETED: {successful} sections loaded successfully")
    if failed > 0:
        print(f"❌ FAILED: {failed} sections had errors")
    if skipped > 0:
        print(f"ℹ️ SKIPPED: {skipped} sections (no change detected)")
    print("=" * 70 + "\n")

    driver.close()


if __name__ == "__main__":
    main()
