# PostgreSQL Functions & Triggers - Advanced Patterns & Performance Tuning

## Advanced Trigger Patterns

### Dynamic Trigger Registration Pattern

Create triggers that adapt based on configuration:

```sql
-- Configuration table
CREATE TABLE trigger_config (
  id serial PRIMARY KEY,
  table_name text NOT NULL,
  trigger_type text NOT NULL, -- 'audit', 'timestamp', 'validation'
  enabled boolean DEFAULT true,
  created_at timestamp DEFAULT now()
);

-- Generic trigger function that reads config
CREATE OR REPLACE FUNCTION execute_trigger_action()
RETURNS TRIGGER AS $$
DECLARE
  trigger_actions trigger_config%ROWTYPE;
BEGIN
  SELECT * INTO trigger_actions 
  FROM trigger_config 
  WHERE table_name = TG_TABLE_NAME AND enabled = true;

  IF trigger_actions IS NULL THEN
    RETURN NEW;
  END IF;

  IF trigger_actions.trigger_type = 'timestamp' THEN
    NEW.updated_at = now();
  ELSIF trigger_actions.trigger_type = 'audit' THEN
    INSERT INTO audit_logs (table_name, operation, old_data, new_data)
    VALUES (TG_TABLE_NAME, TG_OP, row_to_json(OLD), row_to_json(NEW));
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Benefits**:
- Single trigger function handles multiple tables
- Enable/disable triggers without code changes
- Easy to audit trigger behavior

---

### Conditional Trigger Execution with WHEN Clause

Optimize trigger execution with intelligent conditions:

```sql
-- Only audit when sensitive fields change
CREATE TRIGGER audit_sensitive_fields
AFTER UPDATE ON users
FOR EACH ROW
WHEN (
  OLD.email IS DISTINCT FROM NEW.email OR
  OLD.phone IS DISTINCT FROM NEW.phone OR
  OLD.payment_method IS DISTINCT FROM NEW.payment_method
)
EXECUTE FUNCTION audit_changes();

-- Only validate non-null emails
CREATE TRIGGER validate_email_format
BEFORE INSERT OR UPDATE ON users
FOR EACH ROW
WHEN (NEW.email IS NOT NULL)
EXECUTE FUNCTION validate_email();

-- Only update timestamp if not already recent
CREATE TRIGGER update_timestamp_selective
BEFORE UPDATE ON posts
FOR EACH ROW
WHEN (NEW.updated_at IS NULL OR (now() - NEW.updated_at > interval '1 second'))
EXECUTE FUNCTION update_timestamp();
```

**Performance impact**: WHEN clauses reduce function calls by 50-80%

---

### Composite Trigger Pattern (Multiple Operations)

Handle INSERT, UPDATE, DELETE in one function efficiently:

```sql
CREATE OR REPLACE FUNCTION handle_lifecycle_events()
RETURNS TRIGGER AS $$
DECLARE
  lifecycle_type text;
  lifecycle_data jsonb;
BEGIN
  -- Determine event type and data
  CASE TG_OP
    WHEN 'INSERT' THEN
      lifecycle_type := 'created';
      lifecycle_data := row_to_json(NEW);
    WHEN 'UPDATE' THEN
      -- Only track if meaningful changes
      IF row_to_json(NEW) = row_to_json(OLD) THEN
        RETURN NEW;
      END IF;
      lifecycle_type := 'updated';
      lifecycle_data := jsonb_build_object(
        'before', row_to_json(OLD),
        'after', row_to_json(NEW),
        'fields_changed', (
          SELECT array_agg(key) FROM jsonb_each(row_to_json(NEW))
          WHERE row_to_json(NEW) -> key != row_to_json(OLD) -> key
        )
      );
    WHEN 'DELETE' THEN
      lifecycle_type := 'deleted';
      lifecycle_data := row_to_json(OLD);
  END CASE;

  -- Log event
  INSERT INTO lifecycle_events (table_name, event_type, event_data, created_at)
  VALUES (TG_TABLE_NAME, lifecycle_type, lifecycle_data, now());

  -- Return appropriate record
  CASE TG_OP
    WHEN 'INSERT', 'UPDATE' THEN RETURN NEW;
    WHEN 'DELETE' THEN RETURN OLD;
  END CASE;
