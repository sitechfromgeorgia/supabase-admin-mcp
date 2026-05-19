# Skills for supabase-admin-mcp

This project works with Supabase at the admin level (service_role). These skills help the AI agent understand Supabase internals, RLS, PostgreSQL optimization, and more.

## Supabase Skills

| Skill | Location | Relevance |
|-------|----------|-----------|
| **supabase-rls-policies** | `C:\Users\SITECH\Desktop\For Agents\skills\supabase-rls-policies\SKILL.md` | RLS design — critical for understanding security policies this MCP manages |
| **supabase-postgres-best-practices** | `C:\Users\SITECH\Desktop\For Agents\skills\supabase-postgres-best-practices\SKILL.md` | PostgreSQL performance optimization — relevant for all SQL queries |
| **supabase-storage** | `C:\Users\SITECH\Desktop\For Agents\skills\supabase-storage\SKILL.md` | Storage API — referenced by storage tools |
| **supabase-migrations** | `C:\Users\SITECH\Desktop\For Agents\skills\supabase-migrations\SKILL.md` | DB migration patterns — relevant for schema tools |
| **supabase-edge-functions** | `C:\Users\SITECH\Desktop\For Agents\skills\supabase-edge-functions\SKILL.md` | Edge Functions — referenced by edge function tools |
| **postgresql-functions-triggers** | `C:\Users\SITECH\Desktop\For Agents\skills\postgresql-functions-triggers\SKILL.md` | PostgreSQL triggers/functions — relevant for database tools |
| **postgresql-production-setup** | `C:\Users\SITECH\Desktop\For Agents\skills\postgresql-production-setup\SKILL.md` | Production PostgreSQL — relevant for stats/monitoring tools |

## How to Use

When the AI agent needs Supabase-specific guidance, load the relevant skill:

1. `skill` tool → enter the skill name
2. Or manually reference the SKILL.md file

## Tool ↔ Skill Mapping

| MCP Tool | Related Skill |
|----------|---------------|
| `supabase_list_rls_policies` | supabase-rls-policies |
| `supabase_get_rls_status` | supabase-rls-policies |
| `supabase_get_advisors` | supabase-postgres-best-practices |
| `supabase_get_table_sizes` | postgresql-production-setup |
| `supabase_get_autovacuum_status` | postgresql-production-setup |
| `supabase_list_storage_buckets` | supabase-storage |
| `supabase_list_edge_functions` | supabase-edge-functions |
| `supabase_list_migrations` | supabase-migrations |
| `supabase_list_triggers` | postgresql-functions-triggers |
| `supabase_list_functions` | postgresql-functions-triggers |
