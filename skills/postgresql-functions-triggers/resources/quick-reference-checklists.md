# PostgreSQL Functions & Triggers - Quick Reference & Checklists

## SQL Quick Reference

### Function Declaration Modifiers

```sql
-- Language
LANGUAGE plpgsql | sql | python | javascript

-- Security
SECURITY INVOKER (default, respects RLS)
SECURITY DEFINER (runs as creator, bypasses RLS)

-- Volatility
IMMUTABLE (same input = same output, can be cached)
STABLE (within transaction, called once per statement)
VOLATILE (default, can return different values)

-- Parallelization
PARALLEL SAFE (can be parallelized)
PARALLEL UNSAFE (default, cannot be parallelized)
PARALLEL RESTRICTED (can run parallel but not in worker)

-- Strictness
STRICT (returns null if any arg is null, default behavior)
CALLED ON NULL INPUT (always executes, even with null args)

-- Return behavior
RETURNS NULL ON NULL INPUT (equivalent to STRICT)
LEAKPROOF (safe for row security, can't leak information)
```

### Common Function Types

| Pattern | Use Case | Return Type | Language | Volatility |
|---------|----------|-------------|----------|-----------|
| Validation | Check constraints | boolean | plpgsql | IMMUTABLE |
| Computation | Calculate values | scalar | sql/plpgsql | IMMUTABLE |
| Query | Fetch data | TABLE/SETOF | sql | STABLE |
| Side effects | Modify data | void/record | plpgsql | VOLATILE |
| State change | Update records | record | plpgsql | VOLATILE |
| Trigger | Event handler | TRIGGER | plpgsql | VOLATILE |

---

## Trigger Decision Tree

```
Does operation modify a row?
├─ YES → Use BEFORE trigger
│   ├─ Auto-compute field? → Use BEFORE ROW
│   ├─ Validate data? → Use BEFORE ROW
│   └─ Modify row value? → Use BEFORE ROW
│
└─ NO → Use AFTER trigger
    ├─ Record change? → Use AFTER ROW
    ├─ Update statistics? → Use AFTER STATEMENT
    └─ Send notification? → Use AFTER ROW
```

---

## Common Patterns Quick Copy

### Auto-Timestamp

```sql
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$ BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_timestamp_trigger
BEFORE UPDATE ON table_name
FOR EACH ROW
EXECUTE FUNCTION update_timestamp();
```

### Email Validation

```sql
CREATE OR REPLACE FUNCTION validate_email()
RETURNS TRIGGER AS $$ BEGIN
  IF NEW.email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$' THEN
    RAISE EXCEPTION 'Invalid email: %', NEW.email;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER validate_email_trigger
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION validate_email();
```

### Slug Generation

```sql
CREATE OR REPLACE FUNCTION generate_slug()
RETURNS TRIGGER AS $$ BEGIN
  NEW.slug := lower(regexp_replace(NEW.title, '[^a-z0-9]+', '-', 'g'));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER generate_slug_trigger
BEFORE INSERT OR UPDATE ON posts
FOR EACH ROW
WHEN (NEW.title IS DISTINCT FROM OLD.title)
EXECUTE FUNCTION generate_slug();
```

### Audit Logging

```sql
CREATE OR REPLACE FUNCTION audit_changes()
RETURNS TRIGGER AS $$ BEGIN
  INSERT INTO audit_logs (table_name, operation, old_data, new_data, changed_at)
  VALUES (TG_TABLE_NAME, TG_OP, row_to_json(OLD), row_to_json(NEW), now());
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON table_name
FOR EACH ROW
EXECUTE FUNCTION audit_changes();
```

### Counter Increment

