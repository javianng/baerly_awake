"""Populate a Neo4j knowledge graph from the transactions CSV dataset."""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from neo4j import GraphDatabase


def parse_bool(value: Optional[str]) -> Optional[bool]:
    """Return a boolean when the incoming CSV string represents one."""

    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if cleaned in {"true", "t", "yes", "y", "1"}:
        return True
    if cleaned in {"false", "f", "no", "n", "0"}:
        return False
    return None


def parse_float(value: Optional[str]) -> Optional[float]:
    """Convert a CSV field to float when possible."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(value: Optional[str]) -> Optional[int]:
    """Convert a CSV field to int when possible."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_date(value: Optional[str]) -> Optional[date]:
    """Parse assorted date formats present in the dataset."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO or day-first datetimes into Python datetime objects."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed
        except ValueError:
            continue
    return None


def normalize_str(value: Optional[str]) -> Optional[str]:
    """Trim strings and return None for empty cells."""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def compact_props(props: Dict[str, Any]) -> Dict[str, Any]:
    """Drop entries where the value is None."""

    return {key: value for key, value in props.items() if value is not None}


def transform_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Prepare Neo4j parameters from a CSV row."""

    origin_account_number = normalize_str(row.get("originator_account"))
    beneficiary_account_number = normalize_str(row.get("beneficiary_account"))
    if not origin_account_number or not beneficiary_account_number:
        raise ValueError("Both originator and beneficiary account numbers are required")

    booking_dt = parse_datetime(row.get("booking_datetime"))
    value_dt = parse_date(row.get("value_date"))

    transaction_props = compact_props(
        {
            "booking_datetime": booking_dt,
            "value_date": value_dt,
            "amount": parse_float(row.get("amount")),
            "currency": normalize_str(row.get("currency")),
            "swift_mt": normalize_str(row.get("swift_mt")),
            "swift_f50_present": parse_bool(row.get("swift_f50_present")),
            "swift_f59_present": parse_bool(row.get("swift_f59_present")),
            "swift_f70_purpose": normalize_str(row.get("swift_f70_purpose")),
            "swift_f71_charges": normalize_str(row.get("swift_f71_charges")),
            "travel_rule_complete": parse_bool(row.get("travel_rule_complete")),
            "fx_indicator": parse_bool(row.get("fx_indicator")),
            "fx_applied_rate": parse_float(row.get("fx_applied_rate")),
            "fx_market_rate": parse_float(row.get("fx_market_rate")),
            "fx_spread_bps": parse_float(row.get("fx_spread_bps")),
            "purpose_code": normalize_str(row.get("purpose_code")),
            "narrative": normalize_str(row.get("narrative")),
            "is_advised": parse_bool(row.get("is_advised")),
            "product_complex": parse_bool(row.get("product_complex")),
            "suitability_assessed": parse_bool(row.get("suitability_assessed")),
            "suitability_result": normalize_str(row.get("suitability_result")),
            "product_has_va_exposure": parse_bool(row.get("product_has_va_exposure")),
            "va_disclosure_provided": parse_bool(row.get("va_disclosure_provided")),
            "cash_id_verified": parse_bool(row.get("cash_id_verified")),
            "sanctions_screening": normalize_str(row.get("sanctions_screening")),
            "suspicion_determined_datetime": parse_datetime(
                row.get("suspicion_determined_datetime")
            ),
            "str_filed_datetime": parse_datetime(row.get("str_filed_datetime")),
        }
    )

    customer_props = compact_props(
        {
            "customer_type": normalize_str(row.get("customer_type")),
            "customer_risk_rating": normalize_str(row.get("customer_risk_rating")),
            "customer_is_pep": parse_bool(row.get("customer_is_pep")),
            "kyc_last_completed": parse_date(row.get("kyc_last_completed")),
            "kyc_due_date": parse_date(row.get("kyc_due_date")),
            "edd_required": parse_bool(row.get("edd_required")),
            "edd_performed": parse_bool(row.get("edd_performed")),
            "sow_documented": parse_bool(row.get("sow_documented")),
            "client_risk_profile": normalize_str(row.get("client_risk_profile")),
        }
    )

    snapshot_date = value_dt or (booking_dt.date() if booking_dt else None)
    daily_cash_snapshot = compact_props(
        {
            "snapshot_date": snapshot_date,
            "total": parse_float(row.get("daily_cash_total_customer")),
            "txn_count": parse_int(row.get("daily_cash_txn_count")),
        }
    )

    fx_details = {
        "indicator": parse_bool(row.get("fx_indicator")) is True,
        "base": normalize_str(row.get("fx_base_ccy")),
        "quote": normalize_str(row.get("fx_quote_ccy")),
        "applied_rate": parse_float(row.get("fx_applied_rate")),
        "market_rate": parse_float(row.get("fx_market_rate")),
        "spread_bps": parse_float(row.get("fx_spread_bps")),
        "counterparty": normalize_str(row.get("fx_counterparty")),
    }

    params = {
        "txn_id": normalize_str(row.get("transaction_id")),
        "txn_props": transaction_props,
        "booking_jurisdiction": normalize_str(row.get("booking_jurisdiction")),
        "regulator": normalize_str(row.get("regulator")),
        "channel": normalize_str(row.get("channel")),
        "product_type": normalize_str(row.get("product_type")),
        "currency": normalize_str(row.get("currency")),
        "origin_account": {
            "account_number": origin_account_number,
            "props": compact_props(
                {
                    "name": normalize_str(row.get("originator_name")),
                    "country": normalize_str(row.get("originator_country")),
                }
            ),
            "country": normalize_str(row.get("originator_country")),
        },
        "beneficiary_account": {
            "account_number": beneficiary_account_number,
            "props": compact_props(
                {
                    "name": normalize_str(row.get("beneficiary_name")),
                    "country": normalize_str(row.get("beneficiary_country")),
                }
            ),
            "country": normalize_str(row.get("beneficiary_country")),
        },
        "ordering_institution": {
            "bic": normalize_str(row.get("ordering_institution_bic")),
        },
        "beneficiary_institution": {
            "bic": normalize_str(row.get("beneficiary_institution_bic")),
        },
        "fx": fx_details,
        "customer": {
            "customer_id": normalize_str(row.get("customer_id")),
            "props": customer_props,
        },
        "daily_cash_snapshot": daily_cash_snapshot,
    }

    if not params["txn_id"]:
        raise ValueError("Transaction ID is required for each record")
    if not params["booking_jurisdiction"]:
        raise ValueError("Booking jurisdiction is required for each record")

    return params


