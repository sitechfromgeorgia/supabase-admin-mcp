# PostgreSQL Functions & Triggers - Supabase RLS & Integration

## Row Level Security (RLS) with Database Functions

### Pattern 1: RLS-Aware Functions

```sql
-- Helper function to check if user is admin
CREATE OR REPLACE FUNCTION public.is_admin(user_id uuid DEFAULT auth.uid())
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
STABLE
PARALLEL SAFE
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.users
    WHERE id = $1 AND status = 'admin'
  );
$$;

-- Helper function to check user ownership
CREATE OR REPLACE FUNCTION public.user_owns_post(post_id uuid, user_id uuid DEFAULT auth.uid())
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
STABLE
PARALLEL SAFE
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.posts
    WHERE id = $1 AND user_id = $2
  );
$$;

-- Use in RLS policies
CREATE POLICY "Users can view their own posts"
ON public.posts FOR SELECT
USING (user_id = auth.uid());

CREATE POLICY "Users can update their own posts"
ON public.posts FOR UPDATE
USING (user_id = auth.uid())
WITH CHECK (user_id = auth.uid());

CREATE POLICY "Admins can view all posts"
ON public.posts FOR SELECT
USING (public.is_admin(auth.uid()));
```

---

### Pattern 2: Multi-Tenant RLS

```sql
-- Organization table
CREATE TABLE IF NOT EXISTS public.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  owner_id uuid NOT NULL REFERENCES public.auth.users(id),
  created_at timestamp with time zone DEFAULT now()
);

-- Organization members
CREATE TABLE IF NOT EXISTS public.org_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES public.auth.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
  created_at timestamp with time zone DEFAULT now(),
  UNIQUE(org_id, user_id)
);

-- Projects belong to organizations
CREATE TABLE IF NOT EXISTS public.projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  description text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Helper: Get user's organizations
CREATE OR REPLACE FUNCTION public.get_user_orgs(user_id uuid DEFAULT auth.uid())
RETURNS TABLE (org_id uuid, role text)
LANGUAGE sql
SECURITY INVOKER
STABLE
AS $$
  SELECT org_id, role FROM public.org_members
  WHERE user_id = $1;
$$;

-- Helper: Check org membership
CREATE OR REPLACE FUNCTION public.user_in_org(org_id uuid, user_id uuid DEFAULT auth.uid())
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
STABLE
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.org_members
    WHERE org_id = $1 AND user_id = $2
  );
$$;

-- RLS: Users can only view organizations they're part of
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users view own organizations"
ON public.organizations FOR SELECT
USING (
  owner_id = auth.uid() OR
  public.user_in_org(id, auth.uid())
);

-- RLS: Projects visible only to org members
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Org members can view projects"
ON public.projects FOR SELECT
USING (public.user_in_org(org_id, auth.uid()));

CREATE POLICY "Org admins can edit projects"
ON public.projects FOR UPDATE
USING (
  EXISTS (
    SELECT 1 FROM public.org_members
    WHERE org_id = projects.org_id
      AND user_id = auth.uid()
      AND role IN ('owner', 'admin')
  )
);
```

---

### Pattern 3: Time-Based Access Control

```sql
-- Function: Check if user has access based on time
CREATE OR REPLACE FUNCTION public.has_time_based_access(
  resource_id uuid,
  access_type text DEFAULT 'read'
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
STABLE
AS $$
DECLARE
  v_start_time timestamp with time zone;
  v_end_time timestamp with time zone;
BEGIN
  -- Get access window for this resource
  SELECT start_time, end_time INTO v_start_time, v_end_time
  FROM public.access_windows
  WHERE resource_id = $1
    AND access_type = $2
    AND enabled = true;

  IF v_start_time IS NULL THEN
    RETURN true; -- No time restrictions
  END IF;

  -- Check if current time is within access window
  RETURN now() BETWEEN v_start_time AND v_end_time;
END;
$$;

-- Table: Access windows
CREATE TABLE IF NOT EXISTS public.access_windows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resource_id uuid NOT NULL,
  resource_type text NOT NULL, -- 'document', 'video', 'api'
  access_type text NOT NULL,
  start_time timestamp with time zone NOT NULL,
  end_time timestamp with time zone NOT NULL,
  enabled boolean DEFAULT true,
  created_at timestamp with time zone DEFAULT now()
);

-- Use in policies
CREATE POLICY "Time-based document access"
ON public.documents FOR SELECT
USING (
  user_id = auth.uid() OR
  public.has_time_based_access(id, 'read')
);
```

---

## Supabase-Specific Patterns

### Pattern 1: Using auth.jwt()

