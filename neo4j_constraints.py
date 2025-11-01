from neo4j import GraphDatabase

# --- Connection Details (Update these) ---
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "singhack"  # <-- Make sure this is your Neo4j password
# ----------------------------------------


def get_driver():
    """Establishes connection to Neo4j."""
    try:
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        driver.verify_connectivity()
        print("Neo4j connection successful.")
        return driver
    except Exception as e:
        print(f"Failed to connect to Neo4j: {e}")
        return None


def clear_database(tx):
    """Wipes all nodes and relationships from the database."""
    print("Clearing database...")
    tx.run("MATCH (n) DETACH DELETE n")


def create_constraints(tx):
    """Creates unique constraints for our graph schema."""
    print("Creating constraints...")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Rule) REQUIRE r.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")
    tx.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (con:Constraint) REQUIRE con.id IS UNIQUE"
    )
    # --- ADDED LINE ---
    tx.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (rv:RuleVersion) REQUIRE rv.version_id IS UNIQUE"
    )
    print("Constraints created successfully.")


if __name__ == "__main__":
    driver = get_driver()
    if driver:
        with driver.session() as session:
            # --- MODIFIED BLOCK ---
            # We NO LONGER wipe the database by default.
            # Wiping the DB destroys the audit trail.
            # To wipe the DB, you can manually uncomment the line below.
            # session.execute_write(clear_database)

            # Create constraints for our agent's schema
            session.execute_write(create_constraints)

        print("Neo4j database has been seeded with constraints.")
        # ... (rest of the file is unchanged) ...
