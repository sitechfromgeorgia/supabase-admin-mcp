---
name: PostgreSQL Functions & Triggers for Supabase
description: Complete guide to implementing PostgreSQL stored procedures, trigger functions, and database automation in Supabase with Next.js 15. Covers PL/pgSQL patterns, security, performance optimization, and best practices for AI coding agents.
tags: [postgres, supabase, plpgsql, triggers, functions, rpc, database-automation, nextjs]
---

# PostgreSQL Functions & Triggers for Supabase (2025 Guide)

## Quick Reference

### Trigger Types Comparison Table

| Type | Timing | Granularity | Use Cases | Access OLD/NEW |
|------|--------|-------------|-----------|---|
| **BEFORE ROW** | Before operation | Per row | Data validation, auto-timestamps, computed fields | YES (can modify) |
| **AFTER ROW** | After operation | Per row | Audit logs, cascade updates, denormalization | YES (read-only) |
| **AFTER STATEMENT** | After entire statement | Entire operation | Summary updates, aggregation | NO |
| **INSTEAD OF ROW** | Replace operation | Per row | Updatable views | YES |

### PostgreSQL Function Syntax Cheat Sheet

```sql
-- Basic function structure
CREATE OR REPLACE FUNCTION function_name(param1 type, param2 type)
RETURNS return_type
LANGUAGE plpgsql
[SECURITY DEFINER | SECURITY INVOKER]
[IMMUTABLE | STABLE | VOLATILE]
[PARALLEL SAFE | PARALLEL UNSAFE]
AS $$
DECLARE
  variable_name type;
BEGIN
  -- Function body
  RETURN result;
END;
$$ ;

-- Function return types
RETURNS void              -- No return value
RETURNS int               -- Scalar value
RETURNS table(col1 type, col2 type)  -- Named columns
RETURNS SETOF table_name  -- Set of rows
RETURNS json              -- JSON object
```

### Trigger Creation Template

```sql
-- Create trigger function
CREATE OR REPLACE FUNCTION trigger_function_name()
RETURNS TRIGGER AS $$
BEGIN
  -- Trigger logic
  RETURN NEW;  -- or OLD or NULL
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER trigger_name
BEFORE INSERT OR UPDATE OR DELETE ON table_name
FOR EACH ROW
[WHEN (condition)]
EXECUTE FUNCTION trigger_function_name();
```

---

## Core Concepts

### PL/pgSQL Fundamentals

**PL/pgSQL** is PostgreSQL's procedural language for stored functions and triggers. Key features:

- **Block structure**: `DECLARE`, `BEGIN`, `END`
- **Variables**: Declared in DECLARE block, must use `:=` for assignment
- **Control structures**: IF/ELSIF/ELSE, CASE, LOOP, EXIT
- **Records**: Can fetch entire rows into record variables
- **Exceptions**: BEGIN...EXCEPTION block for error handling

**Example: Basic structure**
```sql
CREATE OR REPLACE FUNCTION add_numbers(a int, b int)
RETURNS int AS $$
DECLARE
  result int;
BEGIN
  result := a + b;
  RETURN result;
END;
$$ LANGUAGE plpgsql;
```

### Special Trigger Variables

Automatically available in trigger functions:

| Variable | Type | Description |
|----------|------|-------------|
| `NEW` | record | New row for INSERT/UPDATE (null in DELETE) |
| `OLD` | record | Old row for UPDATE/DELETE (null in INSERT) |
| `TG_OP` | text | 'INSERT', 'UPDATE', 'DELETE' |
| `TG_TABLE_NAME` | text | Table name that fired trigger |
| `TG_LEVEL` | text | 'ROW' or 'STATEMENT' |
| `TG_WHEN` | text | 'BEFORE', 'AFTER', or 'INSTEAD OF' |
| `TG_ARGV` | text[] | Arguments passed to trigger |

### Function Volatility Classification

Choose the **strictest applicable category** for query optimization:

| Category | Can Modify DB | Returns Consistent Results | Examples | Optimization |
|----------|---|---|---|---|
| **IMMUTABLE** | No | Always (same input = same output) | Math, string functions | Cached, pre-computed |
| **STABLE** | No | Within same transaction | `now()`, `current_user` | Called once per statement |
| **VOLATILE** | Maybe | Different results possible | `random()`, triggers | Called every time (default) |

**Performance impact**: IMMUTABLE vs VOLATILE = 86% faster in benchmarks (AWS)

```sql
-- ✅ Good: Correctly classified
CREATE OR REPLACE FUNCTION age_bracket(age int)
RETURNS text AS $$
BEGIN
  RETURN CASE
    WHEN age < 13 THEN 'child'
    WHEN age < 18 THEN 'teen'
    ELSE 'adult'
  END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ❌ Wrong: Should be STABLE, not VOLATILE
CREATE OR REPLACE FUNCTION get_user_profile()
RETURNS json AS $$
  SELECT row_to_json(u) FROM users u WHERE id = auth.uid();
$$ LANGUAGE sql VOLATILE;  -- ← Should be STABLE
```

