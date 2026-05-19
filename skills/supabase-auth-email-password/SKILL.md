---
name: implementing-supabase-ssr-auth-nextjs-15
description: Implements complete Email/Password authentication with Supabase @supabase/ssr package and Next.js 15 App Router. Covers Server Actions, session middleware, PKCE flow, email callbacks, forgot password, RLS policies, and protected routes. Use when building secure authentication systems, handling email verification, protecting routes with middleware, or managing user sessions server-side.
---

# Supabase SSR Auth Implementation with Next.js 15

## Quick Start

### 1. Install Dependencies

```bash
npm install @supabase/ssr @supabase/supabase-js
```

### 2. Set Environment Variables

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-key  # For admin operations only
```

### 3. Create Server Client Helper

**`lib/supabase/server.ts`**

```typescript
import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Catch middleware cookie errors
          }
        },
      },
    }
  );
}
```

### 4. Create Browser Client Helper

**`lib/supabase/client.ts`**

```typescript
'use client';

import { createBrowserClient } from '@supabase/ssr';

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!
  );
}
```

### 5. Create Middleware for Session Refresh

**`lib/supabase/proxy.ts`**

```typescript
import { type NextRequest, NextResponse } from 'next/server';
import { createServerClient } from '@supabase/ssr';

export async function updateSession(request: NextRequest) {
  let supabaseResponse = NextResponse.next({
    request,
  });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // Refresh session to update auth tokens before expiry
  await supabase.auth.getUser();

  return supabaseResponse;
}
```

**`middleware.ts`** (root level)

```typescript
import { type NextRequest } from 'next/server';
import { updateSession } from '@/lib/supabase/proxy';