```sql
CREATE OR REPLACE FUNCTION increment_counter()
RETURNS TRIGGER AS $$ BEGIN
  UPDATE counters SET value = value + 1
  WHERE id = NEW.counter_id;
  IF pg_trigger_depth() = 1 THEN
    -- Only at top level to prevent recursion
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Performance Tuning Checklist

- [ ] Used correct volatility classification (IMMUTABLE > STABLE > VOLATILE)
- [ ] Added WHEN clauses to triggers to skip unnecessary executions
- [ ] Indexed foreign key columns
- [ ] Used BEFORE ROW for modifications, AFTER ROW for side effects
- [ ] Wrapped recursive triggers with `pg_trigger_depth()` guards
- [ ] Profiled query execution with `EXPLAIN ANALYZE`
- [ ] Materialized expensive computations instead of calculating repeatedly
- [ ] Used SECURITY DEFINER for functions needing elevated privileges
- [ ] Added proper indexes on audit tables
- [ ] Considered partitioning for large audit log tables

---

## Error Messages & Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `permission denied for schema public` | Missing grant | `GRANT EXECUTE ON FUNCTION ... TO role;` |
| `infinite recursion detected` | Trigger updates same table | Use `pg_trigger_depth()` guard |
| `NEW is null` | Accessing NEW in DELETE | Use OLD instead |
| `unexpected end of file` | Missing `$$ LANGUAGE` | Check closing syntax |
| `function not found` | Function doesn't exist | `SELECT proname FROM pg_proc;` |
| `trigger not firing` | Wrong condition/disabled | Check `pg_trigger` and WHEN clause |
| `type mismatch` | Wrong return type | Verify RETURNS declaration |
| `constraint violation` | RLS or check constraint | Check policies and constraints |

---

## Supabase CLI Quick Commands

```bash
# Initialize project
supabase init

# Start local development
supabase start

# Create new migration
supabase migration new migration_name

# Apply migrations locally
supabase migration up

# Reset local database
supabase db reset

# Link to Supabase project
supabase link --project-ref your-project-id

# Push migrations to production
supabase db push

# Pull remote schema changes
supabase db pull

# Generate TypeScript types
supabase gen types typescript --linked > types/database.ts

# View logs
supabase logs

# Stop local services
supabase stop
```

---

## TypeScript Type Generation

### Generate Types from Functions

```bash
# Install Supabase CLI
npm install -g supabase

# Generate types (includes function signatures)
supabase gen types typescript --linked > src/lib/database.types.ts
```

### Example Generated Types

```typescript
export interface Database {
  public: {
    Tables: {
      posts: {
        Row: { id: string; title: string; slug: string; ... }
        Insert: { id?: string; title: string; ... }
        Update: { id?: string; title?: string; ... }
      }
    }
    Functions: {
      increment_counter: {
        Args: { counter_id: string; amount?: number }
        Returns: number
      }
      get_user_stats: {
        Args: { user_id: string }
        Returns: {
          total_posts: number
          total_comments: number
        }[]
      }
    }
  }
}
```

---

## RLS Policy Patterns

### Public Read, Owner Write

```sql
-- Readable by all
CREATE POLICY "posts_read_all" ON posts
FOR SELECT USING (true);

-- Writable only by owner
CREATE POLICY "posts_write_owner" ON posts
FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "posts_update_owner" ON posts
FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY "posts_delete_owner" ON posts
FOR DELETE USING (user_id = auth.uid());
```

### Admin Only

```sql
CREATE POLICY "admins_only" ON sensitive_table
FOR ALL
USING (
  auth.jwt() ->> 'role' = 'admin'
)
WITH CHECK (
  auth.jwt() ->> 'role' = 'admin'
);
```

### Multi-Tenant

```sql
CREATE POLICY "org_members_only" ON documents
FOR SELECT
USING (
  org_id IN (
    SELECT org_id FROM org_members
    WHERE user_id = auth.uid()
  )
);
```

---

## Testing Checklist

### Manual Testing (SQL)

```sql
-- Test trigger fires
INSERT INTO table_name (col1, col2) VALUES ('val1', 'val2');
SELECT * FROM audit_logs ORDER BY changed_at DESC LIMIT 1;

-- Test validation
INSERT INTO users (email) VALUES ('invalid');
-- Should raise exception

-- Test RLS
SET ROLE authenticated;
SET claim.sub = 'user-id-123';
SELECT * FROM users;
-- Should only see own data

-- Test performance
EXPLAIN ANALYZE SELECT * FROM large_table;

-- Check trigger status
SELECT tgname, tgenabled FROM pg_trigger WHERE relname = 'table_name';
```

### TypeScript Testing

```typescript
import { createClient } from '@supabase/supabase-js'

// Test function call
const { data, error } = await supabase.rpc('increment_counter', {
  counter_id: 'test-id',
})

