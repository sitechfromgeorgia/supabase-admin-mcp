#!/usr/bin/env python3
"""
supabase_admin_server.py — 47 self-hosted Supabase MCP tools.
All via REST API + execute_sql RPC. No DATABASE_URL needed.
"""

import os
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from client import SupabaseAdminClient

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://data.asistent.ge")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

client = SupabaseAdminClient(SUPABASE_URL, SERVICE_KEY)

app = FastMCP("supabase-admin", instructions="Self-hosted Supabase admin tools. 47 tools via REST API.")

_LINTER = "https://supabase.com/docs/guides/database/database-linter"


def _q(value: str) -> str:
    """Escape a value for safe use inside a single-quoted SQL literal."""
    return str(value).replace("'", "''")


def _lint(name: str, level: str, detail: str, anchor: str = "") -> dict:
    """Build one advisor item (mirrors the shape of Supabase's linter output)."""
    return {
        "name": name,
        "level": level,
        "detail": detail,
        "remediation": f"{_LINTER}?lint={anchor}" if anchor else _LINTER,
    }


@app.tool(description="Get configured Supabase project URL.")
async def supabase_get_project_url() -> dict:
    return {"project_url": SUPABASE_URL}


@app.tool(description="Check if JWT secret is configured.")
async def supabase_verify_jwt_secret() -> dict:
    return {"configured": bool(os.getenv("SUPABASE_AUTH_JWT_SECRET"))}


# ── Schema & Tables ──────────────────────────────────────────────────────

@app.tool(description="List tables in the database schemas.")
async def supabase_list_tables(schema: str = "public") -> list:
    return await client.sql(f"SELECT table_name, table_type, table_schema FROM information_schema.tables WHERE table_schema = '{_q(schema)}' ORDER BY table_name")


@app.tool(description="List installed PostgreSQL extensions.")
async def supabase_list_extensions() -> list:
    return await client.sql("SELECT * FROM pg_extension ORDER BY extname")


@app.tool(description="List applied migrations from supabase_migrations.schema_migrations")
async def supabase_list_migrations() -> list:
    try:
        return await client.sql("SELECT * FROM supabase_migrations.schema_migrations ORDER BY version")
    except Exception:
        return [{"note": "supabase_migrations.schema_migrations table not found. Run Supabase CLI migrations first."}]


@app.tool(description="List columns for a specific table.")
async def supabase_list_table_columns(table: str, schema: str = "public") -> list:
    return await client.sql(f"SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = '{_q(schema)}' AND table_name = '{_q(table)}' ORDER BY ordinal_position")


@app.tool(description="List indexes for a specific table.")
async def supabase_list_indexes(table: str = "", schema: str = "public") -> list:
    q = f"SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = '{_q(schema)}'"
    if table:
        q += f" AND tablename = '{_q(table)}'"
    return await client.sql(q + " ORDER BY tablename, indexname")


@app.tool(description="List constraints for a specific table.")
async def supabase_list_constraints(table: str = "", schema: str = "public", constraint_type: str = "") -> list:
    q = ("SELECT c.conname, c.contype, n.nspname AS schema_name, cl.relname AS table_name, "
         "pg_get_constraintdef(c.oid) AS definition "
         "FROM pg_constraint c "
         "JOIN pg_class cl ON cl.oid = c.conrelid "
         "JOIN pg_namespace n ON n.oid = cl.relnamespace "
         f"WHERE n.nspname = '{_q(schema)}'")
    if table:
        q += f" AND cl.relname = '{_q(table)}'"
    if constraint_type:
        types = {"PRIMARY KEY": "p", "FOREIGN KEY": "f", "UNIQUE": "u", "CHECK": "c", "EXCLUDE": "x"}
        q += f" AND c.contype = '{_q(types.get(constraint_type, constraint_type))}'"
    return await client.sql(q + " ORDER BY cl.relname, c.conname")


