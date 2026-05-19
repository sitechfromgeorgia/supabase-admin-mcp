# supabase-admin-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**47 self-hosted Supabase admin tools — all via REST API. No DATABASE_URL needed.**

Works through Cloudflare, no direct PostgreSQL port required. Everything runs on HTTPS (port 443).

## Architecture

```
SUPABASE_SERVICE_KEY → httpx → /rest/v1/rpc/execute_sql → PostgREST → DB
                                    ↓
                              SECURITY DEFINER (bypasses RLS)
```

**No direct DB connection.** No `pg` pool. No port 5432/6543. Just REST.

## Prerequisites

### 1. Create `execute_sql` RPC Function

Run this SQL **once** in Supabase Studio SQL Editor:

```sql
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

The SQL is also in `MIGRATION.sql`.

### 2. Get Your Service Key

You need the `service_role` key from your Supabase instance. This key bypasses RLS.

## Quick Start

```bash
# Install dependencies
uv sync

# Set env vars and start
SUPABASE_SERVICE_KEY=eyJ... uv run server.py
```

### OpenCode Config

```jsonc
{
  "mcp": {
    "supabase-admin": {
      "type": "local",
      "command": ["uv", "run", "--directory", "PATH/TO/supabase-admin-mcp", "server.py"],
      "environment": { "SUPABASE_SERVICE_KEY": "eyJ..." }
    }
  }
}
```

## 47 Tools

### Schema & Tables (11 tools)

| Tool | Description |
|------|-------------|
| `supabase_list_tables` | List tables in schema |
| `supabase_list_extensions` | Installed PostgreSQL extensions |
| `supabase_list_migrations` | Applied Supabase migrations |
| `supabase_list_table_columns` | Columns for a table |
| `supabase_list_indexes` | Indexes |
| `supabase_list_constraints` | Constraints |
| `supabase_list_foreign_keys` | Foreign keys |
| `supabase_list_triggers` | Triggers |
| `supabase_list_functions` | User-defined functions |
| `supabase_get_function_definition` | Function source |
| `supabase_get_trigger_definition` | Trigger definition |

### SQL & Query (3 tools)

| Tool | Description |
|------|-------------|
| `supabase_execute_sql` | Execute arbitrary SQL (read_only default) |
| `supabase_explain_query` | EXPLAIN ANALYZE |
| `supabase_get_slow_queries` | Slow queries from pg_stat_statements |

### Database Stats (9 tools)

| Tool | Description |
|------|-------------|
| `supabase_get_connections` | Active DB connections |
| `supabase_get_stats` | Database statistics |
| `supabase_get_index_stats` | Index usage stats |
| `supabase_get_table_sizes` | Per-table disk usage |
| `supabase_get_cache_hit_ratio` | Buffer cache hit ratio |
| `supabase_get_locks` | Lock waits and blockers |
| `supabase_get_deadlocks` | Deadlock info |
| `supabase_get_autovacuum_status` | Vacuum status |
| `supabase_get_connection_pool_stats` | Connection pool summary |

### Auth (5 tools)

| Tool | Description |
|------|-------------|
| `supabase_list_auth_users` | List users from auth.users |
| `supabase_get_auth_user` | Get single auth user by ID |
| `supabase_list_user_sessions` | Active sessions for user |
| `supabase_get_auth_settings` | Auth config (MFA, providers) |
| `supabase_check_pgcrypto` | Check if pgcrypto is available |

### Storage (4 tools)

| Tool | Description |
|------|-------------|
| `supabase_list_storage_buckets` | List storage buckets |
| `supabase_list_storage_objects` | Objects in a bucket |
| `supabase_get_storage_config` | Bucket configuration |
| `supabase_get_storage_object_metadata` | Object metadata |

### RLS & Realtime (6 tools)

| Tool | Description |
|------|-------------|
| `supabase_list_rls_policies` | RLS policies |
| `supabase_get_rls_status` | RLS enabled/disabled per table |
| `supabase_get_advisors` | Security/performance notices |
| `supabase_list_publications` | Realtime publications |
| `supabase_list_realtime_channels` | Active Realtime channels |
| `supabase_get_realtime_config` | WAL level |

### Extensions & Edge (5 tools)

| Tool | Description |
|------|-------------|
| `supabase_list_cron_jobs` | pg_cron jobs |
| `supabase_list_vector_indexes` | pgvector indexes |
| `supabase_get_vector_extension_status` | Vector extension status |
| `supabase_list_available_extensions` | Available extensions |
| `supabase_list_edge_functions` | Deployed Edge Functions |

### Info (4 tools)

| Tool | Description |
|------|-------------|
| `supabase_get_project_url` | Configured Supabase URL |
| `supabase_verify_jwt_secret` | JWT secret status |
| `supabase_get_edge_function_details` | Edge Function details |
| `supabase_get_help` | This guide |

## Skills

9 Supabase skills bundled for reference:

| Skill | What it covers |
|-------|---------------|
| `supabase-rls-policies` | RLS design and multi-tenant isolation |
| `supabase-postgres-best-practices` | 39 PostgreSQL performance rules |
| `supabase-storage` | Storage API and configuration |
| `supabase-migrations` | Database migration patterns |
| `supabase-edge-functions` | Edge Function development |
| `supabase-auth-email-password` | Email/password auth patterns |
| `supabase-ssr-auth` | SSR authentication |
| `postgresql-functions-triggers` | PostgreSQL functions and triggers |
| `postgresql-production-setup` | Production PostgreSQL configuration |

## Security

- **Service key required** — never share with client-side code
- **All queries via REST** — no direct DB exposure
- **`execute_sql` restricted** to service_role only
- **Read-only default** — `read_only=True` prevents accidental writes
- **Pre-created RPC** — no auto-DDL on startup (unlike the old Bun version)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase instance URL (default: https://data.asistent.ge) |
| `SUPABASE_SERVICE_KEY` | Yes | Service role key |

## Repository

https://github.com/sitechfromgeorgia/supabase-admin-mcp