### SECURITY DEFINER vs INVOKER

**SECURITY INVOKER** (default):
- Function runs with **caller's permissions**
- Respects caller's RLS policies
- Safer but slower for complex queries
- Cannot bypass RLS

**SECURITY DEFINER**:
- Function runs with **creator's permissions** (usually superuser)
- **Bypasses RLS policies** on referenced tables
- Faster for complex multi-table operations
- **Security risk**: Only use if function validates inputs

**Best practice**: Use SECURITY DEFINER for RLS policy functions

```sql
-- ✅ SECURITY DEFINER for RLS policies
CREATE OR REPLACE FUNCTION has_admin_role()
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM roles_table 
    WHERE user_id = auth.uid() AND role = 'admin'
  );
END;
$$;

-- Use in RLS policy
CREATE POLICY "admins_can_delete"
ON posts FOR DELETE
USING (has_admin_role());
```

### Trigger Return Values

| Return Type | Trigger Type | Effect |
|---|---|---|
| `NULL` | BEFORE ROW | **Skip** the operation for this row |
| `NEW` (modified) | BEFORE ROW | Use modified row for operation |
| `NEW` (unmodified) | BEFORE ROW | Proceed with original row |
| `NULL` | AFTER ROW | Ignored (operation already done) |
| `NULL` | STATEMENT | Required (no row context) |

---

## Implementation Guide

### Step 1: Create Migration File

**Best practice**: Use CLI migrations, never SQL editor for production

```bash
# Create migration with timestamp
supabase migration new add_user_audit_function

# This creates: supabase/migrations/20250120_add_user_audit_function.sql
```

### Step 2: Define Function with Proper Classification

```sql
-- supabase/migrations/20250120_add_user_audit_function.sql

-- Create audit log table
CREATE TABLE IF NOT EXISTS audit_logs (
  id bigserial PRIMARY KEY,
  table_name text NOT NULL,
  operation text NOT NULL,
  user_id uuid NOT NULL REFERENCES auth.users(id),
  old_data jsonb,
  new_data jsonb,
  changed_at timestamp with time zone DEFAULT now()
);

-- Enable RLS on audit_logs
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Policy: Users see only their audit logs
CREATE POLICY "Users see own audit logs"
ON audit_logs FOR SELECT
USING (user_id = auth.uid());

-- Create trigger function with correct classification
CREATE OR REPLACE FUNCTION public.audit_user_changes()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    INSERT INTO audit_logs (table_name, operation, user_id, old_data, changed_at)
    VALUES (TG_TABLE_NAME, TG_OP, auth.uid(), row_to_json(OLD), now());
    RETURN OLD;
  ELSIF TG_OP = 'INSERT' THEN
    INSERT INTO audit_logs (table_name, operation, user_id, new_data, changed_at)
    VALUES (TG_TABLE_NAME, TG_OP, auth.uid(), row_to_json(NEW), now());
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO audit_logs (table_name, operation, user_id, old_data, new_data, changed_at)
    VALUES (TG_TABLE_NAME, TG_OP, auth.uid(), row_to_json(OLD), row_to_json(NEW), now());
    RETURN NEW;
  END IF;
  RETURN NULL;
END;
$$;
```

### Step 3: Create Trigger

```sql
-- Create trigger on users table
CREATE TRIGGER users_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON users
FOR EACH ROW
EXECUTE FUNCTION public.audit_user_changes();
```

### Step 4: Apply Migration

```bash
# Local testing
supabase migration up

# Deploy to production
supabase link
supabase db push
```

### Step 5: Call from Next.js 15

```typescript
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)
```

---

## Code Examples

### Example 1: Auto-Timestamp Trigger (BEFORE ROW)

**Use case**: Automatically update `updated_at` on every row modification

```sql
CREATE OR REPLACE FUNCTION public.update_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER update_timestamp_trigger
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION public.update_timestamp();
```

**TypeScript integration:**
```typescript
// Component.tsx
const handleUserUpdate = async (userId: string, name: string) => {
  const { data, error } = await supabase
    .from('users')
    .update({ name })
    .eq('id', userId)
    .select()

  // updated_at is automatically set by trigger
  console.log(data?.[0].updated_at) // Current timestamp
}
```

**Gold standard pattern**: Apply to ALL tables with timestamps
```sql
-- Generic reusable function
CREATE OR REPLACE FUNCTION public.update_timestamp()
RETURNS TRIGGER AS $$ BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

-- Apply to multiple tables
CREATE TRIGGER update_users_timestamp BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_posts_timestamp BEFORE UPDATE ON posts FOR EACH ROW EXECUTE FUNCTION update_timestamp();
CREATE TRIGGER update_comments_timestamp BEFORE UPDATE ON comments FOR EACH ROW EXECUTE FUNCTION update_timestamp();
```

---