export async function middleware(request: NextRequest) {
  return await updateSession(request);
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
```

---

## When to Use This Skill

- **Email/Password Authentication**: Building login and signup systems
- **Email Verification**: Handling PKCE flow with confirmation emails
- **Protected Routes**: Redirecting unauthenticated users via middleware
- **Session Management**: Keeping auth tokens fresh server-side
- **Password Recovery**: Implementing forgot password flows
- **Server-Side Auth**: Accessing user data in Server Components or Route Handlers
- **RLS Policies**: Securing database queries with Row Level Security

---

## Core Architecture

### The Auth Flow (Server Actions)

#### Sign Up with Email Confirmation

**`actions/auth.ts`**

```typescript
'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';

export async function signUp(formData: FormData) {
  const supabase = await createClient();
  const email = formData.get('email') as string;
  const password = formData.get('password') as string;

  // Validate input
  if (!email || !password || password.length < 8) {
    return { error: 'Invalid email or password (min 8 chars)' };
  }

  const { error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      emailRedirectTo: `${process.env.NEXT_PUBLIC_APP_URL}/auth/callback`,
    },
  });

  if (error) {
    return { error: error.message };
  }

  // Don't redirect yet - user needs to confirm email
  return { success: 'Check your email to confirm signup' };
}
```

#### Sign In

```typescript
export async function signIn(formData: FormData) {
  const supabase = await createClient();
  const email = formData.get('email') as string;
  const password = formData.get('password') as string;

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    return { error: error.message };
  }

  // Redirect on success
  revalidatePath('/', 'layout');
  redirect('/dashboard');
}
```

#### Sign Out

```typescript
export async function signOut() {
  const supabase = await createClient();
  
  await supabase.auth.signOut();
  
  revalidatePath('/', 'layout');
  redirect('/login');
}
```

### Email Confirmation Callback

**`app/auth/callback/route.ts`**

This route handles the PKCE exchange after email verification:

```typescript
import { type EmailOtpType } from '@supabase/supabase-js';
import { type NextRequest, NextResponse } from 'next/server';
import { createClient } from '@/lib/supabase/server';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get('code');
  const next = searchParams.get('next') ?? '/dashboard';

  if (code) {
    const supabase = await createClient();
    
    // Exchange the code for a session (PKCE flow)
    const { error } = await supabase.auth.exchangeCodeForSession(code);

    if (!error) {
      // Redirect authenticated user to dashboard
      return NextResponse.redirect(new URL(next, request.url));
    }
  }

  // Return to auth error page which redirects to login
  return NextResponse.redirect(new URL('/auth/auth-code-error', request.url));
}
```

---

## Protected Routes Pattern

### Option 1: Middleware-Based Protection (Recommended)

**`middleware.ts`** enhanced:

```typescript
import { type NextRequest, NextResponse } from 'next/server';
import { updateSession } from '@/lib/supabase/proxy';
import { createServerClient } from '@supabase/ssr';

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  
  // Update session
  let response = await updateSession(request);

  // Get user
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Protect /dashboard routes
  if (pathname.startsWith('/dashboard') && !user) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // Redirect authenticated users away from login
  if (pathname === '/login' && user) {
    return NextResponse.redirect(new URL('/dashboard', request.url));
  }

  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)', '/dashboard/:path*', '/login'],
};
```

### Option 2: Layout Component Protection

For additional safety, verify user in layout:

**`app/dashboard/layout.tsx`**

```typescript
import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect('/login');
  }

  return <>{children}</>;
}
```

---

## Advanced: Forgot Password Flow

### Step 1: Request Reset Link

**`actions/auth.ts`** (add to file)

```typescript
export async function resetPassword(formData: FormData) {
  const supabase = await createClient();
  const email = formData.get('email') as string;

  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${process.env.NEXT_PUBLIC_APP_URL}/auth/reset-password`,
  });

  if (error) {
    return { error: error.message };
  }

  return { success: 'Check your email for reset link' };
}
```

### Step 2: Update Password Page

**`app/auth/reset-password/page.tsx`**

```typescript
'use client';

import { useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { useRouter } from 'next/navigation';

export default function ResetPasswordPage() {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const supabase = createClient();

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    const { error } = await supabase.auth.updateUser({ password });

    if (error) {
      alert(error.message);
    } else {
      alert('Password updated successfully');
      router.push('/dashboard');
    }

    setLoading(false);
  };

  return (
    <form onSubmit={handleResetPassword}>
      <input
        type="password"
        placeholder="New password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <button disabled={loading}>
        {loading ? 'Updating...' : 'Update Password'}
      </button>
    </form>
  );
}
```

---

## RLS Policies & JWT Claims

### Enable Row Level Security

```sql
-- Enable RLS on your table
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- Policy: Users can read their own data
CREATE POLICY "Users can read own profile"
  ON profiles
  FOR SELECT
  USING (auth.uid() = user_id);

-- Policy: Users can update their own data
CREATE POLICY "Users can update own profile"
  ON profiles
  FOR UPDATE
  USING (auth.uid() = user_id);
```

### Using Custom JWT Claims

Set custom claims when creating user:

```typescript
// Server-side only - requires service role key
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!, // Service key only
  {
    auth: { persistSession: false },
  }
);

// Create user with custom claims
await supabase.auth.admin.createUser({
  email,
  password,
  user_metadata: {
    app_role: 'admin',
    organization_id: 'org_123',
  },
});
```

### RLS Policy with Custom Claims

```sql
-- Admin override: admins can read all
CREATE POLICY "Admins read all"
  ON profiles
  FOR SELECT
  USING (auth.jwt()->>'app_role' = 'admin');

-- Multi-tenant: read own organization's data
CREATE POLICY "Read own org data"
  ON profiles
  FOR SELECT
  USING (
    organization_id = (auth.jwt()->>'organization_id')
    OR auth.jwt()->>'app_role' = 'admin'
  );
```

---

## Best Practices

### Session Management

✅ **DO**: Refresh session in middleware BEFORE route rendering
- Ensures access token is valid
- Prevents "auth session missing on server" errors
- Automatically updates refresh tokens

✅ **DO**: Use separate client instances
- `createClient()` for Server Components/Actions
- `createBrowserClient()` for Client Components
- Each handles cookies appropriately

✅ **DO**: Always redirect after auth actions
- Use `redirect()` inside Server Actions
- Triggers cookie update and page revalidation
- Prevents stale UI state

### Security

✅ **DO**: Verify PKCE flow limitations
- Email links must be clicked in SAME browser/device
- Code verifier stored client-side cannot transfer devices
- Document this limitation to users

✅ **DO**: Enable RLS on all tables
- Client-side validation can be bypassed
- RLS enforced in PostgreSQL - cannot bypass
- Always use `auth.uid()` or JWT claims

✅ **DO**: Use Service Role Key only on server
- Never expose in environment variables sent to client
- Service key bypasses RLS - security risk
- Use only for admin operations

❌ **DON'T**: Store tokens in localStorage
- @supabase/ssr handles cookies automatically
- Prevents XSS attacks from accessing tokens
- Cookies are httpOnly when configured properly

❌ **DON'T**: Call `getUser()` on every request
- Use middleware to refresh once per request
- Let `getSession()` check local cookie state first
- Reduces database load and improves performance

---

## Common Errors & Solutions

### "Auth session is null on server but exists on client"

**Cause**: Middleware didn't run or `getUser()` wasn't called

**Solution**: 
```typescript
// In middleware.ts, ensure updateSession runs
export async function middleware(request: NextRequest) {
  return await updateSession(request); // Must call
}

// Verify matcher includes all routes
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
```

### "PKCE code exchange failed"

**Cause**: Email link clicked in different browser/device than signup

**Solution**: This is expected behavior
```typescript
// Document to users:
// "Click the confirmation link in the SAME browser you signed up with"

// For mobile: provide OTP alternative
const { error } = await supabase.auth.signUp({
  email,
  password,
  options: {
    emailRedirectTo: `${url}/auth/callback`,
    // Optionally add captcha or additional verification
  },
});
```

### "RLS policy violation - unable to read row"

**Cause**: User's JWT doesn't match RLS policy conditions

**Solution**:
```typescript
// 1. Verify policy uses correct function
-- Correct:
USING (auth.uid() = user_id);

-- Wrong (this won't work):
USING (user_id = current_user);

// 2. Check JWT claims if using custom claims
SELECT auth.jwt()->>'sub'; -- User ID
SELECT auth.jwt()->>'app_role'; -- Custom claim

// 3. Ensure user is authenticated
const { data: { user } } = await supabase.auth.getUser();
// If user is null, RLS will deny access
```

### "Redirect inside Server Action not working"

**Cause**: Not using Next.js `redirect()` from `next/navigation`

**Solution**:
```typescript
'use server';

import { redirect } from 'next/navigation'; // Correct import

export async function signIn(formData: FormData) {
  const supabase = await createClient();
  // ... auth logic
  
  redirect('/dashboard'); // Works - special Next.js behavior
  // Don't use return NextResponse.redirect() in Server Actions
}
```

### "Cookies not persisting after auth"

**Cause**: Cookie helpers not properly configured in client

**Solution**:
```typescript
// In createServerClient, ensure getAll/setAll are defined:
const supabase = createServerClient(
  url, key,
  {
    cookies: {
      getAll() {
        return request.cookies.getAll(); // Must return array
      },
      setAll(cookiesToSet) {
        // Must set each cookie
        cookiesToSet.forEach(({ name, value, options }) => {
          response.cookies.set(name, value, options);
        });
      },
    },
  }
);
```

### "Invalid or expired code"

**Cause**: Code already exchanged, token expired (> 10 minutes)

**Solution**:
```typescript
// In callback route, handle gracefully:
const { error } = await supabase.auth.exchangeCodeForSession(code);

if (error?.status === 400) {
  // Likely expired or already used
  return NextResponse.redirect(
    new URL('/login?error=verification-expired', request.url)
  );
}
```

---

## File Structure Reference

```
src/
├── app/
│   ├── middleware.ts                    # Session refresh + route protection
│   ├── auth/
│   │   ├── callback/route.ts           # PKCE exchange endpoint
│   │   ├── reset-password/page.tsx     # Password update form
│   │   └── auth-code-error/page.tsx    # Error fallback
│   ├── dashboard/
│   │   ├── layout.tsx                  # Additional auth check
│   │   └── page.tsx                    # Protected content
│   └── login/
│       └── page.tsx                    # Login/signup form
├── actions/
│   └── auth.ts                         # Server Actions (signUp, signIn, signOut, etc.)
└── lib/
    └── supabase/
        ├── server.ts                   # createClient() helper
        ├── client.ts                   # createBrowserClient() helper
        └── proxy.ts                    # updateSession() for middleware

.env.local:
NEXT_PUBLIC_SUPABASE_URL=https://...
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...          # Server-only
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

---

## References

- [Supabase SSR Documentation](https://supabase.com/docs/guides/auth/server-side/creating-a-client)
- [PKCE Flow Guide](https://supabase.com/docs/guides/auth/sessions/pkce-flow)
- [Row Level Security Policies](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase Auth API Reference](https://supabase.com/docs/reference/javascript/auth-signup)
- [Next.js 15 App Router Documentation](https://nextjs.org/docs/app)
- [JWT Claims in RLS Policies](https://supabase.com/docs/guides/database/postgres/row-level-security#using-role-based-access-control)
- [Session Management Best Practices](https://supabase.com/docs/guides/auth/sessions)