END;
$$ LANGUAGE plpgsql;
```

---

## Performance Optimization Techniques

### Function Inlining

Force the optimizer to inline simple functions:

```sql
-- ✅ Good: Inlining eligible function
CREATE OR REPLACE FUNCTION get_user_status(user_id uuid)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT status FROM users WHERE id = user_id;
$$;

-- Query optimizer inlines this into the caller's query
SELECT id, get_user_status(id) FROM users LIMIT 10;
-- Equivalent to: SELECT id, (SELECT status FROM users WHERE id = users.id)

-- ❌ Bad: Complex function won't inline
CREATE OR REPLACE FUNCTION get_user_status_complex(user_id uuid)
RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  status text;
BEGIN
  SELECT u.status INTO status
  FROM users u
  WHERE u.id = user_id;
  RETURN status;
END;
$$;
```

**Inlining rules**:
- SQL functions usually inline
- PL/pgSQL functions with logic don't inline
- SECURITY DEFINER prevents inlining (safety boundary)

---

### Materialized Computation

Pre-compute expensive values:

```sql
-- Store expensive calculation
CREATE TABLE user_metrics (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  total_posts int DEFAULT 0,
  total_comments int DEFAULT 0,
  total_engagement int DEFAULT 0,
  last_updated timestamp DEFAULT now()
);

-- Trigger to update metrics on INSERT
CREATE OR REPLACE FUNCTION update_user_metrics()
RETURNS TRIGGER AS $$
BEGIN
  -- Increment counter instead of recalculating
  CASE TG_TABLE_NAME
    WHEN 'posts' THEN
      UPDATE user_metrics 
      SET total_posts = total_posts + (CASE WHEN TG_OP = 'DELETE' THEN -1 ELSE 1 END),
          last_updated = now()
      WHERE user_id = COALESCE(NEW.user_id, OLD.user_id);
    WHEN 'comments' THEN
      UPDATE user_metrics 
      SET total_comments = total_comments + (CASE WHEN TG_OP = 'DELETE' THEN -1 ELSE 1 END),
          last_updated = now()
      WHERE user_id = COALESCE(NEW.user_id, OLD.user_id);
  END CASE;
  
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Instead of: SELECT count(*) FROM posts WHERE user_id = $1 (expensive!)
-- Use: SELECT total_posts FROM user_metrics WHERE user_id = $1 (fast!)
```

**Performance gain**: O(1) vs O(n) lookup

---

### Batch Processing Pattern

Handle bulk operations efficiently:

```sql
-- Trigger for batch inserts
CREATE OR REPLACE FUNCTION batch_insert_handler()
RETURNS TRIGGER AS $$
DECLARE
  batch_id uuid;
BEGIN
  -- Only process at top transaction level
  IF pg_trigger_depth() = 1 THEN
    -- Get or create batch
    batch_id := NEW.batch_id;
    
    -- Update batch status in background
    -- Mark batch as processing
    UPDATE import_batches 
    SET status = 'processing', updated_at = now()
    WHERE id = batch_id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- For bulk updates, defer non-critical processing
CREATE OR REPLACE FUNCTION defer_notifications()
RETURNS TRIGGER AS $$
BEGIN
  -- Queue notification instead of sending immediately
  INSERT INTO notification_queue (user_id, event_type, data)
  VALUES (NEW.user_id, 'post_created', row_to_json(NEW))
  ON CONFLICT (user_id, event_type) DO UPDATE 
  SET data = EXCLUDED.data, queued_at = now();

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Security Hardening

### SQL Injection Prevention in Dynamic SQL

```sql
-- ❌ VULNERABLE
CREATE OR REPLACE FUNCTION bad_search(table_name text, search_term text)
RETURNS TABLE (result jsonb) AS $$
BEGIN
  RETURN QUERY EXECUTE 'SELECT row_to_json(t) FROM ' || table_name || 
    ' t WHERE t.name LIKE ' || quote_literal('%' || search_term || '%');
END;
$$ LANGUAGE plpgsql;

-- ✅ SAFE: Use format with %I (identifier) and %L (literal)
CREATE OR REPLACE FUNCTION safe_search(table_name text, search_term text)
RETURNS TABLE (result jsonb) AS $$
BEGIN
  RETURN QUERY EXECUTE format(
    'SELECT row_to_json(t) FROM %I t WHERE t.name LIKE %L',
    table_name,
    '%' || search_term || '%'
  );
END;
$$ LANGUAGE plpgsql;

-- ✅ SAFE: Use quote_ident and quote_literal
CREATE OR REPLACE FUNCTION safe_search_alt(table_name text, col_name text, search_term text)
RETURNS TABLE (result jsonb) AS $$
BEGIN
  RETURN QUERY EXECUTE format(
    'SELECT row_to_json(t) FROM %I t WHERE %I LIKE %L',
    table_name,
    col_name,
    '%' || search_term || '%'
  );
END;
$$ LANGUAGE plpgsql;
```