// Test with error handling
try {
  const { data, error } = await supabase
    .from('posts')
    .insert({ title: 'Test' })
    .single()

  if (error) throw error
  console.log('Success:', data)
} catch (e) {
  console.error('Expected error:', e)
}
```

---

## Security Hardening Checklist

- [ ] RLS enabled on all sensitive tables
- [ ] Functions validate all inputs before use
- [ ] No hardcoded secrets in functions
- [ ] SECURITY DEFINER only used when necessary
- [ ] Dynamic SQL uses `format()` with `%I` and `%L`
- [ ] Passwords hashed with `crypt()` or bcrypt
- [ ] Sensitive data encrypted at rest
- [ ] Rate limiting implemented for sensitive operations
- [ ] Audit logging enabled for admin operations
- [ ] Error messages don't leak sensitive info

---

## Documentation Template for Functions

```sql
-- Function: increment_counter
-- Purpose: Increment a counter by specified amount
-- Arguments:
--   - counter_id: UUID of the counter to increment
--   - amount: Amount to increment by (default: 1)
-- Returns: New counter value (int)
-- Security: SECURITY INVOKER - respects caller's RLS
-- Performance: STABLE - called once per statement
-- Usage:
--   SELECT increment_counter('uuid-123', 5);
--   SELECT * FROM supabase.rpc('increment_counter', {
--     counter_id: 'uuid-123',
--     amount: 5
--   })
-- Notes: Trigger protection against concurrent updates recommended

CREATE OR REPLACE FUNCTION public.increment_counter(counter_id uuid, amount int DEFAULT 1)
RETURNS int
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
...
$$;
```

---

## Migration Rollback Strategy

```bash
# View migration history
supabase migration list

# Rollback last migration
supabase migration down

# Rollback to specific migration
supabase db reset
supabase migration up --version 20250120_000000
```

### Rollback SQL Pattern

```sql
-- Always include rollback SQL in migration file
-- Create
CREATE TABLE new_table (...);

-- Rollback (in separate migration)
-- DROP TABLE IF EXISTS new_table;

-- Create function
CREATE OR REPLACE FUNCTION my_function() ...

-- Rollback
-- DROP FUNCTION IF EXISTS my_function();
```

---

## Production Deployment Checklist

- [ ] Tested migrations locally with `supabase migration up`
- [ ] Tested rollback with `supabase migration down`
- [ ] Performance tested with realistic data volume
- [ ] RLS policies verified for all sensitive tables
- [ ] Function permissions granted to appropriate roles
- [ ] Triggers have `pg_trigger_depth()` guards where needed
- [ ] Error logging enabled
- [ ] Monitoring/alerts configured
- [ ] Backup created before deployment
- [ ] Deployment window scheduled during low-traffic period
- [ ] Rollback plan documented
- [ ] Team notified of changes

---

## Useful PostgreSQL System Views

```sql
-- List all functions
SELECT proname, pronargs FROM pg_proc WHERE pronamespace = 'public'::regnamespace;

-- List all triggers
SELECT tgname, tgrelid::regclass, tgenabled FROM pg_trigger WHERE tgrelid = 'table_name'::regclass;

-- List function with source
SELECT proname, prosrc FROM pg_proc WHERE proname = 'function_name';

-- Check function permissions
SELECT has_function_privilege(current_user, 'function_name(int)'::regprocedure, 'EXECUTE');

-- View trigger execution plan
EXPLAIN ANALYZE SELECT * FROM table_name WHERE id = 'test';

-- List table indexes
SELECT indexname FROM pg_indexes WHERE tablename = 'table_name';

-- Check RLS status
SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'table_name';

-- View RLS policies
SELECT polname, polcmd, polroles FROM pg_policy WHERE polrelid = 'table_name'::regclass;
```

---

## Resources & Documentation

### Official Documentation
- PostgreSQL PL/pgSQL: https://www.postgresql.org/docs/current/plpgsql.html
- PostgreSQL Triggers: https://www.postgresql.org/docs/current/sql-createtrigger.html
- Supabase Database Functions: https://supabase.com/docs/guides/database/functions
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security

### Community Resources
- PostgreSQL Wiki: https://wiki.postgresql.org/
- Supabase Discord: https://discord.supabase.com/
- Stack Overflow: Tag `postgresql` or `supabase`

### Tools
- pgAdmin: Web-based PostgreSQL management
- DBeaver: Universal database tool
- Supabase Studio: Built-in dashboard

---

**Last Updated**: January 2025  
**PostgreSQL**: 15+  
**Supabase**: Latest (2025)
