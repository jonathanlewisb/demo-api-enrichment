"""
scripts/enrich.py
=============================================================================
API Enrichment Script — called by api_enrichment.dig via py> operator
=============================================================================

PURPOSE
-------
Reads customer records from a TD staging table, calls an external enrichment
API in batches, and writes the results back to TD.

TEMPLATE STRUCTURE
------------------
This script is split into three layers so only ONE section needs changing
per API integration:

  Layer 1 — TD I/O (do not change)
      Reads from / writes to Treasure Data via pytd.

  Layer 2 — API Client (CHANGE THIS for your API)
      EnrichmentAPIClient.enrich_batch() is the only method you swap out.
      The mock implementation below demonstrates the expected contract.

  Layer 3 — Orchestration (do not change)
      run_enrichment() is the entrypoint called by digdag.
      Handles batching, retries, error isolation, and TD writes.

SWITCHING TO A REAL API
-----------------------
1. Replace EnrichmentAPIClient.enrich_batch() with your real API call.
2. Update ENRICHMENT_OUTPUT_FIELDS to match your API's response fields.
3. Set secrets via:
     tdx wf secrets set api_enrichment.base_url "https://api.yourvendor.com/v1"
     tdx wf secrets set api_enrichment.api_key  "your-api-key"

EXAMPLE REAL INTEGRATIONS
--------------------------
- Clearbit Enrichment   → replace enrich_batch() with Clearbit /v2/combined/find
- FullContact           → replace with /v3/person.enrich
- OpenCage Geocoding    → replace with /geocode/v1/json (postcode → lat/lng)
- Any REST API          → follow the same contract (list[dict] in → list[dict] out)
=============================================================================
"""

import logging
import os
import time
import math
import requests
import pandas as pd
import pytd

logger = logging.getLogger(__name__)

# =============================================================================
# CHANGE_ME: List the fields your API returns that should be written to TD.
# These become columns in the enrichment output table.
# =============================================================================
ENRICHMENT_OUTPUT_FIELDS = [
    "enriched_field_1",   # e.g. "company_name"
    "enriched_field_2",   # e.g. "industry"
    "enriched_field_3",   # e.g. "employee_count"
]

# =============================================================================
# LAYER 2: API CLIENT — swap this class for your real API integration
# =============================================================================