@app.tool(description="List foreign keys for a specific table.")
async def supabase_list_foreign_keys(table: str = "", schema: str = "public") -> list:
    q = ("SELECT c.conname, "
         "n.nspname || '.' || cl.relname AS source_table, "
         "tn.nspname || '.' || tcl.relname AS target_table, "
         "pg_get_constraintdef(c.oid) AS definition "
         "FROM pg_constraint c "
         "JOIN pg_class cl ON cl.oid = c.conrelid "
         "JOIN pg_namespace n ON n.oid = cl.relnamespace "
         "LEFT JOIN pg_class tcl ON tcl.oid = c.confrelid "
         "LEFT JOIN pg_namespace tn ON tn.oid = tcl.relnamespace "
         f"WHERE c.contype = 'f' AND n.nspname = '{_q(schema)}'")
    if table:
        q += f" AND cl.relname = '{_q(table)}'"
    return await client.sql(q + " ORDER BY cl.relname, c.conname")


@app.tool(description="List triggers for a specific table.")
async def supabase_list_triggers(table: str = "", schema: str = "public") -> list:
    q = f"SELECT trigger_name, event_manipulation, event_object_table, action_statement FROM information_schema.triggers WHERE trigger_schema = '{_q(schema)}'"
    if table:
        q += f" AND event_object_table = '{_q(table)}'"
    return await client.sql(q)


@app.tool(description="List user-defined database functions.")
async def supabase_list_functions(schema: str = "public") -> list:
    return await client.sql(f"SELECT proname, pronargs, lanname, prorettype::regtype FROM pg_proc WHERE pronamespace = '{_q(schema)}'::regnamespace ORDER BY proname")


@app.tool(description="Get function definition source code.")
async def supabase_get_function_definition(function_name: str, schema: str = "public") -> dict:
    r = await client.sql(f"SELECT prosrc FROM pg_proc WHERE proname = '{_q(function_name)}' AND pronamespace = '{_q(schema)}'::regnamespace LIMIT 1")
    return r[0] if r else {"error": "Function not found"}


@app.tool(description="Get trigger definition with function source.")
async def supabase_get_trigger_definition(trigger_name: str, table: str, schema: str = "public") -> dict:
    q = ("SELECT t.tgname, pg_get_triggerdef(t.oid) AS definition "
         "FROM pg_trigger t "
         "JOIN pg_class cl ON cl.oid = t.tgrelid "
         "JOIN pg_namespace n ON n.oid = cl.relnamespace "
         f"WHERE t.tgname = '{_q(trigger_name)}' AND n.nspname = '{_q(schema)}' AND cl.relname = '{_q(table)}'")
    r = await client.sql(q)
    return r[0] if r else {"error": "Trigger not found"}


# ── SQL & Query ──────────────────────────────────────────────────────────

@app.tool(description="Execute arbitrary SQL query. read_only=true by default and enforced in the database (read-only transaction). Set read_only=false explicitly for DDL/DML.")
async def supabase_execute_sql(query: str, read_only: bool = True) -> list:
    return await client.sql(query, read_only=read_only)


@app.tool(description="Get the query plan as JSON. WARNING: analyze=true actually executes the statement. Runs with read_only=true, so write statements cannot be EXPLAIN ANALYZEd.")
async def supabase_explain_query(sql: str, analyze: bool = False) -> list:
    mode = "ANALYZE, " if analyze else ""
    return await client.sql(f"EXPLAIN ({mode}FORMAT JSON) {sql}", read_only=True)


@app.tool(description="Get slow queries from pg_stat_statements (requires pg_stat_statements extension).")
async def supabase_get_slow_queries(limit: int = 10) -> list:
    ext = await client.sql("SELECT 1 AS ok FROM pg_extension WHERE extname = 'pg_stat_statements'")
    if not ext:
        return [{"note": "pg_stat_statements is not installed on this database."}]
    return await client.sql(f"SELECT query, calls, mean_exec_time, total_exec_time, rows FROM pg_stat_statements ORDER BY mean_exec_time DESC NULLS LAST LIMIT {int(limit)}")


# ── Database Stats ───────────────────────────────────────────────────────

