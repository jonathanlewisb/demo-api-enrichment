-- =============================================================================
-- VALIDATE: Check enrichment output quality before promoting
-- =============================================================================
-- Returns quality metrics from the staging table.
-- The workflow will abort if null_enrichment_pct > 50.
-- =============================================================================

SELECT
  COUNT(*)                                                              AS total_records,
  COUNT(enriched_field_1)                                               AS enriched_count,
  ROUND(
    (COUNT(*) - COUNT(enriched_field_1)) * 100.0 / NULLIF(COUNT(*), 0)
  , 2)                                                                  AS null_enrichment_pct
FROM db_demo.api_enrichment_staging_${session_date_compact}
