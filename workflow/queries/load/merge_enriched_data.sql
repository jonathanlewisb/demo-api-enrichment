-- =============================================================================
-- LOAD: Merge enriched staging data into final output table
-- =============================================================================
-- Selects from the staging table for INSERT INTO the enriched output table.
-- The workflow uses insert_into: which appends; old records for the same
-- td_id are superseded on next query by ordering on enriched_at DESC.
--
-- CHANGE_ME: Replace enriched_field_1/2/3 with your actual API response fields.
-- =============================================================================

SELECT
  td_id,
  email,
  first_name,
  last_name,
  postcode,
  country,

  -- Original pass-through fields
  persona,
  age,
  gender,

  -- API enrichment fields — CHANGE_ME to match your API response
  enriched_field_1,
  enriched_field_2,
  enriched_field_3,

  -- Metadata
  enriched_at,
  api_provider,   -- which API produced this enrichment
  CAST(TO_UNIXTIME(NOW()) AS BIGINT) AS time

FROM demo_db.api_enrichment_staging_${session_date_compact}
WHERE enriched_field_1 IS NOT NULL  -- only promote successfully enriched records