@app.tool(description="Get active database connections.")
async def supabase_get_connections() -> list:
    return await client.sql("SELECT pid, state, query_start, wait_event, query FROM pg_stat_activity WHERE state IS NOT NULL AND pid <> pg_backend_pid() ORDER BY query_start DESC")


@app.tool(description="Get database statistics.")
async def supabase_get_stats() -> list:
    return await client.sql("SELECT * FROM pg_stat_database")


@app.tool(description="Get index usage statistics.")
async def supabase_get_index_stats(index_name: str = "", schema: str = "public") -> list:
    q = f"SELECT schemaname, relname AS tablename, indexrelname AS indexname, idx_scan, idx_tup_read, idx_tup_fetch FROM pg_stat_user_indexes WHERE schemaname = '{_q(schema)}'"
    if index_name:
        q += f" AND indexrelname = '{_q(index_name)}'"
    return await client.sql(q)


@app.tool(description="Get per-table disk usage.")
async def supabase_get_table_sizes(schema: str = "public", limit: int = 20) -> list:
    size = "pg_total_relation_size((quote_ident(schemaname) || '.' || quote_ident(tablename))::regclass)"
    return await client.sql(
        f"SELECT schemaname, tablename, pg_size_pretty({size}) AS total_size "
        f"FROM pg_tables WHERE schemaname = '{_q(schema)}' "
        f"ORDER BY {size} DESC LIMIT {int(limit)}")


@app.tool(description="Get buffer cache hit ratio.")
async def supabase_get_cache_hit_ratio() -> list:
    return await client.sql("SELECT 'buffer_cache' AS name, round(sum(blks_hit)::numeric / (CASE WHEN sum(blks_hit + blks_read) = 0 THEN 1 ELSE sum(blks_hit + blks_read) END) * 100, 2) AS hit_ratio FROM pg_stat_database")


@app.tool(description="Get current lock waits and blockers.")
async def supabase_get_locks(limit: int = 10) -> list:
    return await client.sql(f"SELECT pid, locktype, relation::regclass AS relation, mode, granted, waitstart FROM pg_locks WHERE NOT granted ORDER BY waitstart LIMIT {int(limit)}")


@app.tool(description="Get deadlock and rollback counters for the current database.")
async def supabase_get_deadlocks() -> list:
    return await client.sql("SELECT deadlocks, xact_rollback, xact_commit, stats_reset FROM pg_stat_database WHERE datname = current_database()")


@app.tool(description="Get vacuum/autovacuum status.")
async def supabase_get_autovacuum_status(schema: str = "public", limit: int = 20) -> list:
    return await client.sql(f"SELECT schemaname, relname, n_dead_tup, n_live_tup, last_vacuum, last_autovacuum, last_analyze FROM pg_stat_user_tables WHERE schemaname = '{_q(schema)}' ORDER BY n_dead_tup DESC LIMIT {int(limit)}")


@app.tool(description="Get connection pool stats.")
async def supabase_get_connection_pool_stats() -> list:
    return await client.sql("SELECT state, count(*) FROM pg_stat_activity GROUP BY state")


# ── Auth ─────────────────────────────────────────────────────────────────

@app.tool(description="List auth users. Uses execute_sql with SECURITY DEFINER to access auth.users.")
async def supabase_list_auth_users(limit: int = 50, offset: int = 0) -> list:
    return await client.sql(f"SELECT id, email, role, created_at, last_sign_in_at, email_confirmed_at FROM auth.users ORDER BY created_at DESC LIMIT {int(limit)} OFFSET {int(offset)}")


@app.tool(description="Get a specific auth user by ID.")
async def supabase_get_auth_user(user_id: str) -> dict | None:
    r = await client.sql(f"SELECT id, email, role, created_at, last_sign_in_at, email_confirmed_at, phone FROM auth.users WHERE id = '{_q(user_id)}' LIMIT 1")
    return r[0] if r else None


@app.tool(description="List active sessions for a user.")
async def supabase_list_user_sessions(user_id: str) -> list:
    return await client.sql(f"SELECT id, user_id, created_at, updated_at, factor_id FROM auth.sessions WHERE user_id = '{_q(user_id)}'")


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
    return await client.storage_get("bucket")