def ensure_constraints(session: Any) -> None:
    """Create the uniqueness constraints required by the graph model."""

    statements = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Transaction) REQUIRE t.transaction_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Account) REQUIRE a.account_number IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (j:Jurisdiction) REQUIRE j.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Regulator) REQUIRE r.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Institution) REQUIRE i.bic IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (ch:Channel) REQUIRE ch.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Product) REQUIRE p.type IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cu:Currency) REQUIRE cu.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cp:Counterparty) REQUIRE cp.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cdc:CustomerDailyCash) REQUIRE (cdc.customer_id, cdc.snapshot_date) IS UNIQUE",
    ]
    for statement in statements:
        session.run(statement)


def ingest_record(tx: Any, params: Dict[str, Any]) -> None:
    """Create or update the graph for a single transaction."""

    tx.run(
        """
		MERGE (txn:Transaction {transaction_id: $txn_id})
		SET txn += $txn_props

		WITH txn
		MERGE (jur:Jurisdiction {code: $booking_jurisdiction})
		MERGE (txn)-[:BOOKED_IN]->(jur)

		WITH txn, jur
		FOREACH (regName IN CASE WHEN $regulator IS NULL THEN [] ELSE [$regulator] END |
			MERGE (reg:Regulator {name: regName})
			MERGE (jur)-[:REGULATED_BY]->(reg)
			MERGE (txn)-[:UNDER_SUPERVISION_OF]->(reg)
		)

		WITH txn
		MERGE (origAcc:Account {account_number: $origin_account.account_number})
		SET origAcc += $origin_account.props
		MERGE (txn)-[:ORIGINATED_FROM]->(origAcc)

		WITH txn, origAcc
		FOREACH (ocCode IN CASE WHEN $origin_account.country IS NULL THEN [] ELSE [$origin_account.country] END |
			MERGE (oc:Country {code: ocCode})
			MERGE (origAcc)-[:DOMICILED_IN]->(oc)
		)

		WITH txn, origAcc
		MERGE (benefAcc:Account {account_number: $beneficiary_account.account_number})
		SET benefAcc += $beneficiary_account.props
		MERGE (txn)-[:BENEFITS]->(benefAcc)

		WITH txn, origAcc, benefAcc
		FOREACH (bcCode IN CASE WHEN $beneficiary_account.country IS NULL THEN [] ELSE [$beneficiary_account.country] END |
			MERGE (bc:Country {code: bcCode})
			MERGE (benefAcc)-[:DOMICILED_IN]->(bc)
		)

		WITH txn, origAcc, benefAcc
		FOREACH (orderBic IN CASE WHEN $ordering_institution.bic IS NULL THEN [] ELSE [$ordering_institution.bic] END |
			MERGE (orderInst:Institution {bic: orderBic})
			MERGE (txn)-[:ORDERED_THROUGH]->(orderInst)
		)

		WITH txn, origAcc, benefAcc
		FOREACH (benefBic IN CASE WHEN $beneficiary_institution.bic IS NULL THEN [] ELSE [$beneficiary_institution.bic] END |
			MERGE (benefInst:Institution {bic: benefBic})
			MERGE (txn)-[:RECEIVED_AT]->(benefInst)
		)

		WITH txn, origAcc, benefAcc
		FOREACH (currCode IN CASE WHEN $currency IS NULL THEN [] ELSE [$currency] END |
			MERGE (curr:Currency {code: currCode})
			MERGE (txn)-[:SETTLED_IN]->(curr)
		)

		WITH txn, origAcc, benefAcc
		FOREACH (_ IN CASE WHEN $fx.indicator = true AND $fx.base IS NOT NULL AND $fx.quote IS NOT NULL THEN [1] ELSE [] END |
			MERGE (base:Currency {code: $fx.base})
			MERGE (quote:Currency {code: $fx.quote})
			MERGE (txn)-[fxrel:FX_BASE_DETAILS]->(base)
			SET fxrel.applied_rate = $fx.applied_rate,
				fxrel.market_rate = $fx.market_rate,
				fxrel.spread_bps = $fx.spread_bps
			MERGE (txn)-[:FX_QUOTE_CURRENCY]->(quote)
			FOREACH (cpName IN CASE WHEN $fx.counterparty IS NULL THEN [] ELSE [$fx.counterparty] END |
				MERGE (cp:Counterparty {name: cpName})
				MERGE (txn)-[:FX_WITH]->(cp)
			)
		)

		WITH txn, origAcc
		FOREACH (_ IN CASE WHEN $customer.customer_id IS NULL THEN [] ELSE [1] END |
			MERGE (cust:Customer {customer_id: $customer.customer_id})
			SET cust += $customer.props
			MERGE (cust)-[:OWNS_ACCOUNT]->(origAcc)
            MERGE (cust)-[:PARTY_TO]->(txn)
            FOREACH (_ IN CASE WHEN $daily_cash_snapshot.snapshot_date IS NULL THEN [] ELSE [1] END |
                MERGE (cash:CustomerDailyCash {customer_id: $customer.customer_id, snapshot_date: $daily_cash_snapshot.snapshot_date})
                SET cash.total = $daily_cash_snapshot.total,
                    cash.txn_count = $daily_cash_snapshot.txn_count
                MERGE (cust)-[:HAS_DAILY_CASH]->(cash)
            )
		)

		WITH txn
		FOREACH (chanName IN CASE WHEN $channel IS NULL THEN [] ELSE [$channel] END |
			MERGE (chan:Channel {name: chanName})
			MERGE (txn)-[:THROUGH_CHANNEL]->(chan)
		)

		WITH txn
		FOREACH (prodType IN CASE WHEN $product_type IS NULL THEN [] ELSE [$product_type] END |
			MERGE (prod:Product {type: prodType})
			MERGE (txn)-[:OF_PRODUCT]->(prod)
		)
		""",
        params,
    )