### Example 2: Computed Column Trigger (BEFORE INSERT)

**Use case**: Auto-generate slug from title

```sql
CREATE OR REPLACE FUNCTION public.generate_slug()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.slug := lower(regexp_replace(NEW.title, '[^a-z0-9]+', '-', 'g'), '');
  RETURN NEW;
END;
$$;

CREATE TRIGGER generate_slug_trigger
BEFORE INSERT OR UPDATE ON posts
FOR EACH ROW
WHEN (NEW.title IS DISTINCT FROM OLD.title OR NEW.title IS NOT NULL)
EXECUTE FUNCTION public.generate_slug();
```

**TypeScript usage:**
```typescript
const { data } = await supabase
  .from('posts')
  .insert({ title: 'My First Blog Post' })
  .select()

console.log(data?.[0].slug) // 'my-first-blog-post' (auto-generated)
```

---

### Example 3: Validation Trigger (BEFORE INSERT/UPDATE)

**Use case**: Enforce business rules at database layer

```sql
CREATE OR REPLACE FUNCTION public.validate_user_data()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  -- Email validation
  IF NEW.email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$' THEN
    RAISE EXCEPTION 'Invalid email format: %', NEW.email;
  END IF;

  -- Age validation
  IF NEW.age < 0 OR NEW.age > 150 THEN
    RAISE EXCEPTION 'Invalid age: must be between 0 and 150';
  END IF;

  -- Credit limit validation
  IF NEW.credit_limit < 0 THEN
    RAISE EXCEPTION 'Credit limit cannot be negative';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER validate_user_trigger
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION public.validate_user_data();
```

**TypeScript error handling:**
```typescript
try {
  const { data, error } = await supabase
    .from('users')
    .insert({ email: 'invalid-email', age: 200 })

  if (error?.message.includes('Invalid')) {
    console.error('Validation failed:', error.message)
    // Display user-friendly error
  }
} catch (e) {
  console.error('Database error:', e)
}
```

---

### Example 4: Audit Log Trigger (AFTER ROW)

**Use case**: Track all changes to sensitive tables

```sql
-- Audit logs table
CREATE TABLE IF NOT EXISTS audit_logs (
  id bigserial PRIMARY KEY,
  table_name text NOT NULL,
  operation text NOT NULL, -- 'INSERT', 'UPDATE', 'DELETE'
  record_id uuid NOT NULL,
  changed_by uuid REFERENCES auth.users(id),
  old_values jsonb,
  new_values jsonb,
  changed_at timestamp with time zone DEFAULT now()
);

-- Audit trigger function
CREATE OR REPLACE FUNCTION public.audit_changes()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO audit_logs (table_name, operation, record_id, changed_by, new_values)
    VALUES (TG_TABLE_NAME, 'INSERT', NEW.id, auth.uid(), row_to_json(NEW));
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO audit_logs (table_name, operation, record_id, changed_by, old_values, new_values)
    VALUES (TG_TABLE_NAME, 'UPDATE', NEW.id, auth.uid(), row_to_json(OLD), row_to_json(NEW));
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO audit_logs (table_name, operation, record_id, changed_by, old_values)
    VALUES (TG_TABLE_NAME, 'DELETE', OLD.id, auth.uid(), row_to_json(OLD));
    RETURN OLD;
  END IF;
END;
$$;

-- Apply to sensitive tables
CREATE TRIGGER audit_users_trigger AFTER INSERT OR UPDATE OR DELETE ON users FOR EACH ROW EXECUTE FUNCTION audit_changes();
CREATE TRIGGER audit_orders_trigger AFTER INSERT OR UPDATE OR DELETE ON orders FOR EACH ROW EXECUTE FUNCTION audit_changes();
```

**TypeScript to retrieve audit trail:**
```typescript
const getAuditTrail = async (recordId: string) => {
  const { data } = await supabase
    .from('audit_logs')
    .select('*')
    .eq('record_id', recordId)
    .order('changed_at', { ascending: false })

  return data
}

// Usage
const trail = await getAuditTrail(userId)
trail?.forEach(log => {
  console.log(`${log.operation} by ${log.changed_by} at ${log.changed_at}`)
  console.log('Old:', log.old_values)
  console.log('New:', log.new_values)
})
```

---

### Example 5: Prevent Recursive Triggers

**Use case**: Update parent table without infinite recursion

