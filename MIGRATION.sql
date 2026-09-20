-- supabase-admin-mcp — one-time database setup
--
-- Run this ONCE in the SQL editor of your Supabase instance (or via psql as
-- the database owner) BEFORE using the MCP server.
--
-- What it does:
--   1. Creates public.execute_sql — the SECURITY DEFINER RPC the MCP uses for
--      all database access (runs with the owner's privileges, like any
--      service_role query).
--   2. Makes read_only = true an actual safety rail: the query runs inside a
--      read-only transaction, so INSERT/UPDATE/DELETE/DDL are rejected with
--      SQLSTATE 25006. Writes require an explicit read_only = false.
--   3. Restricts EXECUTE to service_role ONLY. This matters: PostgreSQL grants
--      EXECUTE on new functions to PUBLIC by default, and without the REVOKEs
--      below ANY anon key holder could run arbitrary SQL through
--      POST /rest/v1/rpc/execute_sql. Never skip the REVOKEs.
--
-- Statement handling:
--   - SELECT/WITH/... (subqueryable): rows come back as a JSON array.
--   - DDL/DML (CREATE, ALTER, INSERT, ...): executed directly and the RPC
--     returns {"status": "ok", "row_count": N}.
--   - EXPLAIN is a utility statement and cannot be captured from PL/pgSQL:
--     use the MCP explain tool (postgres-meta path) or Studio instead.
--
-- Re-run this file after every MCP upgrade — it is idempotent.

CREATE OR REPLACE FUNCTION public.execute_sql(query text, read_only boolean DEFAULT true)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  result jsonb;
  explain_result json;
  rowcount bigint;
BEGIN
  IF read_only THEN
    PERFORM set_config('transaction_read_only', 'on', true);
  END IF;

  -- EXPLAIN is a utility statement; PL/pgSQL cannot capture its output via
  -- EXECUTE ... INTO. Detect it with a plain string check instead of a regex
  -- (PostgreSQL regexes use \y for word boundaries; \b means backspace).
  -- Try to capture anyway, then fail with a clear message instead of
  -- silently swallowing the call.
  IF left(ltrim(lower(query), ' ' || chr(9) || chr(10) || chr(13)), 7) = 'explain' THEN
    BEGIN
      EXECUTE query INTO explain_result;
      RETURN explain_result::jsonb;
    EXCEPTION WHEN others THEN
      RAISE EXCEPTION 'EXPLAIN cannot be captured through execute_sql — use the supabase_explain_query tool or Studio (%)', SQLERRM;
    END;
  END IF;

  -- Subqueryable statements return their rows as a JSON array.
  BEGIN
    EXECUTE 'SELECT COALESCE(jsonb_agg(t), ''[]''::jsonb) FROM (' || query || ') t' INTO result;
  EXCEPTION WHEN syntax_error THEN
    -- Not subqueryable (DDL/DML/utility: CREATE, ALTER, INSERT, ...): run it
    -- directly and report a summary instead of rows.
    EXECUTE query;
    GET DIAGNOSTICS rowcount = ROW_COUNT;
    result := jsonb_build_object('status', 'ok', 'row_count', rowcount);
  END;

  RETURN result;
EXCEPTION
  WHEN read_only_sql_transaction THEN
    RAISE EXCEPTION 'read_only = true: statement rejected — the database is in read-only mode (pass read_only=false for writes)';
  WHEN others THEN
    RAISE EXCEPTION 'Error executing SQL (SQLSTATE: %): %', SQLSTATE, SQLERRM;
END;
$$;

REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM anon;
REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.execute_sql(text, boolean) TO service_role;

NOTIFY pgrst, 'reload schema';

-- Sanity check (optional): SELECT public.execute_sql('select 1 as ok');
