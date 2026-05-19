# PostgreSQL Functions & Triggers - Implementation Cookbook

## Complete Project Setup Example

### Project Structure

```
my-supabase-app/
├── supabase/
│   ├── migrations/
│   │   ├── 20250120_000000_init.sql
│   │   ├── 20250120_001000_create_audit_system.sql
│   │   ├── 20250120_002000_create_user_functions.sql
│   │   └── 20250120_003000_create_triggers.sql
│   ├── seed.sql
│   └── config.toml
├── src/
│   ├── lib/
│   │   ├── supabase.ts
│   │   └── database.types.ts
│   ├── hooks/
│   │   ├── useRpc.ts
│   │   └── useFunctionCall.ts
│   └── components/
│       └── examples/
└── package.json
```

---

## Migration 1: Initialize Database Schema

**File**: `supabase/migrations/20250120_000000_init.sql`

```sql
BEGIN;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Users table
CREATE TABLE IF NOT EXISTS public.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text UNIQUE NOT NULL,
  name text,
  avatar_url text,
  bio text,
  status text DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'banned')),
  email_verified_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Posts table
CREATE TABLE IF NOT EXISTS public.posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  title text NOT NULL,
  slug text UNIQUE,
  content text NOT NULL,
  excerpt text,
  published boolean DEFAULT false,
  view_count int DEFAULT 0,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Comments table
CREATE TABLE IF NOT EXISTS public.comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id uuid NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  content text NOT NULL,
  likes_count int DEFAULT 0,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Audit logs table
CREATE TABLE IF NOT EXISTS public.audit_logs (
  id bigserial PRIMARY KEY,
  table_name text NOT NULL,
  record_id uuid NOT NULL,
  operation text NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
  changed_by uuid,
  old_values jsonb,
  new_values jsonb,
  changed_at timestamp with time zone DEFAULT now()
);

-- Create indexes
CREATE INDEX idx_posts_user_id ON public.posts(user_id);
CREATE INDEX idx_posts_published ON public.posts(published) WHERE published = true;
CREATE INDEX idx_comments_post_id ON public.comments(post_id);
CREATE INDEX idx_comments_user_id ON public.comments(user_id);
CREATE INDEX idx_audit_logs_table_record ON public.audit_logs(table_name, record_id);
CREATE INDEX idx_audit_logs_created ON public.audit_logs(changed_at DESC);

COMMIT;
```

---

## Migration 2: Setup Audit System

**File**: `supabase/migrations/20250120_001000_create_audit_system.sql`

```sql
BEGIN;

-- Function: Log all changes
CREATE OR REPLACE FUNCTION public.audit_trigger_func()
RETURNS TRIGGER AS $$
DECLARE
  v_changed_by uuid;
BEGIN
  -- Try to get current user
  BEGIN
    v_changed_by := auth.uid();
  EXCEPTION WHEN OTHERS THEN
    v_changed_by := NULL;
  END;

  IF TG_OP = 'DELETE' THEN
    INSERT INTO public.audit_logs (
      table_name, record_id, operation, changed_by, old_values, changed_at
    ) VALUES (
      TG_TABLE_NAME,
      OLD.id,
      'DELETE',
      v_changed_by,
      row_to_json(OLD),
      now()
    );
    RETURN OLD;
  ELSIF TG_OP = 'INSERT' THEN
    INSERT INTO public.audit_logs (
      table_name, record_id, operation, changed_by, new_values, changed_at
    ) VALUES (
      TG_TABLE_NAME,
      NEW.id,
      'INSERT',
      v_changed_by,
      row_to_json(NEW),
      now()
    );
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO public.audit_logs (
      table_name, record_id, operation, changed_by, old_values, new_values, changed_at
    ) VALUES (
      TG_TABLE_NAME,
      NEW.id,
      'UPDATE',
      v_changed_by,
      row_to_json(OLD),
      row_to_json(NEW),
      now()
    );
    RETURN NEW;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Enable RLS on audit_logs
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

-- Policy: Users can see audit logs for their own records
CREATE POLICY "Users see own audit logs"
ON public.audit_logs FOR SELECT
USING (
  changed_by = auth.uid() OR
  EXISTS (
    SELECT 1 FROM public.users 
    WHERE id = auth.uid() AND status = 'active'
  )
);

COMMIT;
```

---

## Migration 3: Create User Functions

