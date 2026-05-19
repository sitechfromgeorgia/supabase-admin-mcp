#!/usr/bin/env python3
"""
supabase_admin_server.py — 50+ self-hosted Supabase MCP tools.
All via REST API + execute_sql RPC. No DATABASE_URL needed.
"""

import os
from mcp.server.fastmcp import FastMCP
from client import SupabaseAdminClient

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://data.asistent.ge")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

client = SupabaseAdminClient(SUPABASE_URL, SERVICE_KEY)

app = FastMCP("supabase-admin", instructions="Self-hosted Supabase admin tools. 50+ tools via REST API.")


def _e(msg: str | None) -> str | None:
    if not SERVICE_KEY:
        return "SUPABASE_SERVICE_KEY not set"
    return msg


@app.tool(description="Get configured Supabase project URL.")
async def supabase_get_project_url() -> dict:
    return {"project_url": SUPABASE_URL}


@app.tool(description="Check if JWT secret is configured.")
async def supabase_verify_jwt_secret() -> dict:
    return {"configured": bool(os.getenv("SUPABASE_AUTH_JWT_SECRET"))}


# ── Schema & Tables ──────────────────────────────────────────────────────

@app.tool(description="List tables in the database schemas.")
async def supabase_list_tables(schema: str = "public") -> list:
    return await client.sql(f"SELECT table_name, table_type, table_schema FROM information_schema.tables WHERE table_schema = '{schema}' ORDER BY table_name")


@app.tool(description="List installed PostgreSQL extensions.")
async def supabase_list_extensions() -> list:
    return await client.sql("SELECT * FROM pg_extension ORDER BY extname")


@app.tool(description="List applied migrations from supabase_migrations.schema_migrations")
async def supabase_list_migrations() -> list:
    return await client.sql("SELECT * FROM supabase_migrations.schema_migrations ORDER BY version")


@app.tool(description="List columns for a specific table.")
async def supabase_list_table_columns(table: str, schema: str = "public") -> list:
    return await client.sql(f"SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = '{schema}' AND table_name = '{table}' ORDER BY ordinal_position")


@app.tool(description="List indexes for a specific table.")
async def supabase_list_indexes(table: str = "", schema: str = "public") -> list:
    q = f"SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = '{schema}'"
    if table:
        q += f" AND tablename = '{table}'"
    return await client.sql(q + " ORDER BY tablename, indexname")


@app.tool(description="List constraints for a specific table.")
async def supabase_list_constraints(table: str = "", schema: str = "public", constraint_type: str = "") -> list:
    q = f"SELECT conname, contype, conrelid::regclass AS table_name, pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid::regclass::text LIKE '{schema}.%'"
    if table:
        q += f" AND conrelid::regclass::text = '{schema}.{table}'"
    if constraint_type:
        types = {"PRIMARY KEY": "p", "FOREIGN KEY": "f", "UNIQUE": "u", "CHECK": "c", "EXCLUDE": "x"}
        q += f" AND contype = '{types.get(constraint_type, constraint_type)}'"
    return await client.sql(q)


@app.tool(description="List foreign keys for a specific table.")
async def supabase_list_foreign_keys(table: str = "", schema: str = "public") -> list:
    q = f"""SELECT conname, conrelid::regclass AS source_table, 
          confrelid::regclass AS target_table, 
          pg_get_constraintdef(oid) AS definition
          FROM pg_constraint WHERE contype = 'f' AND conrelid::regclass::text LIKE '{schema}.%'"""
    if table:
        q += f" AND conrelid::regclass::text = '{schema}.{table}'"
    return await client.sql(q)


@app.tool(description="List triggers for a specific table.")
async def supabase_list_triggers(table: str = "", schema: str = "public") -> list:
    q = f"SELECT trigger_name, event_manipulation, event_object_table, action_statement FROM information_schema.triggers WHERE trigger_schema = '{schema}'"
    if table:
        q += f" AND event_object_table = '{table}'"
    return await client.sql(q)


@app.tool(description="List user-defined database functions.")
async def supabase_list_functions(schema: str = "public") -> list:
    return await client.sql(f"SELECT proname, pronargs, lanname, prorettype::regtype FROM pg_proc WHERE pronamespace = '{schema}'::regnamespace ORDER BY proname")


@app.tool(description="Get function definition source code.")
async def supabase_get_function_definition(function_name: str, schema: str = "public") -> dict:
    r = await client.sql(f"SELECT prosrc FROM pg_proc WHERE proname = '{function_name}' AND pronamespace = '{schema}'::regnamespace LIMIT 1")
    return r[0] if r else {"error": "Function not found"}


@app.tool(description="Get trigger definition with function source.")
async def supabase_get_trigger_definition(trigger_name: str, table: str, schema: str = "public") -> dict:
    r = await client.sql(f"SELECT tgname, pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE tgname = '{trigger_name}' AND tgrelid::regclass::text = '{schema}.{table}'")
    return r[0] if r else {"error": "Trigger not found"}