def load_csv_rows(csv_path: Path) -> Iterable[Dict[str, str]]:
    """Yield rows from the CSV file as dictionaries."""

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""

    default_csv = (
        Path(__file__).parent / "assets" / "transactions_mock_1000_for_participants.csv"
    )
    parser = argparse.ArgumentParser(description="Load transactions into Neo4j")
    parser.add_argument(
        "--csv",
        type=Path,
        default=default_csv,
        help="Path to the transactions CSV file",
    )
    parser.add_argument(
        "--uri",
        default=os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687"),
        help="Neo4j connection URI",
    )
    parser.add_argument(
        "--user", default=os.environ.get("NEO4J_USER", "neo4j"), help="Neo4j username"
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("NEO4J_PASSWORD", "singhack"),
        help="Neo4j password",
    )
    parser.add_argument(
        "--log-every",
        type=int,
        default=100,
        help="Print progress every N rows processed",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = args.csv
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    processed = 0

    try:
        with driver.session() as session:
            ensure_constraints(session)
            for raw_row in load_csv_rows(csv_path):
                params = transform_row(raw_row)
                session.execute_write(ingest_record, params)
                processed += 1
                if args.log_every and processed % args.log_every == 0:
                    print(f"Processed {processed} transactions...")
    finally:
        driver.close()

    print(f"Finished ingesting {processed} transactions into Neo4j.")


if __name__ == "__main__":
    main()