**File**: `supabase/migrations/20250120_002000_create_user_functions.sql`

```sql
BEGIN;

-- Function: Auto-update timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Generate slug from title
CREATE OR REPLACE FUNCTION public.generate_post_slug()
RETURNS TRIGGER AS $$
BEGIN
  NEW.slug := lower(
    regexp_replace(
      regexp_replace(
        trim(NEW.title),
        '[^a-z0-9\s-]',
        '',
        'gi'
      ),
      '\s+',
      '-',
      'g'
    )
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Validate email format
CREATE OR REPLACE FUNCTION public.validate_email_format()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$' THEN
    RAISE EXCEPTION 'Invalid email format: %', NEW.email;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function: Get post statistics
CREATE OR REPLACE FUNCTION public.get_post_stats(post_id uuid)
RETURNS TABLE (
  total_comments bigint,
  total_likes bigint,
  avg_likes_per_comment numeric
) LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT
    COUNT(c.id)::bigint as total_comments,
    SUM(c.likes_count)::bigint as total_likes,
    COALESCE(AVG(c.likes_count), 0)::numeric as avg_likes_per_comment
  FROM public.comments c
  WHERE c.post_id = $1;
$$;

-- Function: Get user activity
CREATE OR REPLACE FUNCTION public.get_user_activity(user_id uuid)
RETURNS TABLE (
  total_posts bigint,
  total_comments bigint,
  total_likes_received bigint,
  last_post_date timestamp with time zone
) LANGUAGE sql STABLE AS $$
  SELECT
    COUNT(DISTINCT p.id)::bigint as total_posts,
    COUNT(DISTINCT c.id)::bigint as total_comments,
    SUM(c.likes_count)::bigint as total_likes_received,
    MAX(p.created_at) as last_post_date
  FROM public.users u
  LEFT JOIN public.posts p ON u.id = p.user_id
  LEFT JOIN public.comments c ON u.id = c.user_id
  WHERE u.id = $1
  GROUP BY u.id;
$$;

-- Function: Increment view count
CREATE OR REPLACE FUNCTION public.increment_post_views(post_id uuid)
RETURNS int LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
  v_new_count int;
BEGIN
  UPDATE public.posts
  SET view_count = view_count + 1
  WHERE id = post_id
  RETURNING view_count INTO v_new_count;
  
  RETURN v_new_count;
END;
$$;

COMMIT;
```

---

## Migration 4: Create Triggers

**File**: `supabase/migrations/20250120_003000_create_triggers.sql`

```sql
BEGIN;

-- Trigger: Update timestamp on user update
CREATE TRIGGER users_update_timestamp_trigger
BEFORE UPDATE ON public.users
FOR EACH ROW
WHEN (NEW.updated_at IS NULL OR NEW.updated_at = OLD.updated_at)
EXECUTE FUNCTION public.update_updated_at_column();

-- Trigger: Update timestamp on post update
CREATE TRIGGER posts_update_timestamp_trigger
BEFORE UPDATE ON public.posts
FOR EACH ROW
WHEN (NEW.updated_at IS NULL OR NEW.updated_at = OLD.updated_at)
EXECUTE FUNCTION public.update_updated_at_column();

-- Trigger: Update timestamp on comment update
CREATE TRIGGER comments_update_timestamp_trigger
BEFORE UPDATE ON public.comments
FOR EACH ROW
WHEN (NEW.updated_at IS NULL OR NEW.updated_at = OLD.updated_at)
EXECUTE FUNCTION public.update_updated_at_column();

-- Trigger: Validate user email
CREATE TRIGGER users_validate_email_trigger
BEFORE INSERT OR UPDATE ON public.users
FOR EACH ROW
WHEN (NEW.email IS DISTINCT FROM OLD.email OR NEW.email IS NOT NULL)
EXECUTE FUNCTION public.validate_email_format();

-- Trigger: Generate post slug
CREATE TRIGGER posts_generate_slug_trigger
BEFORE INSERT OR UPDATE ON public.posts
FOR EACH ROW
WHEN (NEW.title IS DISTINCT FROM OLD.title OR NEW.title IS NOT NULL)
EXECUTE FUNCTION public.generate_post_slug();

-- Trigger: Audit user changes
CREATE TRIGGER users_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.users
FOR EACH ROW
WHEN (pg_trigger_depth() = 1)
EXECUTE FUNCTION public.audit_trigger_func();

-- Trigger: Audit post changes
CREATE TRIGGER posts_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.posts
FOR EACH ROW
WHEN (pg_trigger_depth() = 1)
EXECUTE FUNCTION public.audit_trigger_func();

-- Trigger: Audit comment changes
CREATE TRIGGER comments_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.comments
FOR EACH ROW
WHEN (pg_trigger_depth() = 1)
EXECUTE FUNCTION public.audit_trigger_func();

COMMIT;
```

