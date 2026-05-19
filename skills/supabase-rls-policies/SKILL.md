---
name: supabase-rls-multi-tenant-fortress
description: Designing and applying robust Row Level Security (RLS) policies for multi-tenant applications to ensure strict data isolation and security at the database layer.
---

# Supabase RLS Multi-Tenant Fortress

## Metadata
- **Name:** Supabase RLS Multi-Tenant Fortress
- **Category:** Backend Security
- **Priority:** P0 (Critical Security)
- **Domain:** PostgreSQL, Supabase Auth, Row Level Security, Multi-tenancy
- **Owner Role:** Backend/Security Engineer
- **Complexity:** High

## Mission
Design and enforce "Fort Knox" level security at the database layer using PostgreSQL Row Level Security (RLS). Ensure that **no query** can ever leak data across tenants (organizations/users), regardless of bugs in the application code. The database must defend itself.

## Core Principles
1.  **Deny by Default:** Enable RLS on ALL tables. If no policy exists, no access is granted.
2.  **Tenant Isolation:** Every query must filter by `organization_id` or `user_id` enforced by policy.
3.  **Service Role Bypass:** Only specific administrative Edge Functions use `service_role`; everything else uses the authenticated user's JWT.
4.  **Performance:** Policies are executed on every row scan. They must be fast (indexed columns only).

## Implementation Strategy

### 1. Enabling RLS
Run this for **every single table** in the public schema.
```sql
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.todos ENABLE ROW LEVEL SECURITY;
-- ...
```

### 2. The Policies (Golden Patterns)

**Pattern A: Private User Data (1-to-1)**
*Users can only see/edit their own rows.*
```sql
-- Read
CREATE POLICY "Users can view own data"
  ON public.profiles
  FOR SELECT
  TO authenticated
  USING ( auth.uid() = id );

-- Update
CREATE POLICY "Users can update own data"
  ON public.profiles
  FOR UPDATE
  TO authenticated
  USING ( auth.uid() = id );
```

**Pattern B: Organization Multi-Tenancy (Many-to-Many)**
*Users belong to Organizations. Data belongs to Organizations.*
*Requires a `organization_members` table linking users to orgs.*

Helper Function (Crucial for performance/cleanliness):
```sql
-- Create a secure helper function to check membership
CREATE OR REPLACE FUNCTION is_org_member(_org_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1
    FROM organization_members
    WHERE organization_id = _org_id
    AND user_id = auth.uid()
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

RLS Policy using Helper:
```sql
CREATE POLICY "Org members can view org projects"
  ON public.projects
  FOR SELECT
  TO authenticated
  USING ( is_org_member(organization_id) );
```

**Pattern C: Public Read / Admin Write**
*Everyone can read (e.g., blog posts), only admins can write.*
```sql
-- Read (Public)
CREATE POLICY "Public read access"
  ON public.posts
  FOR SELECT
  TO anon, authenticated 
  USING ( published = true );

-- Write (Admin only)
-- Assumes you have a custom claim or a generic 'admins' table
CREATE POLICY "Admins can insert"
  ON public.posts
  FOR INSERT
  TO authenticated
  WITH CHECK ( 
    EXISTS (SELECT 1 FROM admins WHERE user_id = auth.uid()) 
  );
```

### 3. Testing Policies
Never assume it works. Test it.

**SQL Test Script:**
```sql
-- 1. Switch to a specific user
SET "request.jwt.claim.sub" = 'user-uuid-123';
SET ROLE authenticated;

-- 2. Try to select data from another user
SELECT * FROM private_data; 
-- Expect: Empty result set (if RLS is working) or Error.

-- 3. Try to select own data
SELECT * FROM private_data WHERE user_id = 'user-uuid-123';
-- Expect: Data returned.
```

### 4. Common Pitfalls
-   **Infinite Recursion:** A policy on Table A queries Table A.
-   **Performance Killer:** Joining 5 tables inside a policy. Use denormalization (store `org_id` on the child table) or efficient naming conventions to avoid deep joins.
-   **Forgot `WITH CHECK`:** `USING` controls visibility (SELECT/UPDATE/DELETE). `WITH CHECK` controls what data can be INSERTED/UPDATED.
    -   *Example:* I can see row A, but I shouldn't be able to UPDATE row A to belong to `user_id` B.

## Checklist
- [ ] RLS enabled on all tables?
- [ ] Policies defined for SELECT, INSERT, UPDATE, DELETE?
- [ ] Helper functions used for complex logic?
- [ ] Indexes exist on all columns used in policies (`user_id`, `org_id`)?
- [ ] Tested with `anon`, `authenticated` (user A), `authenticated` (user B)?