```sql
-- Function: Extract custom claims from JWT
CREATE OR REPLACE FUNCTION public.get_user_role()
RETURNS text
LANGUAGE sql
SECURITY INVOKER
STABLE
PARALLEL SAFE
AS $$
  SELECT auth.jwt() -> 'user_metadata' ->> 'role';
$$;

-- Function: Check custom claim
CREATE OR REPLACE FUNCTION public.user_has_claim(claim_name text, claim_value text DEFAULT NULL)
RETURNS boolean
LANGUAGE sql
SECURITY INVOKER
STABLE
PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN $2 IS NULL THEN
      (auth.jwt() -> 'user_metadata' -> $1) IS NOT NULL
    ELSE
      auth.jwt() -> 'user_metadata' ->> $1 = $2
  END;
$$;

-- Use in policies
CREATE POLICY "Premium users only"
ON public.premium_features FOR SELECT
USING (
  public.user_has_claim('tier', 'premium') OR
  public.is_admin()
);
```

---

### Pattern 2: Using auth.uid() and auth.email()

```sql
-- Trigger: Auto-populate user profile from auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
  v_email text;
BEGIN
  v_email := NEW.email;
  
  -- Create user profile
  INSERT INTO public.users (id, email, name, created_at)
  VALUES (
    NEW.id,
    v_email,
    NEW.raw_user_meta_data ->> 'full_name',
    now()
  )
  ON CONFLICT (id) DO NOTHING;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger: Fire when new user signs up
CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.handle_new_user();
```

---

### Pattern 3: Supabase Auth with Profiles

```sql
-- Complete user setup
CREATE TABLE IF NOT EXISTS public.profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  username text UNIQUE,
  full_name text,
  avatar_url text,
  bio text,
  website text,
  updated_at timestamp with time zone DEFAULT now()
);

-- Function: Get profile with auth email
CREATE OR REPLACE FUNCTION public.get_profile(user_id uuid DEFAULT auth.uid())
RETURNS TABLE (
  id uuid,
  email text,
  username text,
  full_name text,
  avatar_url text,
  bio text,
  website text
)
LANGUAGE sql
SECURITY INVOKER
STABLE
AS $$
  SELECT
    u.id,
    u.email,
    p.username,
    p.full_name,
    p.avatar_url,
    p.bio,
    p.website
  FROM public.profiles p
  JOIN auth.users u ON p.id = u.id
  WHERE p.id = $1;
$$;

-- Enable RLS on profiles
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public profiles are viewable by everyone"
ON public.profiles FOR SELECT
USING (true);

CREATE POLICY "Users can update own profile"
ON public.profiles FOR UPDATE
USING (auth.uid() = id)
WITH CHECK (auth.uid() = id);
```

---

## Realtime with Triggers

### Pattern 1: Realtime Notifications

```sql
-- Notifications table
CREATE TABLE IF NOT EXISTS public.notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  type text NOT NULL, -- 'comment', 'like', 'follow'
  related_user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
  related_post_id uuid REFERENCES public.posts(id) ON DELETE CASCADE,
  read boolean DEFAULT false,
  created_at timestamp with time zone DEFAULT now()
);

-- Index for efficient queries
CREATE INDEX idx_notifications_user_read ON public.notifications(user_id, read);

-- Trigger: Create notification when someone comments
CREATE OR REPLACE FUNCTION public.notify_on_comment()
RETURNS TRIGGER AS $$
BEGIN
  -- Get post owner
  INSERT INTO public.notifications (user_id, type, related_user_id, related_post_id)
  SELECT
    p.user_id,
    'comment',
    NEW.user_id,
    NEW.post_id
  FROM public.posts p
  WHERE p.id = NEW.post_id AND p.user_id != NEW.user_id;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER on_new_comment
AFTER INSERT ON public.comments
FOR EACH ROW
EXECUTE FUNCTION public.notify_on_comment();

-- Enable realtime
ALTER TABLE public.notifications REPLICA IDENTITY FULL;
```

---

### Pattern 2: Real-Time Status Updates

```sql
-- User activity table
CREATE TABLE IF NOT EXISTS public.user_activity (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
  status text DEFAULT 'offline' CHECK (status IN ('online', 'idle', 'offline')),
  last_seen timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Function: Update user activity
CREATE OR REPLACE FUNCTION public.update_user_activity(
  p_status text DEFAULT 'online'
)
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result json;
BEGIN
  INSERT INTO public.user_activity (user_id, status, last_seen, updated_at)
  VALUES (auth.uid(), p_status, now(), now())
  ON CONFLICT (user_id) DO UPDATE
  SET status = $1, last_seen = now(), updated_at = now()
  RETURNING row_to_json(user_activity.*) INTO v_result;

  RETURN v_result;
END;
$$;

-- Enable realtime for activity
ALTER TABLE public.user_activity REPLICA IDENTITY FULL;
```

---

## Error Handling & Logging

### Pattern 1: Structured Error Responses

