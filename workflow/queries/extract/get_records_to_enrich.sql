-- =============================================================================
-- EXTRACT: Get records to enrich
-- =============================================================================
-- Selects customer records that either have never been enriched, or whose
-- enrichment data is stale (older than 30 days).
--
-- TEMPLATE NOTE: Adjust the LEFT JOIN target table and staleness window
-- to match your enrichment output table and refresh cadence.
-- =============================================================================

SELECT
  p.td_id,
  p.email,
  p.first_name,
  p.last_name,
  p.postcode,
  p.country,           -- CHANGE_ME: add/remove fields your API accepts as input

  -- Pass-through fields retained in output (not sent to API)
  p.persona,
  p.age,
  p.gender,
  p.time

FROM demo_lotto24.profile_attributes p

-- Only enrich records not yet enriched, or stale (>30 days old)
LEFT JOIN demo_lotto24.profile_attributes_enriched e
  ON p.td_id = e.td_id

WHERE e.td_id IS NULL
   OR e.enriched_at < TO_UNIXTIME(NOW() - INTERVAL '30' DAY)

-- CHANGE_ME: Add any additional filters here
-- e.g. only enrich customers with valid emails:
-- AND p.email LIKE '%@%'

LIMIT 10000  -- Safety cap — remove or increase for full runs
