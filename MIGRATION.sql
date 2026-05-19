# Run this SQL in Supabase Studio SQL Editor ONCE before using the MCP

CREATE OR REPLACE FUNCTION public.execute_sql(query text, read_only boolean DEFAULT false)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  result jsonb;
BEGIN
  EXECUTE 'SELECT COALESCE(jsonb_agg(t), ''[]''::jsonb) FROM (' || query || ') t' INTO result;
  RETURN result;
EXCEPTION
  WHEN others THEN
    RAISE EXCEPTION 'Error executing SQL (SQLSTATE: %): %', SQLSTATE, SQLERRM;
END;
$$;

REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM anon;
REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.execute_sql(text, boolean) TO service_role;
NOTIFY pgrst, 'reload schema';
