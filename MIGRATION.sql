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
BEGIN
  IF read_only THEN
    PERFORM set_config('transaction_read_only', 'on', true);
  END IF;

  -- EXPLAIN output cannot be wrapped as a subquery — run it directly.
  -- Use FORMAT JSON (single json row), e.g.: EXPLAIN (FORMAT JSON) SELECT ...
  IF query ~* '^\s*explain\b' THEN
    EXECUTE query INTO explain_result;
    RETURN explain_result::jsonb;
  END IF;

  EXECUTE 'SELECT COALESCE(jsonb_agg(t), ''[]''::jsonb) FROM (' || query || ') t' INTO result;
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