```sql
-- ❌ WRONG - Causes infinite recursion
CREATE OR REPLACE FUNCTION bad_recursive_trigger()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE accounts SET balance = balance - 1 WHERE id = NEW.account_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ✅ CORRECT - Use pg_trigger_depth() to prevent recursion
CREATE OR REPLACE FUNCTION recursive_trigger_safe()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  -- Only execute at first nesting level
  IF pg_trigger_depth() = 1 THEN
    UPDATE accounts SET balance = balance - 1 WHERE id = NEW.account_id;
  END IF;
  RETURN NEW;
END;
$$;

-- Or: Use WHEN clause to prevent re-triggering
CREATE TRIGGER recursive_safe_trigger
AFTER INSERT ON transactions
FOR EACH ROW
WHEN (pg_trigger_depth() < 2)  -- Only fire at top level
EXECUTE FUNCTION recursive_trigger_safe();

-- Or: Use additional WHERE condition
CREATE OR REPLACE FUNCTION recursive_with_guard()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE accounts 
  SET balance = balance - 1,
      last_synced = now()
  WHERE id = NEW.account_id
    AND last_synced < now() - interval '1 second';  -- Guard condition
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Debugging recursive triggers:**
```sql
-- Check current nesting level
SELECT pg_trigger_depth();

-- Monitor trigger calls
CREATE TABLE trigger_calls (
  id serial,
  trigger_name text,
  depth int,
  called_at timestamp DEFAULT now()
);

-- Add to trigger function for debugging
INSERT INTO trigger_calls (trigger_name, depth) 
VALUES (TG_NAME, pg_trigger_depth());
```

---

### Example 6: RPC Function (Callable from TypeScript)

**Use case**: Complex operation exposed via REST API

```sql
-- Function to increment a counter
CREATE OR REPLACE FUNCTION public.increment_counter(counter_id uuid, amount int DEFAULT 1)
RETURNS int
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
DECLARE
  new_value int;
BEGIN
  UPDATE counters 
  SET value = value + amount
  WHERE id = counter_id
  RETURNING value INTO new_value;

  RETURN new_value;
END;
$$;
```

**TypeScript RPC call:**
```typescript
// Use .rpc() to call database function
const { data, error } = await supabase.rpc('increment_counter', {
  counter_id: 'uuid-123',
  amount: 5
})

if (error) {
  console.error('RPC error:', error)
  return
}

console.log('New counter value:', data) // Returns: int
```

**Type-safe RPC with generated types:**
```typescript
// lib/database.types.ts (generated by Supabase CLI)
import { Database } from './database.types'

const rpcWithTypes = async () => {
  const { data, error } = await supabase.rpc<number>('increment_counter', {
    counter_id: 'uuid-123',
    amount: 5
  })

  return data as number
}
```

---

### Example 7: Function Returning Multiple Columns (TABLE)

**Use case**: Return structured data from complex queries

```sql
CREATE OR REPLACE FUNCTION public.get_user_stats(user_id uuid)
RETURNS TABLE (
  total_posts bigint,
  total_comments bigint,
  total_likes bigint,
  avg_engagement_score float
) AS $$
BEGIN
  RETURN QUERY SELECT
    COUNT(p.id) as total_posts,
    COUNT(c.id) as total_comments,
    COUNT(l.id) as total_likes,
    (COUNT(l.id)::float / NULLIF(COUNT(p.id), 0)) as avg_engagement_score
  FROM users u
  LEFT JOIN posts p ON u.id = p.user_id
  LEFT JOIN comments c ON u.id = c.user_id
  LEFT JOIN likes l ON p.id = l.post_id
  WHERE u.id = user_id
  GROUP BY u.id;
END;
$$ LANGUAGE plpgsql;
```

**TypeScript usage:**
```typescript
const { data, error } = await supabase.rpc('get_user_stats', {
  user_id: userId
})

// data = { total_posts: 15, total_comments: 42, total_likes: 128, avg_engagement_score: 8.53 }
```

---

## Project Structure (Gold Standard)

**Migration file organization:**
```
supabase/
├── migrations/
│   ├── 20250120_000000_create_base_tables.sql
│   ├── 20250120_001000_create_users_table.sql
│   ├── 20250120_002000_enable_rls.sql
│   ├── 20250120_003000_add_timestamp_triggers.sql
│   ├── 20250120_004000_create_audit_log_table.sql
│   ├── 20250120_005000_create_audit_triggers.sql
│   ├── 20250120_010000_create_rpc_functions.sql
│   └── README.md
├── functions/
│   ├── README.md (documents all functions)
│   └── triggers.md (documents all triggers)
└── README.md
```

**Migration file template:**
```sql
-- supabase/migrations/20250120_HHMMSS_add_feature.sql
-- Description: Brief explanation of what this migration does
-- Author: [name]
-- Date: 2025-01-20

-- Always wrap in transaction for safety
BEGIN;

-- Always handle idempotency with IF NOT EXISTS
CREATE TABLE IF NOT EXISTS my_table (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamp with time zone DEFAULT now()
);

-- Create function
CREATE OR REPLACE FUNCTION my_function()
RETURNS void AS $$ BEGIN
  -- Implementation
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER my_trigger
BEFORE INSERT ON my_table
FOR EACH ROW
EXECUTE FUNCTION my_function();

COMMIT;
```

**TypeScript client setup:**
```typescript
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js'
import type { Database } from './database.types'