**Key functions**:
- `format()` with `%I` = identifier (safe from injection)
- `%L` = literal value (SQL-escaped)
- `%s` = string (NOT safe, avoid!)

---

### Input Validation Patterns

```sql
-- Validate before processing
CREATE OR REPLACE FUNCTION create_user_with_validation(
  p_email text,
  p_age int,
  p_country_code text
)
RETURNS uuid AS $$
DECLARE
  user_id uuid;
BEGIN
  -- Validate email format
  IF NOT p_email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$' THEN
    RAISE EXCEPTION 'Invalid email format: %', p_email;
  END IF;

  -- Validate age range
  IF p_age < 13 OR p_age > 150 THEN
    RAISE EXCEPTION 'Age must be between 13 and 150, got %', p_age;
  END IF;

  -- Validate country code
  IF NOT EXISTS (SELECT 1 FROM countries WHERE code = p_country_code) THEN
    RAISE EXCEPTION 'Invalid country code: %', p_country_code;
  END IF;

  -- All validations passed
  INSERT INTO users (email, age, country_code)
  VALUES (p_email, p_age, p_country_code)
  RETURNING id INTO user_id;

  RETURN user_id;
END;
$$ LANGUAGE plpgsql;
```

---

### Encryption at Rest in Triggers

```sql
-- Automatically encrypt sensitive fields
CREATE OR REPLACE FUNCTION encrypt_sensitive_data()
RETURNS TRIGGER AS $$
BEGIN
  -- Encrypt SSN using pgcrypto
  IF NEW.ssn IS NOT NULL THEN
    NEW.ssn_encrypted := crypt(NEW.ssn, gen_salt('bf', 8));
    NEW.ssn := NULL;  -- Don't store plaintext
  END IF;

  -- Hash password
  IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.password IS DISTINCT FROM OLD.password) THEN
    IF NEW.password IS NOT NULL THEN
      NEW.password_hash := crypt(NEW.password, gen_salt('bf', 12));
      NEW.password := NULL;
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Verify encrypted data
CREATE OR REPLACE FUNCTION verify_password(p_user_id uuid, p_password text)
RETURNS boolean AS $$
DECLARE
  v_hash text;
BEGIN
  SELECT password_hash INTO v_hash FROM users WHERE id = p_user_id;
  RETURN v_hash = crypt(p_password, v_hash);
END;
$$ LANGUAGE plpgsql;
```

---

## Debugging & Monitoring

### Trigger Execution Logging