```sql
-- Error log table
CREATE TABLE IF NOT EXISTS public.error_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  error_code text NOT NULL,
  error_message text NOT NULL,
  function_name text,
  context jsonb,
  user_id uuid REFERENCES public.users(id) ON DELETE SET NULL,
  created_at timestamp with time zone DEFAULT now()
);

-- Function: Log error
CREATE OR REPLACE FUNCTION public.log_error(
  p_code text,
  p_message text,
  p_function_name text DEFAULT NULL,
  p_context jsonb DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_error_id uuid;
BEGIN
  INSERT INTO public.error_logs (
    error_code, error_message, function_name, context, user_id, created_at
  ) VALUES (
    p_code, p_message, p_function_name, p_context, 
    auth.uid(), now()
  )
  RETURNING id INTO v_error_id;

  RETURN v_error_id;
END;
$$;

-- Function: Safe wrapper for RPC calls
CREATE OR REPLACE FUNCTION public.safe_operation(
  p_operation_name text,
  p_payload jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result jsonb;
BEGIN
  -- Perform operation
  CASE p_operation_name
    WHEN 'create_post' THEN
      v_result := jsonb_build_object(
        'success', true,
        'data', (
          INSERT INTO public.posts (
            user_id, title, content
          ) VALUES (
            auth.uid(),
            p_payload ->> 'title',
            p_payload ->> 'content'
          )
          RETURNING row_to_json(posts.*)
        )[1]
      );
    ELSE
      RAISE EXCEPTION 'Unknown operation: %', p_operation_name;
  END CASE;

  RETURN v_result;

EXCEPTION WHEN OTHERS THEN
  PERFORM public.log_error(
    'OPERATION_ERROR',
    SQLERRM,
    p_operation_name,
    p_payload
  );

  RETURN jsonb_build_object(
    'success', false,
    'error', SQLERRM
  );
END;
$$;
```

---

## Rate Limiting with Triggers

```sql
-- Rate limit table
CREATE TABLE IF NOT EXISTS public.rate_limits (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  operation text NOT NULL, -- 'create_post', 'create_comment'
  window_start timestamp with time zone DEFAULT now(),
  request_count int DEFAULT 1
);

-- Function: Check rate limit
CREATE OR REPLACE FUNCTION public.check_rate_limit(
  p_operation text,
  p_limit int DEFAULT 10,
  p_window_minutes int DEFAULT 60
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_count int;
  v_window_start timestamp with time zone;
BEGIN
  v_window_start := now() - (p_window_minutes || ' minutes')::interval;

  -- Get request count in current window
  SELECT COUNT(*) INTO v_count
  FROM public.rate_limits
  WHERE user_id = auth.uid()
    AND operation = p_operation
    AND window_start > v_window_start;

  IF v_count >= p_limit THEN
    RAISE EXCEPTION 'Rate limit exceeded for operation: %', p_operation
      USING HINT = 'Try again later',
            ERRCODE = 'RATE_LIMIT_EXCEEDED';
  END IF;

  -- Record this request
  INSERT INTO public.rate_limits (user_id, operation, window_start)
  VALUES (auth.uid(), p_operation, now());

  RETURN true;
END;
$$;

-- Trigger: Check rate limit before insert
CREATE OR REPLACE FUNCTION public.check_post_rate_limit()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM public.check_rate_limit('create_post', 5, 60);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER posts_rate_limit_trigger
BEFORE INSERT ON public.posts
FOR EACH ROW
EXECUTE FUNCTION public.check_post_rate_limit();
```

---

## Deployment Checklist for Supabase

### Pre-Deployment

- [ ] All migrations tested locally with `supabase migration up`
- [ ] All migrations can be rolled back with `supabase migration down`
- [ ] RLS policies created for all tables with sensitive data
- [ ] Functions have appropriate SECURITY DEFINER/INVOKER settings
- [ ] Function volatility (IMMUTABLE/STABLE/VOLATILE) correctly specified
- [ ] Recursive triggers have `pg_trigger_depth()` guards
- [ ] No circular dependencies between triggers
- [ ] Error messages are user-friendly
- [ ] Performance tested with `EXPLAIN ANALYZE`

### Supabase CLI Commands

```bash
# Initialize project
supabase init

# Create migration
supabase migration new add_feature_name

# Test locally
supabase start
supabase migration up

# Link to production
supabase link --project-ref your-project-ref

# Push migrations to production
supabase db push

# Pull schema from production (after changes via dashboard)
supabase db pull

# Check migration status
supabase migration list

# View logs
supabase functions list
supabase logs
```

---

## TypeScript Client Library for RLS Functions

```typescript
// lib/rls-helpers.ts
import { supabase } from './supabase'

export const RLSHelpers = {
  // Check admin status
  async isAdmin(): Promise<boolean> {
    const { data, error } = await supabase.rpc('is_admin')
    return error ? false : data ?? false
  },

  // Check ownership
  async ownsPost(postId: string): Promise<boolean> {
    const { data, error } = await supabase.rpc('user_owns_post', {
      post_id: postId,
    })
    return error ? false : data ?? false
  },

  // Get organizations
  async getOrganizations() {
    const { data, error } = await supabase.rpc('get_user_orgs')
    return { data, error }
  },

  // Update activity status
  async updateActivity(status: 'online' | 'idle' | 'offline') {
    const { data, error } = await supabase.rpc('update_user_activity', {
      p_status: status,
    })
    return { data, error }
  },
}
```

---

**Last Updated**: January 2025
**Supabase Version**: Latest (2025)
**PostgreSQL Version**: 15+