export const supabase = createClient<Database>(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

// Call RPC functions with types
export const rpc = {
  incrementCounter: (counterId: string, amount?: number) =>
    supabase.rpc('increment_counter', { counter_id: counterId, amount }),
  
  getUserStats: (userId: string) =>
    supabase.rpc('get_user_stats', { user_id: userId }),
}
```

---

## Best Practices with Rationale

### 1. Always Use Migrations (Never Direct SQL Editor)

❌ **Wrong**: Using Supabase Dashboard SQL Editor
✅ **Right**: Using `supabase migration` CLI

**Why**: 
- Reproducible deployments
- Version control integration
- Easy rollback
- Team collaboration
- Production safety (no accidental schema changes)

```bash
# Create migration
supabase migration new add_new_function

# Local testing
supabase migration up

# Production deployment
supabase link
supabase db push
```

---

### 2. Classify Functions Correctly for Performance

❌ **Wrong**:
```sql
CREATE FUNCTION get_discount() RETURNS float
LANGUAGE sql VOLATILE  -- ← Recalculated every time
AS $$ SELECT 0.15; $$;
```

✅ **Right**:
```sql
CREATE FUNCTION get_discount() RETURNS float
LANGUAGE sql IMMUTABLE  -- ← Cached by optimizer
AS $$ SELECT 0.15; $$;
```

**Why**: Immutable functions are cached, resulting in 10-86% performance improvement

---

### 3. Use SECURITY DEFINER for RLS Policy Functions

❌ **Wrong**:
```sql
CREATE FUNCTION has_admin_role() RETURNS boolean AS $$
  SELECT EXISTS (SELECT 1 FROM roles WHERE user_id = auth.uid() AND role = 'admin');
$$ LANGUAGE sql SECURITY INVOKER;  -- ← Slow: Applies RLS twice
```

✅ **Right**:
```sql
CREATE FUNCTION has_admin_role() RETURNS boolean AS $$
  SELECT EXISTS (SELECT 1 FROM roles WHERE user_id = auth.uid() AND role = 'admin');
$$ LANGUAGE sql SECURITY DEFINER;  -- ← Bypasses RLS on roles table
```

**Why**: Bypassing RLS on helper tables prevents recursive policy checks

---

### 4. Use BEFORE Triggers for Computations, AFTER for Side Effects

❌ **Wrong**:
```sql
CREATE TRIGGER update_slug
AFTER INSERT ON posts  -- ← Can't modify row anymore
FOR EACH ROW
EXECUTE FUNCTION generate_slug();
```

✅ **Right**:
```sql
CREATE TRIGGER update_slug
BEFORE INSERT ON posts  -- ← Can modify row before insertion
FOR EACH ROW
EXECUTE FUNCTION generate_slug();
```

**Why**: BEFORE can modify the row, AFTER only reads it (operation already done)

---

### 5. Include WHEN Clause for Better Performance

❌ **Wrong**:
```sql
CREATE TRIGGER check_email
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION validate_email();  -- Fires even if email didn't change
```

✅ **Right**:
```sql
CREATE TRIGGER check_email
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW
WHEN (NEW.email IS DISTINCT FROM OLD.email)
EXECUTE FUNCTION validate_email();  -- Only fires if email changed
```

**Why**: WHEN clause prevents unnecessary function calls

---

### 6. Prevent Recursive Triggers Explicitly

❌ **Wrong**: No recursion prevention
```sql
CREATE FUNCTION update_parent() RETURNS trigger AS $$
BEGIN
  UPDATE parent_table SET count = count + 1 WHERE id = NEW.parent_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- ← If parent_table has same trigger, infinite recursion!
```

✅ **Right**: Use pg_trigger_depth()
```sql
CREATE FUNCTION update_parent() RETURNS trigger AS $$
BEGIN
  IF pg_trigger_depth() = 1 THEN
    UPDATE parent_table SET count = count + 1 WHERE id = NEW.parent_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Why**: Prevents stack overflow and database crashes

---

### 7. Escape User Input in Dynamic SQL

❌ **Wrong**: SQL injection vulnerability
```sql
CREATE FUNCTION search_users(search_term text) RETURNS TABLE (id uuid, name text) AS $$
BEGIN
  RETURN QUERY EXECUTE 'SELECT id, name FROM users WHERE name LIKE ''%' || search_term || '%''';
  -- ↑ Vulnerable to SQL injection
END;
$$ LANGUAGE plpgsql;
```

✅ **Right**: Use parameterized queries
```sql
CREATE FUNCTION search_users(search_term text) RETURNS TABLE (id uuid, name text) AS $$
BEGIN
  RETURN QUERY SELECT id, name FROM users WHERE name LIKE '%' || search_term || '%';
  -- ↑ Safe: parameter is properly escaped
END;
$$ LANGUAGE plpgsql;

-- Or with EXECUTE if dynamic SQL required:
CREATE FUNCTION search_column(table_name text, search_term text) RETURNS TABLE (result text) AS $$
BEGIN
  RETURN QUERY EXECUTE format('SELECT name FROM %I WHERE content LIKE %L', table_name, '%' || search_term || '%');
  -- ↑ Safe: %I and %L properly escape identifiers and values
END;
$$ LANGUAGE plpgsql;
```

**Why**: Prevents SQL injection attacks

---

### 8. Keep Triggers Simple, Use FOR EACH ROW

❌ **Wrong**: Complex logic in trigger
```sql
CREATE FUNCTION calculate_revenue() RETURNS trigger AS $$
BEGIN
  -- Complex calculations, multiple table updates, external API calls
  UPDATE orders SET revenue = ...
  UPDATE analytics SET metrics = ...
  PERFORM http_post(...);  -- ← Never call external APIs in triggers!
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

✅ **Right**: Simple trigger, complex logic in app or Edge Function
```sql
-- Trigger: only mark for processing
CREATE FUNCTION mark_for_processing() RETURNS trigger AS $$
BEGIN
  NEW.needs_processing = true;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Edge Function: handle complex logic
-- Use Supabase realtime to trigger processing when needs_processing = true
```

**Why**: Keeps database responsive, external calls should be in Edge Functions

---

### 9. Use RLS with Database Functions

✅ **Pattern**: Combine RLS + functions for defense in depth

```sql
-- Enable RLS on sensitive tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- RLS policy
CREATE POLICY "Users see own data"
ON users FOR SELECT
USING (auth.uid() = id);

-- Function with SECURITY INVOKER respects RLS
CREATE FUNCTION get_current_user() RETURNS users AS $$
  SELECT * FROM users WHERE id = auth.uid();
$$ LANGUAGE sql SECURITY INVOKER;

-- Calling from TypeScript automatically filtered by RLS
const { data } = await supabase.rpc('get_current_user')
```

**Why**: Defense in depth - even if app logic fails, RLS protects data

---

### 10. Document Functions and Triggers

```sql
-- ✅ Good documentation
COMMENT ON FUNCTION public.increment_counter(uuid, int) IS
'Increments a counter by the specified amount.
Arguments:
  - counter_id: UUID of the counter to increment
  - amount: Increment amount (default: 1)
Returns:
  - New counter value after increment
Security: SECURITY INVOKER - respects caller permissions
Performance: STABLE function - can be optimized by planner';

COMMENT ON TRIGGER update_timestamp_trigger ON users IS
'Automatically updates the updated_at column before any UPDATE.
This trigger ensures all row modifications are timestamped.';
```

**Why**: Helps team understand function purpose and behavior

---

## Common Errors & Troubleshooting

### Error 1: "permission denied for schema public"

**Cause**: Function/trigger created without proper grants

```sql
-- ✅ Fix: Grant execute permission
CREATE OR REPLACE FUNCTION public.my_function()
RETURNS void AS $$ BEGIN END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION public.my_function() TO authenticated;
```

---

### Error 2: "infinite recursion detected"

**Cause**: Trigger updates same table, triggers itself repeatedly

```sql
-- ✅ Fix 1: Use BEFORE trigger to modify row instead of updating
CREATE OR REPLACE FUNCTION safe_update() RETURNS trigger AS $$
BEGIN
  NEW.column = computed_value;  -- Modify in BEFORE trigger
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ✅ Fix 2: Use pg_trigger_depth() guard
CREATE OR REPLACE FUNCTION update_with_guard() RETURNS trigger AS $$
BEGIN
  IF pg_trigger_depth() = 1 THEN
    UPDATE same_table SET count = count + 1 WHERE id = NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

### Error 3: "unexpected end of file" in PL/pgSQL

**Cause**: Missing `$$` or `END;` in function definition

```sql
-- ❌ Wrong
CREATE FUNCTION bad() RETURNS void AS $$
BEGIN
  RAISE NOTICE 'missing end';
-- Missing $$

-- ✅ Right
CREATE FUNCTION good() RETURNS void AS $$
BEGIN
  RAISE NOTICE 'complete function';
END;
$$ LANGUAGE plpgsql;
```

---

### Error 4: "NEW is null" in DELETE trigger

**Cause**: Trying to access NEW in DELETE trigger (doesn't exist)

```sql
-- ❌ Wrong
CREATE TRIGGER delete_trigger AFTER DELETE ON users
FOR EACH ROW
EXECUTE FUNCTION bad_delete();  -- Can't access NEW here

CREATE FUNCTION bad_delete() RETURNS trigger AS $$
BEGIN
  INSERT INTO logs (data) VALUES (row_to_json(NEW));  -- ← NEW is null!
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ✅ Right: Use OLD in DELETE triggers
CREATE FUNCTION good_delete() RETURNS trigger AS $$
BEGIN
  INSERT INTO logs (data) VALUES (row_to_json(OLD));  -- ← Use OLD
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;
```

---

### Error 5: "Trigger depth exceeded"

**Cause**: Recursive trigger exceeded 100 nesting levels (database safety limit)

```sql
-- ✅ Check depth in trigger
CREATE FUNCTION safe_recursive() RETURNS trigger AS $$
BEGIN
  RAISE NOTICE 'Current trigger depth: %', pg_trigger_depth();
  
  IF pg_trigger_depth() > 10 THEN
    RAISE EXCEPTION 'Trigger recursion too deep';
  END IF;
  
  -- Safe operations only
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

### Error 6: "Function return type mismatch" in RPC

**Cause**: TypeScript expects different return type than function

```sql
-- Function returns SETOF json
CREATE FUNCTION get_items() RETURNS SETOF json AS $$
  SELECT row_to_json(t) FROM items t;
$$ LANGUAGE sql;
```

```typescript
// ✅ TypeScript type fix
const { data, error } = await supabase
  .rpc('get_items')
  .then(res => ({
    data: (res.data as unknown as Items[]) || [],
    error: res.error
  }))

// Or generate types with Supabase CLI
supabase gen types typescript --linked > database.types.ts
```

---

### Error 7: "Trigger not firing" - Debugging Checklist

```sql
-- ✅ Step 1: Verify trigger exists and is enabled
SELECT tgname, tgenabled FROM pg_trigger WHERE tgname = 'my_trigger';
-- tgenabled should be 'O' (origin) or 'A' (always)

-- ✅ Step 2: Verify function exists
SELECT proname FROM pg_proc WHERE proname = 'my_trigger_function';

-- ✅ Step 3: Add debug logging
CREATE OR REPLACE FUNCTION debug_trigger() RETURNS trigger AS $$
BEGIN
  RAISE NOTICE 'Trigger fired: %, Operation: %, Table: %', TG_NAME, TG_OP, TG_TABLE_NAME;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ✅ Step 4: Check for WHEN clause preventing execution
-- Run the WHEN condition independently
SELECT id, NEW_email FROM users WHERE NEW.email IS DISTINCT FROM OLD.email;

-- ✅ Step 5: Test directly
INSERT INTO my_table (column) VALUES ('test');
-- Check PostgreSQL logs or use psql: SELECT * FROM pg_stat_user_tables;

-- ✅ Step 6: Re-create trigger if needed
DROP TRIGGER IF EXISTS my_trigger ON my_table;
CREATE TRIGGER my_trigger BEFORE INSERT ON my_table FOR EACH ROW EXECUTE FUNCTION my_trigger_function();
```

---

### Debugging with RAISE Statements

```sql
CREATE OR REPLACE FUNCTION debug_function(user_id uuid)
RETURNS void AS $$
DECLARE
  user_record record;
  debug_msg text;
BEGIN
  -- RAISE NOTICE: Always logged (use in development)
  RAISE NOTICE 'Starting debug for user: %', user_id;

  SELECT * INTO user_record FROM users WHERE id = user_id;
  
  -- RAISE WARNING: Logged to server logs
  IF user_record IS NULL THEN
    RAISE WARNING 'User % not found', user_id;
  END IF;

  -- RAISE EXCEPTION: Stops execution and rolls back transaction
  IF user_record.is_active = false THEN
    RAISE EXCEPTION 'User % is inactive', user_id;
  END IF;

  RAISE NOTICE 'User details: %', row_to_json(user_record);
END;
$$ LANGUAGE plpgsql;
```

---

## Database Functions vs Edge Functions Decision Matrix

| Factor | Database Functions | Edge Functions |
|--------|---|---|
| **Latency** | ~1-5ms (same server) | 50-200ms (geographic distance) |
| **Language** | PL/pgSQL, SQL | TypeScript/JavaScript |
| **Complexity** | Good (queries, logic) | Better (external APIs, transforms) |
| **External APIs** | ❌ Not recommended | ✅ Recommended |
| **RLS Support** | ✅ Native | ❌ Manual |
| **Concurrency** | ✅ High | ⚠️ Cold starts |
| **File uploads** | ⚠️ Limited | ✅ Recommended |
| **Long-running** | ❌ Timeout risk | ✅ Better (up to 60s) |

**Decision rule**:
- **DB Functions**: Data operations, RLS policies, triggers, real-time queries
- **Edge Functions**: External API calls, file operations, complex transformations, scheduling

---

## TypeScript Integration Patterns

### Pattern 1: Type-Safe RPC Calls

```typescript
// types/database.ts
export interface Database {
  public: {
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
          total_likes: number
          avg_engagement_score: number
        }[]
      }
    }
  }
}