```sql
-- Create comprehensive trigger log
CREATE TABLE trigger_execution_log (
  id bigserial PRIMARY KEY,
  trigger_name text NOT NULL,
  table_name text NOT NULL,
  operation text NOT NULL,
  execution_time_ms numeric,
  trigger_depth int,
  error_occurred boolean DEFAULT false,
  error_message text,
  executed_at timestamp with time zone DEFAULT now()
);

-- Wrapper function for all triggers
CREATE OR REPLACE FUNCTION log_trigger_execution(
  p_trigger_name text,
  p_table_name text,
  p_operation text,
  p_execution_time_ms numeric DEFAULT 0,
  p_error_message text DEFAULT NULL
) RETURNS void AS $$
BEGIN
  INSERT INTO trigger_execution_log (
    trigger_name, table_name, operation, execution_time_ms, 
    trigger_depth, error_occurred, error_message
  ) VALUES (
    p_trigger_name, p_table_name, p_operation, p_execution_time_ms,
    pg_trigger_depth(), p_error_message IS NOT NULL, p_error_message
  );
END;
$$ LANGUAGE plpgsql;

-- Use in triggers
CREATE OR REPLACE FUNCTION monitored_trigger()
RETURNS TRIGGER AS $$
DECLARE
  v_start_time timestamp;
  v_error text;
BEGIN
  v_start_time := clock_timestamp();

  BEGIN
    -- Actual trigger logic
    NEW.updated_at = now();
    RETURN NEW;
  EXCEPTION WHEN OTHERS THEN
    v_error := SQLERRM;
    PERFORM log_trigger_execution(
      'monitored_trigger',
      TG_TABLE_NAME,
      TG_OP,
      EXTRACT(EPOCH FROM (clock_timestamp() - v_start_time)) * 1000,
      v_error
    );
    RAISE;
  END;

  PERFORM log_trigger_execution(
    'monitored_trigger',
    TG_TABLE_NAME,
    TG_OP,
    EXTRACT(EPOCH FROM (clock_timestamp() - v_start_time)) * 1000
  );

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

### Performance Profiling

```sql
-- Analyze trigger performance
CREATE OR REPLACE FUNCTION analyze_trigger_performance()
RETURNS TABLE (
  trigger_name text,
  avg_duration_ms numeric,
  max_duration_ms numeric,
  min_duration_ms numeric,
  total_executions bigint,
  error_count bigint
) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    tel.trigger_name,
    AVG(tel.execution_time_ms)::numeric,
    MAX(tel.execution_time_ms)::numeric,
    MIN(tel.execution_time_ms)::numeric,
    COUNT(*)::bigint,
    COUNT(*) FILTER (WHERE tel.error_occurred = true)::bigint
  FROM trigger_execution_log tel
  WHERE tel.executed_at > now() - interval '24 hours'
  GROUP BY tel.trigger_name
  ORDER BY AVG(tel.execution_time_ms) DESC;
END;
$$ LANGUAGE plpgsql;

-- Usage
SELECT * FROM analyze_trigger_performance();
-- Shows: slow triggers, error rates, execution frequency
```

---

## Error Handling Best Practices

### Graceful Degradation

```sql
-- Fail safe: log error but don't block operation
CREATE OR REPLACE FUNCTION resilient_trigger()
RETURNS TRIGGER AS $$
BEGIN
  BEGIN
    -- Try to update analytics
    UPDATE analytics SET counter = counter + 1 
    WHERE category = NEW.category;
  EXCEPTION WHEN OTHERS THEN
    -- Log but don't fail the main operation
    INSERT INTO error_log (error_msg, source) 
    VALUES (SQLERRM, 'resilient_trigger');
    -- Continue anyway
  END;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

### Contextual Error Messages

```sql
-- Provide helpful error context
CREATE OR REPLACE FUNCTION validate_order_with_context()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.quantity <= 0 THEN
    RAISE EXCEPTION 'Invalid order quantity: %. Order ID: %. User: %',
      NEW.quantity, NEW.id, NEW.user_id
      USING HINT = 'Quantity must be greater than 0',
            DETAIL = 'Check inventory system for valid quantities',
            ERRCODE = 'invalid_parameter_value';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Migration Patterns for Functions & Triggers

### Zero-Downtime Function Updates

```sql
-- Step 1: Create new function with v2 suffix
CREATE OR REPLACE FUNCTION process_order_v2(order_id uuid)
RETURNS json AS $$
  -- New implementation
$$ LANGUAGE plpgsql;

-- Step 2: Redirect old function to new one
CREATE OR REPLACE FUNCTION process_order(order_id uuid)
RETURNS json AS $$
BEGIN
  RETURN process_order_v2(order_id);
END;
$$ LANGUAGE plpgsql;

-- Step 3: After verification, rename
-- DROP FUNCTION process_order(uuid) CASCADE;
-- CREATE OR REPLACE FUNCTION process_order AS SELECT * FROM process_order_v2
-- DROP FUNCTION process_order_v2(uuid)
```

---

### Trigger Rollout Strategy

```sql
-- 1. Create new trigger with _new suffix
CREATE TRIGGER users_audit_new
AFTER INSERT OR UPDATE OR DELETE ON users
FOR EACH ROW
EXECUTE FUNCTION audit_changes_v2();

-- 2. Dual-write to validate new trigger
-- Application reads from old trigger, verifies new trigger output

-- 3. Switch triggers
-- DISABLE TRIGGER users_audit ON users;
-- ENABLE TRIGGER users_audit_new ON users;

-- 4. Clean up
-- DROP TRIGGER users_audit_new ON users;
-- RENAME TRIGGER users_audit_new TO users_audit;
```

---

**Last Updated**: January 2025
**Scope**: Advanced patterns, performance, security, debugging