@app.tool(description="List objects in a storage bucket.")
async def supabase_list_storage_objects(bucket: str, prefix: str = "", limit: int = 100) -> list:
    return await client.storage_get(f"object/list/{quote(bucket, safe='')}", params={"prefix": prefix, "limit": int(limit)})


@app.tool(description="Get storage bucket configuration.")
async def supabase_get_storage_config(bucket_id: str = "") -> list | dict:
    if bucket_id:
        return await client.storage_get(f"bucket/{quote(bucket_id, safe='')}")
    return await client.storage_get("bucket")


@app.tool(description="Get metadata for a storage object.")
async def supabase_get_storage_object_metadata(bucket: str, path: str) -> dict | None:
    r = await client.storage_get(f"object/info/{quote(bucket, safe='')}/{quote(path.strip('/'), safe='/')}")
    if isinstance(r, dict):
        return r
    return r[0] if r else None


# ── RLS ──────────────────────────────────────────────────────────────────

@app.tool(description="List RLS policies for a table or schema.")
async def supabase_list_rls_policies(table: str = "", schema: str = "public") -> list:
    q = f"SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check FROM pg_policies WHERE schemaname = '{_q(schema)}'"
    if table:
        q += f" AND tablename = '{_q(table)}'"
    return await client.sql(q)


@app.tool(description="Get RLS enabled/disabled status for tables.")
async def supabase_get_rls_status(schema: str = "public") -> list:
    return await client.sql(f"SELECT relname AS table_name, relrowsecurity AS rls_enabled, relforcerowsecurity AS rls_forced FROM pg_class WHERE relnamespace = '{_q(schema)}'::regnamespace AND relkind = 'r' ORDER BY relname")