class EnrichmentAPIClient:
    """
    Wraps the external enrichment API.

    Contract
    --------
    enrich_batch(records: list[dict]) -> list[dict]

    Each input record is a row dict from TD (keys = column names).
    Each output record must include at minimum:
      - td_id           (to join back to source)
      - enriched_at     (unix timestamp of enrichment)
      - api_provider    (string name of API used)
      - all fields in ENRICHMENT_OUTPUT_FIELDS (None if not available)
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key  = api_key
        self.session  = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        })

    def enrich_batch(self, records: list[dict]) -> list[dict]:
        """
        MOCK IMPLEMENTATION — replace this method for your real API.

        Real API example (Clearbit-style):
        -----------------------------------
        results = []
        for record in records:
            try:
                resp = self.session.get(
                    f"{self.base_url}/v2/combined/find",
                    params={"email": record["email"]},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                results.append({
                    "td_id":            record["td_id"],
                    "enriched_at":      int(time.time()),
                    "api_provider":     "clearbit",
                    "enriched_field_1": data.get("company", {}).get("name"),
                    "enriched_field_2": data.get("company", {}).get("category", {}).get("industry"),
                    "enriched_field_3": data.get("company", {}).get("metrics", {}).get("employees"),
                })
            except Exception as e:
                logger.warning(f"Failed to enrich td_id={record['td_id']}: {e}")
                results.append(_empty_result(record["td_id"]))
        return results
        """
        # ── MOCK: returns placeholder enrichment for demonstration ──────────
        results = []
        for record in records:
            results.append({
                "td_id":            record["td_id"],
                "enriched_at":      int(time.time()),
                "api_provider":     "mock_api",
                "enriched_field_1": f"mock_value_1_for_{record.get('td_id', 'unknown')}",
                "enriched_field_2": "mock_industry",
                "enriched_field_3": 42,
            })
        return results
        # ── END MOCK ─────────────────────────────────────────────────────────


def _empty_result(td_id: str) -> dict:
    """Returns a null-enrichment result for a failed record (keeps row in output)."""
    return {
        "td_id":        td_id,
        "enriched_at":  int(time.time()),
        "api_provider": "error",
        **{field: None for field in ENRICHMENT_OUTPUT_FIELDS},
    }


# =============================================================================
# LAYER 3: ORCHESTRATION — called by digdag py> operator
# =============================================================================

def run_enrichment(
    database:     str,
    source_table: str,
    output_table: str,
    api_base_url: str,
    api_key:      str,
    batch_size:   str,
    session_date: str,
) -> None:
    """
    Entrypoint for digdag py> operator.

    Reads source_table from TD, calls the enrichment API in batches,
    writes results to output_table in TD.
    """
    batch_size = int(batch_size)
    logger.info(f"Starting API enrichment | source={database}.{source_table} | "
                f"output={database}.{output_table} | session={session_date}")

    # ── Connect to TD ───────────────────────────────────────────────────────
    td_api_key = os.environ.get("TD_API_KEY") or os.environ.get("td.apikey")
    if not td_api_key:
        raise RuntimeError("TD_API_KEY environment variable not set")

    client = pytd.Client(
        apikey=td_api_key,
        endpoint="api.eu01.treasuredata.com",   # CHANGE_ME: us01 for US, ap02 for AP
        database=database,
    )

    # ── Read source records ─────────────────────────────────────────────────
    logger.info(f"Reading records from {database}.{source_table}")
    result   = client.query(f"SELECT * FROM {source_table}")
    df       = pd.DataFrame(**result)
    records  = df.to_dict(orient="records")
    total    = len(records)
    logger.info(f"Found {total} records to enrich")

    if total == 0:
        logger.info("No records to enrich — exiting")
        return

    # ── Initialise API client ───────────────────────────────────────────────
    api_client = EnrichmentAPIClient(base_url=api_base_url, api_key=api_key)

    # ── Process in batches ──────────────────────────────────────────────────
    num_batches  = math.ceil(total / batch_size)
    all_enriched = []

    for batch_num in range(num_batches):
        start = batch_num * batch_size
        end   = min(start + batch_size, total)
        batch = records[start:end]

        logger.info(f"Processing batch {batch_num + 1}/{num_batches} "
                    f"(records {start + 1}–{end})")

        try:
            enriched = api_client.enrich_batch(batch)
            all_enriched.extend(enriched)
        except Exception as e:
            logger.error(f"Batch {batch_num + 1} failed: {e}")
            # Emit null results for failed batch so we don't silently drop records
            all_enriched.extend([_empty_result(r["td_id"]) for r in batch])

        # Respect API rate limits — pause between batches
        if batch_num < num_batches - 1:
            time.sleep(0.5)   # CHANGE_ME: adjust to your API's rate limit

    # ── Merge with original pass-through fields ─────────────────────────────
    enriched_df   = pd.DataFrame(all_enriched)
    source_df     = df.drop(columns=[c for c in ENRICHMENT_OUTPUT_FIELDS if c in df.columns],
                            errors="ignore")
    final_df      = source_df.merge(enriched_df, on="td_id", how="left")

    # ── Write results to TD staging table ───────────────────────────────────
    logger.info(f"Writing {len(final_df)} enriched records to {database}.{output_table}")
    client.load_table_from_dataframe(
        final_df,
        output_table,
        writer="bulk_import",
        if_exists="overwrite",
    )

    logger.info(f"Enrichment complete — {len(final_df)} records written to "
                f"{database}.{output_table}")
