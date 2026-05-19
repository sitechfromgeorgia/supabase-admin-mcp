# supabase-admin-mcp — Documentation

## Architecture

```
┌─────────────────────┐      httpx       ┌──────────────────┐      REST API      ┌──────────┐
│  MCP Client         │ ────────────────► │  server.py       │ ────────────────► │ Supabase │
│  (OpenCode / Claude)│ ◄──────────────── │  47 tools        │ ◄──────────────── │ (Kong)   │
└─────────────────────┘      stdio        └──────────────────┘      HTTP/443     └──────────┘
                                             │                                         │
                                             │ execute_sql RPC                          │ PostgREST
                                             ▼                                         ▼
                                        client.py                             /rest/v1/rpc/
                                        (httpx AsyncClient)                   execute_sql
```

## Why No DATABASE_URL?

The old Bun MCP required `DATABASE_URL` (direct PostgreSQL connection at port 5432) for two reasons:
1. Auto-creating the `execute_sql` RPC function on startup
2. Tools that needed privileged schema access (auth, storage)

This Python version solves both via REST API:
1. `execute_sql` is pre-created in DB via `MIGRATION.sql`
2. Schema-qualified names (`auth.users`) in SQL bypass search_path limits
3. Storage via `/rest/v1/` with proper headers

## execute_sql RPC

The `execute_sql` function is the core of this MCP. It's a `SECURITY DEFINER` function — runs with the privileges of its owner (the user who created it, usually `postgres` or `supabase_admin`).

```sql
CREATE OR REPLACE FUNCTION public.execute_sql(query text, read_only boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
```

**Security:**
- Only `service_role` can call it (REVOKE from anon, authenticated)
- `SECURITY DEFINER` means it runs as the function owner (bypasses RLS)
- `SET search_path = public` prevents search-path attacks
- The MCP's `read_only=true` defaults to safe

### PostgreSQL Query Patterns

**Schema-qualified names for system catalogs:**
```sql
SELECT * FROM pg_stat_activity WHERE state IS NOT NULL
SELECT * FROM pg_indexes WHERE schemaname = 'public'
```

**Cross-schema queries (auth, storage):**
```sql
SELECT id, email FROM auth.users ORDER BY created_at DESC
SELECT * FROM storage.buckets
```

**The `public` search_path doesn't block schema-qualified queries.**

## Tool Categories

### Schema & Tables (11 tools)
Standard PostgreSQL introspection. Queries `information_schema`, `pg_catalog`.

### SQL & Query (3 tools)
`execute_sql` is the powerhouse — any SQL. `explain_query` for performance. `get_slow_queries` needs `pg_stat_statements` extension.

### Database Stats (9 tools)
Production monitoring: connections, locks, vacuum status, cache hit ratio, table sizes.

### Auth (5 tools)
Read `auth.users`, sessions, config. Uses `auth.` schema prefix in SQL. **No user creation/update** via this MCP (use Supabase Studio for that).

### Storage (4 tools)
Lists buckets/objects, reads config/metadata. Uses `/rest/v1/bucket`, `/rest/v1/object/` endpoints directly.

### RLS & Realtime (6 tools)
Row-Level Security policies, publications, WAL configuration.

### Extensions (4 tools)
pg_cron, pgvector, available extensions.

### Edge Functions (2 tools)
List deployed functions, get function details.

## Migration

```sql
-- Run ONCE in Supabase Studio SQL Editor
CREATE OR REPLACE FUNCTION public.execute_sql(query text, read_only boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE result jsonb; BEGIN
  EXECUTE 'SELECT COALESCE(jsonb_agg(t), ''[]''::jsonb) FROM (' || query || ') t' INTO result;
  RETURN result;
EXCEPTION WHEN others THEN RAISE EXCEPTION 'Error executing SQL (SQLSTATE: %): %', SQLSTATE, SQLERRM;
END; $$;
REVOKE ALL ON FUNCTION public.execute_sql(text, boolean) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.execute_sql(text, boolean) TO service_role;
NOTIFY pgrst, 'reload schema';
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase instance URL |
| `SUPABASE_SERVICE_KEY` | Yes | service_role key (bypasses RLS) |

## GitHub

Repository: <https://github.com/sitechfromgeorgia/supabase-admin-mcp>
