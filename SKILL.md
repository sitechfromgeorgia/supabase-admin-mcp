# supabase-admin-mcp — Skill

Self-hosted Supabase admin tools. 47 tools, all via REST API. No DATABASE_URL needed.

## Config

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

## Prerequisites

Run `MIGRATION.sql` in Supabase Studio SQL Editor **once** to create the `execute_sql` RPC function. Without it, all tools return an error.

Since 0.2.0 the function enforces `read_only = true` (read-only transaction) and revokes EXECUTE from `PUBLIC`, `anon` and `authenticated` — re-run `MIGRATION.sql` after upgrading, or verify with `scripts/verify_setup.py`.

## Tools (47)

### Schema & Tables
| Tool | Description |
|------|-------------|
| `supabase_list_tables` | List tables in schema |
| `supabase_list_extensions` | Installed PostgreSQL extensions |
| `supabase_list_migrations` | Applied Supabase migrations |
| `supabase_list_table_columns` | Columns for a table |
| `supabase_list_indexes` | Indexes for a table |
| `supabase_list_constraints` | Constraints |
| `supabase_list_foreign_keys` | Foreign keys |
| `supabase_list_triggers` | Triggers |
| `supabase_list_functions` | User-defined functions |
| `supabase_get_function_definition` | Function source code |
| `supabase_get_trigger_definition` | Trigger definition |

### SQL & Query
| Tool | Description |
|------|-------------|
| `supabase_execute_sql` | Arbitrary SQL — `read_only=true` enforced unless explicitly `false` |
| `supabase_explain_query` | Query plan JSON (`analyze=true` executes; via postgres-meta) |
| `supabase_get_slow_queries` | Slow queries (pg_stat_statements) |

### Database Stats
| Tool | Description |
|------|-------------|
| `supabase_get_connections` | Active DB connections |
| `supabase_get_stats` | pg_stat_database |
| `supabase_get_index_stats` | Index usage stats |
| `supabase_get_table_sizes` | Per-table disk usage |
| `supabase_get_cache_hit_ratio` | Buffer cache hit ratio |
| `supabase_get_locks` | Lock waits and blockers |
| `supabase_get_deadlocks` | Deadlock/rollback counters |
| `supabase_get_autovacuum_status` | Vacuum status |
| `supabase_get_connection_pool_stats` | Connection pool |

### Auth
| Tool | Description |
|------|-------------|
| `supabase_list_auth_users` | auth.users list |
| `supabase_get_auth_user` | Single auth user |
| `supabase_list_user_sessions` | User sessions |
| `supabase_get_auth_settings` | Auth config |
| `supabase_check_pgcrypto` | pgcrypto check |

### Storage
| Tool | Description |
|------|-------------|
| `supabase_list_storage_buckets` | Storage buckets |
| `supabase_list_storage_objects` | Objects in bucket |
| `supabase_get_storage_config` | Bucket config |
| `supabase_get_storage_object_metadata` | Object metadata |

### RLS & Realtime
| Tool | Description |
|------|-------------|
| `supabase_list_rls_policies` | RLS policies |
| `supabase_get_rls_status` | RLS enabled/disabled |
| `supabase_get_advisors` | Built-in linter subset (security/performance) |
| `supabase_list_publications` | Realtime publications |
| `supabase_list_realtime_channels` | Tables enabled for Realtime |
| `supabase_get_realtime_config` | WAL / replication settings |

### Extensions & Edge
| Tool | Description |
|------|-------------|
| `supabase_list_cron_jobs` | pg_cron jobs |
| `supabase_list_vector_indexes` | pgvector indexes |
| `supabase_get_vector_extension_status` | Vector status |
| `supabase_list_available_extensions` | Available extensions |
| `supabase_list_edge_functions` | Deployed edge functions |
| `supabase_get_edge_function_details` | Function details |

## Architecture

```
SUPABASE_SERVICE_KEY → httpx → /rest/v1/rpc/execute_sql → PostgREST
                                    ↓
                              SECURITY DEFINER → DB access
```

**All via REST API (port 443). No direct DB ports needed. Works through Cloudflare.**
