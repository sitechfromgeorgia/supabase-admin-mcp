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
CREATE OR REPLACE FUNCTION public.execute_sql(query text, read_only boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
```

**Security:**
- Only `service_role` can call it — `MIGRATION.sql` revokes EXECUTE from `PUBLIC` (PostgreSQL's default grant!), `anon` and `authenticated`
- `SECURITY DEFINER` means it runs as the function owner (bypasses RLS)
- `SET search_path = public, pg_temp` prevents search-path attacks
- `read_only = true` (the default) is enforced at the database level: the query runs inside a read-only transaction, so writes fail with SQLSTATE 25006. Writes require an explicit `read_only = false`
- `EXPLAIN ... (FORMAT JSON)` is special-cased: it cannot be wrapped as a subquery, so it executes directly

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
Standard PostgreSQL introspection. Queries `information_schema`, `pg_catalog` (join-based; no string comparison on `regclass` output).

### SQL & Query (3 tools)
`execute_sql` is the powerhouse — any SQL. `explain_query` for performance (FORMAT JSON). `get_slow_queries` needs `pg_stat_statements`.

### Database Stats (9 tools)
Production monitoring: connections, locks, vacuum status, cache hit ratio, table sizes.

### Auth (5 tools)
Read `auth.users`, sessions, config. Uses `auth.` schema prefix in SQL. **No user creation/update** via this MCP (use Supabase Studio for that).

### Storage (4 tools)
Lists buckets/objects, reads config/metadata. Uses `/rest/v1/bucket`, `/rest/v1/object/` endpoints directly.

### RLS & Realtime (6 tools)
Row-Level Security policies, publications, WAL configuration. `get_advisors` runs a built-in subset of Supabase's linter checks (security/performance).

### Extensions (4 tools)
pg_cron, pgvector, available extensions.

### Edge Functions (2 tools)
List deployed functions, get function details. Gracefully reports when the `supabase_functions` schema is absent.

## Migration

Run [`../MIGRATION.sql`](../MIGRATION.sql) — it creates the function, enforces `read_only`, locks EXECUTE down to `service_role` and reloads the PostgREST schema cache. Re-run it after every upgrade; it is idempotent.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase instance URL |
| `SUPABASE_SERVICE_KEY` | Yes | service_role key (bypasses RLS) |

## GitHub

Repository: <https://github.com/sitechfromgeorgia/supabase-admin-mcp>