// Usage
import { createClient } from '@supabase/supabase-js'
import type { Database } from './types/database'

const supabase = createClient<Database>(url, key)

// Fully typed
const { data, error } = await supabase.rpc('increment_counter', {
  counter_id: 'uuid-123',
  amount: 5, // ✅ Type-checked
})
// data is number | null
```

### Pattern 2: Error Handling Wrapper

```typescript
export async function callRpc<T>(
  fn: string,
  args: Record<string, any> = {}
): Promise<[T | null, Error | null]> {
  try {
    const { data, error } = await supabase.rpc(fn, args)
    
    if (error) {
      console.error(`RPC error in ${fn}:`, error.message)
      return [null, error]
    }
    
    return [data as T, null]
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e))
    console.error(`Unexpected error in ${fn}:`, err)
    return [null, err]
  }
}

// Usage
const [newValue, error] = await callRpc<number>('increment_counter', {
  counter_id: 'uuid-123'
})

if (error) {
  toast.error('Failed to increment counter')
  return
}

console.log('New value:', newValue)
```

### Pattern 3: React Hook for RPC Functions

```typescript
// hooks/useRpc.ts
import { useState, useCallback } from 'react'
import { supabase } from '@/lib/supabase'

export function useRpc<T>(functionName: string) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const call = useCallback(
    async (args?: Record<string, any>) => {
      setLoading(true)
      setError(null)

      try {
        const { data: result, error: err } = await supabase.rpc(
          functionName,
          args
        )

        if (err) throw err
        setData(result as T)
        return result
      } catch (e) {
        const error = e instanceof Error ? e : new Error(String(e))
        setError(error)
        throw error
      } finally {
        setLoading(false)
      }
    },
    [functionName]
  )

  return { data, loading, error, call }
}