---

## TypeScript Integration

### Generated Types

**File**: `src/lib/database.types.ts` (auto-generated by Supabase CLI)

```typescript
export type Database = {
  public: {
    Tables: {
      users: {
        Row: {
          id: string
          email: string
          name: string | null
          avatar_url: string | null
          bio: string | null
          status: 'active' | 'inactive' | 'banned'
          email_verified_at: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          email: string
          name?: string | null
          avatar_url?: string | null
          bio?: string | null
          status?: 'active' | 'inactive' | 'banned'
          email_verified_at?: string | null
          created_at?: string
          updated_at?: string
        }
        Update: {
          id?: string
          email?: string
          name?: string | null
          avatar_url?: string | null
          bio?: string | null
          status?: 'active' | 'inactive' | 'banned'
          email_verified_at?: string | null
          created_at?: string
          updated_at?: string
        }
      }
      posts: {
        Row: {
          id: string
          user_id: string
          title: string
          slug: string | null
          content: string
          excerpt: string | null
          published: boolean
          view_count: number
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          user_id: string
          title: string
          slug?: string | null
          content: string
          excerpt?: string | null
          published?: boolean
          view_count?: number
          created_at?: string
          updated_at?: string
        }
        Update: {
          id?: string
          user_id?: string
          title?: string
          slug?: string | null
          content?: string
          excerpt?: string | null
          published?: boolean
          view_count?: number
          created_at?: string
          updated_at?: string
        }
      }
    }
    Functions: {
      get_post_stats: {
        Args: { post_id: string }
        Returns: {
          total_comments: number
          total_likes: number
          avg_likes_per_comment: number
        }[]
      }
      get_user_activity: {
        Args: { user_id: string }
        Returns: {
          total_posts: number
          total_comments: number
          total_likes_received: number
          last_post_date: string | null
        }[]
      }
      increment_post_views: {
        Args: { post_id: string }
        Returns: number
      }
    }
  }
}
```

### Supabase Client Setup

**File**: `src/lib/supabase.ts`

```typescript
import { createClient } from '@supabase/supabase-js'
import type { Database } from './database.types'

export const supabase = createClient<Database>(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

// Type-safe RPC wrapper
export const db = {
  // RPC Functions
  getPostStats: (postId: string) =>
    supabase.rpc('get_post_stats', { post_id: postId }),

  getUserActivity: (userId: string) =>
    supabase.rpc('get_user_activity', { user_id: userId }),

  incrementPostViews: (postId: string) =>
    supabase.rpc('increment_post_views', { post_id: postId }),

  // Queries
  users: {
    getById: (id: string) =>
      supabase.from('users').select('*').eq('id', id).single(),
    
    create: (user: Database['public']['Tables']['users']['Insert']) =>
      supabase.from('users').insert([user]).select().single(),

    update: (id: string, updates: Database['public']['Tables']['users']['Update']) =>
      supabase.from('users').update(updates).eq('id', id).select().single(),
  },

  posts: {
    getAll: (limit = 10) =>
      supabase
        .from('posts')
        .select(`
          *,
          user:users(id, name, avatar_url),
          comments:comments(id)
        `)
        .eq('published', true)
        .order('created_at', { ascending: false })
        .limit(limit),

    create: (post: Database['public']['Tables']['posts']['Insert']) =>
      supabase.from('posts').insert([post]).select().single(),
  },

  auditLogs: {
    getForRecord: (tableName: string, recordId: string) =>
      supabase
        .from('audit_logs')
        .select('*')
        .eq('table_name', tableName)
        .eq('record_id', recordId)
        .order('changed_at', { ascending: false }),
  },
}
```

### React Hook for RPC Functions

**File**: `src/hooks/useRpc.ts`