@app.tool(description="Run a built-in subset of Supabase's database linter (type: security | performance). For the full official advisor set use the official Supabase MCP.")
async def supabase_get_advisors(type: str = "security") -> dict:
    if type not in ("security", "performance"):
        return {"error": "type must be 'security' or 'performance'"}

    items: list[dict] = []

    if type == "security":
        rows = await client.sql(
            "SELECT n.nspname AS schema, c.relname AS name FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = 'public' AND NOT c.relrowsecurity "
            "ORDER BY c.relname")
        for r in rows:
            items.append(_lint("rls_disabled_in_public", "WARN",
                               f"Table {r['schema']}.{r['name']} has RLS disabled in the public schema",
                               "0013_rls_disabled_in_public"))

        rows = await client.sql(
            "SELECT n.nspname AS schema, c.relname AS name FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = 'public' AND c.relrowsecurity "
            "AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) "
            "ORDER BY c.relname")
        for r in rows:
            items.append(_lint("rls_enabled_no_policy", "INFO",
                               f"Table {r['schema']}.{r['name']} has RLS enabled, but no policies exist",
                               "0008_rls_enabled_no_policy"))

        rows = await client.sql(
            "SELECT schemaname, tablename, policyname, cmd FROM pg_policies "
            "WHERE schemaname = 'public' AND ("
            "  (cmd = 'INSERT' AND with_check = 'true') OR"
            "  (cmd = 'UPDATE' AND (qual = 'true' OR with_check = 'true')) OR"
            "  (cmd = 'DELETE' AND qual = 'true') OR"
            "  (cmd = 'ALL' AND qual = 'true')) "
            "ORDER BY tablename, policyname")
        for r in rows:
            items.append(_lint("rls_policy_always_true", "WARN",
                               f"Table {r['schemaname']}.{r['tablename']} — policy {r['policyname']} ({r['cmd']}) allows unrestricted access (always true)",
                               "0024_permissive_rls_policy"))

        rows = await client.sql(
            "SELECT n.nspname AS schema, c.relname AS name FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'v' AND n.nspname = 'public' "
            "AND NOT EXISTS (SELECT 1 FROM unnest(coalesce(c.reloptions, '{}'::text[])) AS opt(val) WHERE val = 'security_invoker=on') "
            "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e') "
            "ORDER BY c.relname")
        for r in rows:
            items.append(_lint("security_definer_view", "WARN",
                               f"View {r['schema']}.{r['name']} is not marked security_invoker — it runs with the view owner's privileges (querying user's RLS is bypassed). Add WITH (security_invoker = on) if this is not intended",
                               "0010_security_definer_view"))

        try:
            rows = await client.sql(
                "SELECT n.nspname AS schema, p.proname AS name, "
                "has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_can, "
                "has_function_privilege('authenticated', p.oid, 'EXECUTE') AS auth_can "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE p.prosecdef AND n.nspname = 'public' "
                "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') "
                "AND (has_function_privilege('anon', p.oid, 'EXECUTE') OR has_function_privilege('authenticated', p.oid, 'EXECUTE')) "
                "ORDER BY p.proname")
        except Exception:
            rows = []  # anon/authenticated roles do not exist (non-Supabase Postgres)
        for r in rows:
            if r.get("anon_can"):
                items.append(_lint("anon_security_definer_function_executable", "WARN",
                                   f"Function {r['schema']}.{r['name']}(...) can be executed by the anon role as SECURITY DEFINER",
                                   "0028_anon_security_definer_function_executable"))
            if r.get("auth_can"):
                items.append(_lint("authenticated_security_definer_function_executable", "WARN",
                                   f"Function {r['schema']}.{r['name']}(...) can be executed by the authenticated role as SECURITY DEFINER",
                                   "0029_authenticated_security_definer_function_executable"))

        rows = await client.sql(
            "SELECT n.nspname AS schema, p.proname AS name FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.prokind = 'f' "
            "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') "
            "AND (p.proconfig IS NULL OR NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) AS cfg(val) WHERE val LIKE 'search_path=%')) "
            "ORDER BY p.proname")
        for r in rows:
            items.append(_lint("function_search_path_mutable", "WARN",
                               f"Function {r['schema']}.{r['name']} has a mutable search_path — set it explicitly (e.g. SET search_path = public, pg_temp)",
                               "0011_function_search_path_mutable"))

        rows = await client.sql(
            "SELECT e.extname AS name FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE n.nspname = 'public' ORDER BY e.extname")
        for r in rows:
            items.append(_lint("extension_in_public", "WARN",
                               f"Extension {r['name']} is installed in the public schema — consider moving it to a dedicated schema",
                               "0014_extension_in_public"))

    else:  # performance
        rows = await client.sql(
            "SELECT n.nspname AS schema, cl.relname AS table_name, c.conname AS name "
            "FROM pg_constraint c JOIN pg_class cl ON cl.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "WHERE c.contype = 'f' AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indisvalid "
            "  AND (string_to_array(i.indkey::text, ' ')::int2[])[1:array_length(c.conkey, 1)] = c.conkey"
            ") ORDER BY cl.relname")
        for r in rows:
            items.append(_lint("unindexed_foreign_keys", "INFO",
                               f"Table {r['schema']}.{r['table_name']} — foreign key {r['name']} has no supporting index (slow joins/cascades)",
                               "0001_unindexed_foreign_keys"))

        rows = await client.sql(
            "SELECT n.nspname AS schema, c.relname AS name FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast') "
            "AND c.relpersistence <> 't' "
            "AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary) "
            "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e') "
            "ORDER BY n.nspname, c.relname")
        for r in rows:
            items.append(_lint("tables_without_primary_key", "INFO",
                               f"Table {r['schema']}.{r['name']} has no primary key",
                               "0004_tables_without_primary_key"))

        rows = await client.sql(
            "SELECT n.nspname AS schema, cl.relname AS table_name, "
            "string_agg(idx.relname, ', ' ORDER BY idx.relname) AS indexes "
            "FROM pg_index i JOIN pg_class cl ON cl.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = cl.relnamespace "
            "JOIN pg_class idx ON idx.oid = i.indexrelid "
            "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "GROUP BY n.nspname, cl.relname, i.indrelid, i.indkey::text "
            "HAVING count(*) > 1 ORDER BY cl.relname")
        for r in rows:
            items.append(_lint("duplicate_indexes", "INFO",
                               f"Table {r['schema']}.{r['table_name']} — duplicate indexes: {r['indexes']}",
                               "0009_duplicate_indexes"))

    return {"type": type, "total_count": len(items), "items": items}