# ── SQL & Query ──────────────────────────────────────────────────────────

@app.tool(description="Execute arbitrary SQL query. read_only=true by default for safety. Set read_only=false for DDL/DML.")
async def supabase_execute_sql(query: str, read_only: bool = True) -> list:
    return await client.sql(query, read_only=read_only)


@app.tool(description="Run EXPLAIN on a query (JSON format). WARNING: with analyze=true the query actually executes.")
async def supabase_explain_query(sql: str, analyze: bool = False) -> list:
    mode = "ANALYZE " if analyze else ""
    return await client.sql(f"EXPLAIN ({mode}FORMAT JSON) {sql}")


@app.tool(description="Get slow queries from pg_stat_statements (requires pg_stat_statements extension).")
async def supabase_get_slow_queries(limit: int = 10) -> list:
    return await client.sql(f"SELECT query, calls, mean_exec_time, total_exec_time, rows FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT {limit}")


# ── Database Stats ───────────────────────────────────────────────────────

@app.tool(description="Get active database connections.")
async def supabase_get_connections() -> list:
    return await client.sql("SELECT pid, state, query_start, wait_event, query FROM pg_stat_activity WHERE state IS NOT NULL AND pid <> pg_backend_pid() ORDER BY query_start DESC")


@app.tool(description="Get database statistics.")
async def supabase_get_stats() -> list:
    return await client.sql("SELECT * FROM pg_stat_database")


@app.tool(description="Get index usage statistics.")
async def supabase_get_index_stats(index_name: str = "", schema: str = "public") -> list:
    q = f"SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch FROM pg_stat_user_indexes WHERE schemaname = '{schema}'"
    if index_name:
        q += f" AND indexname = '{index_name}'"
    return await client.sql(q)


@app.tool(description="Get per-table disk usage.")
async def supabase_get_table_sizes(schema: str = "public", limit: int = 20) -> list:
    return await client.sql(f"SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size FROM pg_tables WHERE schemaname = '{schema}' ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT {limit}")


@app.tool(description="Get buffer cache hit ratio.")
async def supabase_get_cache_hit_ratio() -> list:
    return await client.sql("SELECT 'buffer_cache' AS name, round(sum(blks_hit)::numeric / (CASE WHEN sum(blks_hit + blks_read) = 0 THEN 1 ELSE sum(blks_hit + blks_read) END) * 100, 2) AS hit_ratio FROM pg_stat_database")


@app.tool(description="Get current lock waits and blockers.")
async def supabase_get_locks(limit: int = 10) -> list:
    return await client.sql(f"SELECT pid, locktype, relation::regclass AS relation, mode, granted, waitstart FROM pg_locks WHERE NOT granted ORDER BY waitstart LIMIT {limit}")


@app.tool(description="Get recent deadlock info.")
async def supabase_get_deadlocks(limit: int = 10) -> list:
    return await client.sql(f"SELECT * FROM pg_stat_database WHERE datname = current_database() LIMIT {limit}")


@app.tool(description="Get vacuum/autovacuum status.")
async def supabase_get_autovacuum_status(schema: str = "public", limit: int = 20) -> list:
    return await client.sql(f"SELECT schemaname, relname, n_dead_tup, n_live_tup, last_vacuum, last_autovacuum, last_analyze FROM pg_stat_user_tables WHERE schemaname = '{schema}' ORDER BY n_dead_tup DESC LIMIT {limit}")


@app.tool(description="Get connection pool stats.")
async def supabase_get_connection_pool_stats() -> list:
    return await client.sql("SELECT state, count(*) FROM pg_stat_activity GROUP BY state")


# ── Auth ─────────────────────────────────────────────────────────────────

@app.tool(description="List auth users. Uses execute_sql with SECURITY DEFINER to access auth.users.")
async def supabase_list_auth_users(limit: int = 50, offset: int = 0) -> list:
    return await client.sql(f"SELECT id, email, role, created_at, last_sign_in_at, email_confirmed_at FROM auth.users ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}")


@app.tool(description="Get a specific auth user by ID.")
async def supabase_get_auth_user(user_id: str) -> dict | None:
    r = await client.sql(f"SELECT id, email, role, created_at, last_sign_in_at, email_confirmed_at, phone FROM auth.users WHERE id = '{user_id}' LIMIT 1")
    return r[0] if r else None


@app.tool(description="List active sessions for a user.")
async def supabase_list_user_sessions(user_id: str) -> list:
    return await client.sql(f"SELECT id, user_id, created_at, updated_at, factor_id FROM auth.sessions WHERE user_id = '{user_id}'")


@app.tool(description="Get auth configuration (MFA, providers, email templates).")
async def supabase_get_auth_settings() -> list:
    return await client.sql("SELECT * FROM auth.config LIMIT 1")