```typescript
import { useState, useCallback, useEffect } from 'react'
import { supabase } from '@/lib/supabase'

interface UseRpcOptions {
  autoFetch?: boolean
  onError?: (error: Error) => void
  onSuccess?: (data: any) => void
}

export function useRpc<T>(
  functionName: string,
  args?: Record<string, any>,
  options: UseRpcOptions = {}
) {
  const { autoFetch = false, onError, onSuccess } = options
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(autoFetch)
  const [error, setError] = useState<Error | null>(null)

  const call = useCallback(
    async (callArgs?: Record<string, any>) => {
      setLoading(true)
      setError(null)

      try {
        const { data: result, error: err } = await supabase.rpc(
          functionName,
          callArgs || args || {}
        )

        if (err) {
          throw new Error(err.message)
        }

        setData(result as T)
        onSuccess?.(result)
        return result
      } catch (e) {
        const error = e instanceof Error ? e : new Error(String(e))
        setError(error)
        onError?.(error)
        throw error
      } finally {
        setLoading(false)
      }
    },
    [functionName, args, onError, onSuccess]
  )

  useEffect(() => {
    if (autoFetch) {
      call()
    }
  }, [autoFetch, call])

  return { data, loading, error, call, refetch: call }
}
```

### Example Component Usage

**File**: `src/components/examples/PostStats.tsx`

```typescript
'use client'

import { useEffect } from 'react'
import { useRpc } from '@/hooks/useRpc'
import type { Database } from '@/lib/database.types'

type PostStats = Database['public']['Functions']['get_post_stats']['Returns'][0]

interface PostStatsProps {
  postId: string
}

export function PostStats({ postId }: PostStatsProps) {
  const { data: stats, loading, error, refetch } = useRpc<PostStats[]>(
    'get_post_stats',
    { post_id: postId }
  )

  useEffect(() => {
    refetch()
  }, [postId, refetch])

  if (loading) {
    return <div className="text-gray-500">Loading statistics...</div>
  }

  if (error) {
    return <div className="text-red-500">Error: {error.message}</div>
  }

  const stat = stats?.[0]
  if (!stat) {
    return <div className="text-gray-400">No statistics available</div>
  }

  return (
    <div className="flex gap-6 text-sm text-gray-600">
      <div>
        <span className="font-semibold">{stat.total_comments}</span>
        <span className="ml-1">comments</span>
      </div>
      <div>
        <span className="font-semibold">{stat.total_likes}</span>
        <span className="ml-1">likes</span>
      </div>
      <div>
        <span className="font-semibold">
          {stat.avg_likes_per_comment.toFixed(1)}
        </span>
        <span className="ml-1">avg likes/comment</span>
      </div>
    </div>
  )
}
```

---

## Practical Testing Examples

### Manual Testing in Supabase Studio

```sql
-- Test 1: Create a user (auto-validates email)
INSERT INTO users (email, name) VALUES ('john@example.com', 'John Doe');

-- Test 2: Update user (updated_at auto-updated by trigger)
UPDATE users SET name = 'John Smith' WHERE email = 'john@example.com';

-- Test 3: Create a post (slug auto-generated)
INSERT INTO posts (user_id, title, content)
SELECT id, 'My First Post', 'This is my first post content'
FROM users WHERE email = 'john@example.com';

-- Test 4: Check audit logs (should see all changes)
SELECT * FROM audit_logs ORDER BY changed_at DESC LIMIT 10;

-- Test 5: Get post statistics
SELECT * FROM get_post_stats(
  (SELECT id FROM posts LIMIT 1)
);

-- Test 6: Increment view count
SELECT increment_post_views(
  (SELECT id FROM posts LIMIT 1)
);
```

---

## Error Recovery Examples

### Handling Validation Errors in TypeScript

```typescript
export async function createPostWithValidation(
  userId: string,
  title: string,
  content: string
) {
  try {
    const { data, error } = await supabase
      .from('posts')
      .insert({
        user_id: userId,
        title,
        content,
      })
      .select()
      .single()

    if (error) {
      // Check if it's a specific error
      if (error.message.includes('duplicate key')) {
        throw new Error('A post with this title already exists')
      }
      throw error
    }

    return { success: true, data }
  } catch (e) {
    console.error('Failed to create post:', e)
    return {
      success: false,
      error: e instanceof Error ? e.message : 'Unknown error',
    }
  }
}
```

---

**Last Updated**: January 2025