// Usage in component
export function MyComponent() {
  const { data: stats, loading, error, call } = useRpc('get_user_stats')

  useEffect(() => {
    call({ user_id: userId })
  }, [userId, call])

  if (loading) return <div>Loading...</div>
  if (error) return <div>Error: {error.message}</div>

  return <div>{stats?.total_posts} posts</div>
}
```

---

## Official Documentation Links

### PostgreSQL
- **PL/pgSQL Trigger Functions**: https://www.postgresql.org/docs/current/plpgsql-trigger.html
- **CREATE TRIGGER Syntax**: https://www.postgresql.org/docs/current/sql-createtrigger.html
- **PL/pgSQL Documentation**: https://www.postgresql.org/docs/current/plpgsql.html
- **PostgreSQL Function Documentation**: https://www.postgresql.org/docs/current/sql-createfunction.html

### Supabase
- **Database Functions**: https://supabase.com/docs/guides/database/functions
- **Row Level Security**: https://supabase.com/docs/guides/database/postgres/row-level-security
- **Database Migrations**: https://supabase.com/docs/guides/deployment/database-migrations
- **Supabase CLI**: https://supabase.com/docs/reference/cli/introduction
- **RPC Calling**: https://supabase.com/docs/reference/javascript/rpc
- **RLS Performance & Best Practices**: https://supabase.com/docs/guides/troubleshooting/rls-performance-and-best-practices-Z5Jjwv

### Learning Resources
- **PostgreSQL Volatility Classification**: https://aws.amazon.com/blogs/database/volatility-classification-in-postgresql/
- **Preventing Recursive Triggers**: https://www.cybertec-postgresql.com/en/dealing-with-trigger-recursion-in-postgresql/
- **Trigger Implementation Guide**: https://chat2db.ai/resources/blog/how-to-implement-postgresql-triggers

---

## Migration Checklist

Before deploying to production:

- [ ] Migration file follows naming convention: `YYYYMMdd_HHMMSS_description.sql`
- [ ] All SQL is wrapped in `BEGIN; ... COMMIT;`
- [ ] Used `CREATE OR REPLACE` and `IF NOT EXISTS` for idempotency
- [ ] Functions classified with correct volatility (IMMUTABLE/STABLE/VOLATILE)
- [ ] Triggers use `WHEN` clauses where applicable
- [ ] Recursive triggers have `pg_trigger_depth()` guards
- [ ] All functions include documentation comments
- [ ] RLS policies created for sensitive tables
- [ ] Tested locally with `supabase migration up`
- [ ] Tested rollback with `supabase db reset`
- [ ] No hardcoded secrets or sensitive data in migration
- [ ] Performance tested with `EXPLAIN ANALYZE`
- [ ] Backup created before production deployment

---

## Quick Troubleshooting Reference

| Issue | Command to Debug |
|-------|---|
| Trigger not firing | `SELECT * FROM pg_trigger WHERE tgname = 'name'; SELECT * FROM pg_stat_user_tables;` |
| Function permission denied | `SELECT has_function_privilege(current_user, 'function_name'::regprocedure, 'EXECUTE');` |
| Recursive trigger | `SELECT pg_trigger_depth();` (run during trigger execution) |
| Wrong function being called | `SELECT routine_name FROM information_schema.routines WHERE routine_name = 'name';` |
| Function not updated | `DROP FUNCTION IF EXISTS function_name(); CREATE FUNCTION ...;` |
| RLS not working | `ALTER TABLE table_name ENABLE ROW LEVEL SECURITY;` |

---

**Last Updated**: January 2025  
**PostgreSQL Version**: 15+  
**Supabase**: Latest (January 2026)