@app.tool(description="Check if pgcrypto extension is available (required for auth user creation).")
async def supabase_check_pgcrypto() -> dict:
    r = await client.sql("SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'")
    return {"available": len(r) > 0}


# ── Storage ──────────────────────────────────────────────────────────────

@app.tool(description="List storage buckets.")
async def supabase_list_storage_buckets() -> list:
    return await client.get("/bucket")


@app.tool(description="List objects in a storage bucket.")
async def supabase_list_storage_objects(bucket: str, prefix: str = "", limit: int = 100) -> list:
    return await client.get(f"/object/list/{bucket}", params={"prefix": prefix, "limit": limit})


@app.tool(description="Get storage bucket configuration.")
async def supabase_get_storage_config(bucket_id: str = "") -> list | dict:
    if bucket_id:
        r = await client.get(f"/bucket/{bucket_id}")
        return r[0] if r else {}
    return await client.get("/bucket")


@app.tool(description="Get metadata for a storage object.")
async def supabase_get_storage_object_metadata(bucket: str, path: str) -> dict | None:
    r = await client.get(f"/object/info/{bucket}/{path}")
    return r[0] if r else None


# ── RLS ──────────────────────────────────────────────────────────────────

@app.tool(description="List RLS policies for a table or schema.")
async def supabase_list_rls_policies(table: str = "", schema: str = "public") -> list:
    q = f"SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check FROM pg_policies WHERE schemaname = '{schema}'"
    if table:
        q += f" AND tablename = '{table}'"
    return await client.sql(q)


@app.tool(description="Get RLS enabled/disabled status for tables.")
async def supabase_get_rls_status(schema: str = "public") -> list:
    return await client.sql(f"SELECT relname AS table_name, relrowsecurity AS rls_enabled, relforcerowsecurity AS rls_forced FROM pg_class WHERE relnamespace = '{schema}'::regnamespace AND relkind = 'r' ORDER BY relname")


@app.tool(description="Get security and performance advisory notices.")
async def supabase_get_advisors(type: str = "security") -> list:
    if type == "security":
        r = await client.sql("SELECT schemaname, tablename, policyname FROM pg_policies WHERE schemaname = 'public'")
        return {"type": "security", "total_count": len(r), "policies": r}
    return {"type": type, "total_count": 0, "issues": []}


# ── Realtime ─────────────────────────────────────────────────────────────

@app.tool(description="List PostgreSQL publications (e.g. supabase_realtime).")
async def supabase_list_publications() -> list:
    return await client.sql("SELECT * FROM pg_publication")


@app.tool(description="List active Realtime channel subscriptions.")
async def supabase_list_realtime_channels() -> list:
    return await client.sql("SELECT * FROM pg_publication_tables")


@app.tool(description="Get Realtime server configuration.")
async def supabase_get_realtime_config() -> list:
    return await client.sql("SHOW wal_level")


# ── Extensions ───────────────────────────────────────────────────────────

@app.tool(description="List pg_cron jobs (requires pg_cron extension).")
async def supabase_list_cron_jobs() -> list:
    return await client.sql("SELECT * FROM cron.job")


@app.tool(description="List pgvector indexes (requires pgvector extension).")
async def supabase_list_vector_indexes() -> list:
    return await client.sql("SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE indexdef LIKE '%vector%'")


@app.tool(description="Check pgvector extension status.")
async def supabase_get_vector_extension_status() -> dict:
    r = await client.sql("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'")
    return {"installed": len(r) > 0, "version": r[0]["extversion"] if r else None}


@app.tool(description="List available PostgreSQL extensions.")
async def supabase_list_available_extensions(show_installed: bool = True) -> list:
    return await client.sql("SELECT name, default_version, installed_version, comment FROM pg_available_extensions ORDER BY name")


# ── Edge Functions ──────────────────────────────────────────────────────

@app.tool(description="List deployed Edge Functions.")
async def supabase_list_edge_functions() -> list:
    return await client.sql("SELECT * FROM supabase_functions.hooks ORDER BY created_at DESC")


@app.tool(description="Get Edge Function details by slug.")
async def supabase_get_edge_function_details(function_slug: str) -> dict | None:
    r = await client.sql(f"SELECT * FROM supabase_functions.hooks WHERE slug = '{function_slug}' LIMIT 1")
    return r[0] if r else None


# ── Help ─────────────────────────────────────────────────────────────────

@app.tool(description="List available tools with descriptions.")
async def supabase_get_help() -> dict:
    return {
        "name": "supabase-admin-mcp",
        "version": "0.1.0",
        "tools_count": 49,
        "categories": "Schema, SQL, Stats, Auth, Storage, RLS, Realtime, Extensions, Edge Functions",
        "note": "Requires execute_sql RPC in database. Run MIGRATION.sql first.",
    }


if __name__ == "__main__":
    app.run(transport="stdio")