# ── Realtime ─────────────────────────────────────────────────────────────

@app.tool(description="List PostgreSQL publications (e.g. supabase_realtime).")
async def supabase_list_publications() -> list:
    return await client.sql("SELECT * FROM pg_publication")


@app.tool(description="List tables enabled for Realtime (publication tables).")
async def supabase_list_realtime_channels() -> list:
    return await client.sql("SELECT * FROM pg_publication_tables")


@app.tool(description="Get Realtime/WAL configuration from pg_settings.")
async def supabase_get_realtime_config() -> list:
    return await client.sql("SELECT name, setting FROM pg_settings WHERE name IN ('wal_level', 'max_replication_slots', 'max_wal_senders', 'max_slot_wal_keep_size') ORDER BY name")


# ── Extensions ───────────────────────────────────────────────────────────

@app.tool(description="List pg_cron jobs (requires pg_cron extension).")
async def supabase_list_cron_jobs() -> list:
    schema = await client.sql("SELECT 1 AS ok FROM pg_namespace WHERE nspname = 'cron'")
    if not schema:
        return [{"note": "pg_cron is not installed (cron schema not found)."}]
    return await client.sql("SELECT jobid, schedule, command, nodename, database, username, active FROM cron.job ORDER BY jobid")


@app.tool(description="List pgvector indexes (requires pgvector extension).")
async def supabase_list_vector_indexes() -> list:
    return await client.sql("SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE indexdef LIKE '%vector%'")


@app.tool(description="Check pgvector extension status.")
async def supabase_get_vector_extension_status() -> dict:
    r = await client.sql("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'")
    return {"installed": len(r) > 0, "version": r[0]["extversion"] if r else None}


@app.tool(description="List available PostgreSQL extensions.")
async def supabase_list_available_extensions(show_installed: bool = True) -> list:
    q = "SELECT name, default_version, installed_version, comment FROM pg_available_extensions"
    if not show_installed:
        q += " WHERE installed_version IS NULL"
    return await client.sql(q + " ORDER BY name")


# ── Edge Functions ──────────────────────────────────────────────────────

@app.tool(description="List deployed Edge Functions.")
async def supabase_list_edge_functions() -> list:
    schema = await client.sql("SELECT 1 AS ok FROM pg_namespace WHERE nspname = 'supabase_functions'")
    if not schema:
        return [{"note": "supabase_functions schema not found — Edge Functions are not enabled on this instance."}]
    return await client.sql("SELECT * FROM supabase_functions.hooks ORDER BY created_at DESC")


@app.tool(description="Get Edge Function details by slug.")
async def supabase_get_edge_function_details(function_slug: str) -> dict | None:
    schema = await client.sql("SELECT 1 AS ok FROM pg_namespace WHERE nspname = 'supabase_functions'")
    if not schema:
        return {"note": "supabase_functions schema not found — Edge Functions are not enabled on this instance."}
    r = await client.sql(f"SELECT * FROM supabase_functions.hooks WHERE slug = '{_q(function_slug)}' LIMIT 1")
    return r[0] if r else None


# ── Help ─────────────────────────────────────────────────────────────────

@app.tool(description="List available tools with descriptions.")
async def supabase_get_help() -> dict:
    return {
        "name": "supabase-admin-mcp",
        "version": "0.2.0",
        "tools_count": 47,
        "categories": "Schema, SQL, Stats, Auth, Storage, RLS, Realtime, Extensions, Edge Functions",
        "note": "Requires execute_sql RPC in database. Run MIGRATION.sql first.",
    }


if __name__ == "__main__":
    app.run(transport="stdio")
