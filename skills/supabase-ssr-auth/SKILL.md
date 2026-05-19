---
name: supabase-ssr-nextjs-15-authentication
description: Implements production-grade Supabase SSR authentication in Next.js 15 using @supabase/ssr package with PKCE flow, token refresh in middleware, and secure Server Components. Use when building Next.js 15+ apps requiring secure login, protected routes, OAuth, and server-side auth without deprecated auth-helpers.
---

# Supabase SSR Authentication in Next.js 15 (2025 Guide)

## Quick Start

### 1. Install Dependencies
```bash
npm install @supabase/supabase-js @supabase/ssr
npm uninstall @supabase/auth-helpers-nextjs  # Remove if present
```

### 2. Environment Variables
Create `.env.local`:
```env
NEXT_PUBLIC_SUPABASE_URL=https://xxxyyyzzz.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxx...
```

### 3. Create Client Utilities

**lib/supabase/client.ts** - Browser client (use in Client Components)
```typescript
import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!
  )
}
```

**lib/supabase/server.ts** - Server client (use in Server Components, Actions, Route Handlers)
```typescript
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

export async function createClient() {
  const cookieStore = await cookies()

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            )
          } catch {
            // Ignored: setAll may be called from Server Components
            // Middleware will refresh and set cookies on response
          }
        },
      },
    }
  )
}
```

### 4. Middleware (Token Refresh - CRITICAL)
**middleware.ts** - Refreshes expired tokens before rendering Server Components
```typescript
import { type NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/middleware'

export async function middleware(request: NextRequest) {
  return await updateSession(request)
}

export const config = {
  // Exclude static files and images
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'],
}
```

**lib/supabase/middleware.ts** - Token refresh logic
```typescript
import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

export async function updateSession(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          )
          // Create fresh response with updated cookies
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  // CRITICAL: Call getClaims() immediately after createServerClient
  // This refreshes expired tokens and prevents random logouts
  // Do NOT run other code between createServerClient and getClaims()
  const { data: { claims } } = await supabase.auth.getClaims()

  // Optional: Redirect unauthenticated users
  if (!claims && !isPublicRoute(request.nextUrl.pathname)) {
    const loginUrl = request.nextUrl.clone()
    loginUrl.pathname = '/login'
    return NextResponse.redirect(loginUrl)
  }

  return supabaseResponse
}

function isPublicRoute(pathname: string): boolean {
  const publicRoutes = ['/login', '/signup', '/auth/callback']
  return publicRoutes.some(route => pathname.startsWith(route))
}
```

### 5. Login Server Action
**app/auth/actions.ts**
```typescript
'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

export async function signIn(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string

  const supabase = await createClient()

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    return { error: error.message }
  }

  revalidatePath('/', 'layout')
  redirect('/dashboard')
}

export async function signUp(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string

  const supabase = await createClient()

  const { error } = await supabase.auth.signUp({
    email,
    password,
  })

  if (error) {
    return { error: error.message }
  }

  // Email confirmation required - redirect to check inbox
  redirect('/auth/check-email')
}

export async function signOut() {
  const supabase = await createClient()
  await supabase.auth.signOut()

  revalidatePath('/', 'layout')
  redirect('/login')
}
```

### 6. Protected Server Component
**app/dashboard/page.tsx**
```typescript
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

export default async function DashboardPage() {
  const supabase = await createClient()

  // Use getUser() for secure validation (calls Supabase Auth API)
  const { data: { user }, error } = await supabase.auth.getUser()

  if (error || !user) {
    redirect('/login')
  }

  const { data: profile } = await supabase
    .from('profiles')
    .select('*')
    .eq('id', user.id)
    .single()

  return (
    <div>
      <h1>Welcome, {user.email}</h1>
      {/* Use profile data */}
    </div>
  )
}
```

## When to Use This Skill

- ✅ Building SSR apps with Next.js 15+ requiring authentication
- ✅ Migrating from deprecated `@supabase/auth-helpers-nextjs`
- ✅ Implementing secure token refresh in middleware
- ✅ Using Server Components for protected routes
- ✅ Building with PKCE flow (OAuth, passwordless, email/password)
- ✅ Production Next.js apps needing bulletproof auth

---

## Architecture & Key Concepts

### Why @supabase/ssr Replaced auth-helpers

| Aspect | auth-helpers | @supabase/ssr |
|--------|--------------|--------------|
| **Cookie Handling** | Built-in abstraction | Developer-controlled abstraction |
| **Maintenance** | Deprecated (no updates) | Active (2025+) |
| **Flexibility** | Fixed cookie behavior | Adapts to Next.js changes |
| **Bundle Size** | Larger | Lighter |
| **Breaking Changes** | Frequent | Stable |

**Core insight**: Cookie handling is a Next.js implementation detail that changes. By moving cookie logic to your code, Supabase avoids maintaining multiple versions.

### Client Types

**Browser Client** (`createBrowserClient`)
- Runs in Client Components
- Stores session in browser memory/localStorage
- Used for realtime subscriptions, client-side operations
- NOT used in middleware/server operations

**Server Client** (`createServerClient`)
- Runs in Server Components, Server Actions, Route Handlers, Middleware
- Uses cookies for session persistence
- Requires cookie abstraction (getAll/setAll)
- **THREE FLAVORS**:
  1. **Server Components** - Uses Next.js `cookies()` API
  2. **Middleware** - Uses `request.cookies` and `response.cookies`
  3. **Route Handlers** - Uses `request` and `response` objects

### Token Refresh Flow (CRITICAL)

**Problem**: Server Components cannot write cookies (immutable request/response pattern). Yet tokens expire and need refreshing.

**Solution**: Middleware intercepts EVERY request, refreshes the token if needed, and writes updated cookies to the response BEFORE Server Components render.

**Sequence**:
```
1. Browser sends request with auth cookie
         ↓
2. Middleware.ts executes updateSession()
         ↓
3. createServerClient created in middleware
         ↓
4. supabase.auth.getClaims() called IMMEDIATELY
   - Validates JWT signature
   - If expired, uses refresh token to get new access token
   - Returns claims or null
         ↓
5. Updated cookies set on response.cookies
         ↓
6. Server Components render with fresh session
         ↓
7. Response with refreshed cookies sent to browser
```

**Why getClaims() immediately?** It validates the JWT against Supabase's public keys. Doing anything else between `createServerClient` and `getClaims()` breaks the auth guarantee.

### getUser() vs getSession()

| Method | Where | What Happens | Result | Security |
|--------|-------|--------------|--------|----------|
| `getUser()` | Server/Client | Makes HTTP request to Supabase Auth API, validates JWT signature | Authentic user object or error | ✅ SECURE |
| `getSession()` | Client only | Reads from browser storage (cookies) | Session object | ✅ Safe on client |
| `getSession()` | Server | Reads cookie value without validation | Potentially spoofed user | ❌ INSECURE |

**Rule**: Use `getUser()` in Server Components for route protection. Browser cookies can be tampered with.

### PKCE Flow (Why It Matters)

**PKCE** (Proof Key for Code Exchange):
- Required for SSR apps with Supabase
- Implemented by @supabase/ssr automatically
- Email templates must use `{{ .TokenHash }}` (not implicit flow's `{{ .ConfirmationURL }}`)
- Code exchanges are one-time use (5-minute expiry)
- Cannot exchange code on different device than where it was initiated

**Setup**: Email template in Supabase Auth → Email Templates → Verify → Change to PKCE format:
```html
<!-- PKCE style (for SSR with Next.js) -->
<a href="{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=email_change">
  Confirm Email Change
</a>

<!-- NOT: implicit style (deprecated) -->
<!-- <a href="{{ .ConfirmationURL }}">Confirm</a> -->
```

---

## Usage Patterns

### Server Components: Fetch User Data
```typescript
// app/profile/page.tsx - SECURE
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

export default async function ProfilePage() {
  const supabase = await createClient()

  // getUser() calls Supabase to validate JWT
  const { data: { user }, error } = await supabase.auth.getUser()

  if (error || !user) {
    redirect('/login')
  }

  return <div>User: {user.email}</div>
}
```

### Server Actions: Sign In
```typescript
// app/auth/actions.ts
'use server'

import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

export async function login(email: string, password: string) {
  const supabase = await createClient()

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    throw new Error(error.message)
  }

  redirect('/dashboard')
}
```

### Route Handlers: API Endpoint
```typescript
// app/api/user/route.ts
import { createClient } from '@/lib/supabase/server'
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const supabase = await createClient()

  const { data: { user }, error } = await supabase.auth.getUser()

  if (error || !user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  return NextResponse.json({ user })
}
```

### Client Components: Realtime Subscriptions
```typescript
'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'

export default function RealtimeComponent() {
  const supabase = createClient()
  const [data, setData] = useState([])

  useEffect(() => {
    const channel = supabase
      .channel('messages')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'messages' }, (payload) => {
        setData(prev => [...prev, payload.new])
      })
      .subscribe()

    return () => supabase.removeChannel(channel)
  }, [])

  return <div>{data.length} messages</div>
}
```

---

## Best Practices

### 1. Cookie Security Configuration
**Development (localhost)**:
```env
# .env.local
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321  # Local Supabase
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=eyJ...
```

**Production**:
```typescript
// lib/supabase/middleware.ts - Auto-configured by @supabase/ssr
// Supabase automatically sets:
// - httpOnly: true (prevents XSS)
// - secure: true (HTTPS only)
// - sameSite: 'lax' (CSRF protection)
// - domain: .yourdomain.com (not localhost)
```

**Rationale**: httpOnly cookies cannot be accessed by JavaScript, preventing token theft via XSS. Middleware ensures cookies are set server-side, never exposed to client.

### 2. Always Call getClaims() in Middleware
```typescript
// ✅ CORRECT
const supabase = createServerClient(...)
const { data: { claims } } = await supabase.auth.getClaims()  // RIGHT HERE

// ❌ WRONG - Don't do other stuff first
const supabase = createServerClient(...)
const user = await getUser()  // Breaks token refresh guarantee
const { data: { claims } } = await supabase.auth.getClaims()
```

**Rationale**: `getClaims()` is where token refresh happens. Doing anything else before it means missed refresh opportunities and random logouts.

### 3. Use getUser() for Authorization
```typescript
// ✅ SECURE - Always validates
const { data: { user } } = await supabase.auth.getUser()
if (!user) return redirect('/login')

// ❌ INSECURE ON SERVER - Reads cookie without validation
const { data: { session } } = await supabase.auth.getSession()
if (!session) return redirect('/login')  // Falsely trusts cookie
```

**Rationale**: Sessions are stored in cookies which can be tampered with. `getUser()` makes an HTTP request to Supabase Auth, validating the JWT signature against published public keys.

### 4. Revalidate Cache After Auth Changes
```typescript
'use server'

import { revalidatePath } from 'next/cache'

export async function signOut() {
  const supabase = await createClient()
  await supabase.auth.signOut()

  // Refresh all cached pages to reflect new auth state
  revalidatePath('/', 'layout')
  redirect('/login')
}
```

**Rationale**: Next.js caches Server Component renders. After login/logout, stale user data remains cached. `revalidatePath` clears the cache.

### 5. Public Routes in Middleware
```typescript
function isPublicRoute(pathname: string): boolean {
  const publicRoutes = [
    '/login',
    '/signup',
    '/auth/callback',  // OAuth/magic link callback
    '/forgot-password',
    '/api/health',     // Health checks
  ]
  return publicRoutes.some(route => pathname.startsWith(route))
}

if (!claims && !isPublicRoute(request.nextUrl.pathname)) {
  redirect('/login')
}
```

**Rationale**: Redirecting from `/login` to `/login` creates infinite loops. Whitelist public routes to avoid redirect loops.

---

## Common Errors & Troubleshooting

### "Auth session missing!" in Production

**Symptom**: Works locally, fails on production (Vercel, etc.)
```
Error: Auth session missing!
Status: 401
```

**Causes & Fixes**:

| Cause | Fix |
|-------|-----|
| **Cookies not sent over HTTPS** | Ensure Vercel domain uses HTTPS. Check NEXT_PUBLIC_SUPABASE_URL uses `https://` |
| **Cookie domain mismatch** | Supabase uses auto-domain detection. Works automatically for *.vercel.app domains |
| **Redirect URL not configured** | Add `https://yourdomain.com/auth/callback` to Supabase Auth → URL Configuration |
| **Environment variables missing** | Redeploy after adding NEXT_PUBLIC_SUPABASE_URL to Vercel dashboard |

**Debug**:
```typescript
// Add logging in middleware.ts
console.log('Claims:', claims)
console.log('Cookies:', request.cookies.getAll())
console.log('Response cookies:', supabaseResponse.cookies.getAll())
```

### "Invalid Refresh Token: Already Used"

**Symptom**: Repeated refresh attempts causing token revocation
```
[AuthApiError: Invalid Refresh Token: Already Used]{
  __isAuthError: true,
  status: 400
}
```

**Causes**:
1. **Calling getClaims() multiple times per request** - Each call may use the refresh token
2. **Middleware configured wrong** - Running on routes it shouldn't
3. **Network issues** - Token refreshed but browser didn't receive response

**Fix**:
```typescript
// middleware.ts - ONLY call getClaims() ONCE
export async function updateSession(request: NextRequest) {
  const supabase = createServerClient(...)
  
  // ONLY THIS LINE calls refresh
  await supabase.auth.getClaims()
  
  // Don't call getUser() or other auth methods after
  
  return supabaseResponse
}
```

### "setAll() method was called from a Server Component"

**Symptom**: Warning in logs, but no actual error
```
The `setAll` method was called from a Server Component.
This can be ignored if you have middleware refreshing user sessions.
```

**Why**: Server Components can't write cookies. That's OK—middleware does it. This is expected behavior.

**Suppress** (if desired):
```typescript
// lib/supabase/server.ts
setAll(cookiesToSet) {
  try {
    cookiesToSet.forEach(({ name, value, options }) =>
      cookieStore.set(name, value, options)
    )
  } catch {
    // Expected: setAll may be called from Server Components
    // Middleware will refresh and set cookies correctly
  }
}
```

### TypeScript: "Cannot find module @supabase/ssr"

**Fix**:
```bash
# Delete node_modules and reinstall
rm -rf node_modules package-lock.json
npm install

# Or just install the package
npm install @supabase/ssr --save
```

### Infinite Redirect Loop

**Symptom**: Redirecting between /login and /dashboard repeatedly

**Causes**:
1. Middleware redirects unauthenticated users, but getUser() fails
2. Auth check not excluding public routes

**Fix**:
```typescript
// middleware.ts
function isPublicRoute(pathname: string): boolean {
  // IMPORTANT: Must match your actual public routes
  const publicRoutes = ['/login', '/signup', '/auth/callback', '/forgot-password']
  return publicRoutes.some(route => pathname.startsWith(route))
}

if (!claims && !isPublicRoute(request.nextUrl.pathname)) {
  const url = request.nextUrl.clone()
  url.pathname = '/login'
  return NextResponse.redirect(url)  // Don't redirect FROM /login TO /login
}
```

### OAuth Redirect Returns No Session

**Symptom**: OAuth callback arrives with `?code=...` but session not created

**Causes**:
1. Email template not updated to PKCE format (uses implicit flow tokens)
2. Redirect URL not in Supabase Auth URL Configuration
3. OAuth provider scopes not configured

**Fix - Update Email Template**:
```
Auth → Email Templates → Confirm Signup → Change to:

{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=email_signup

NOT:

{{ .ConfirmationURL }}
```

**Fix - Add Redirect URL**:
```
Supabase Dashboard → Auth → URL Configuration → Redirect URLs:
- http://localhost:3000/auth/callback
- https://yourdomain.com/auth/callback
```

---

## References

- **Official Docs**: [Supabase SSR Guide](https://supabase.com/docs/guides/auth/server-side-rendering)
- **Migration Guide**: [Auth Helpers → @supabase/ssr](https://supabase.com/docs/guides/troubleshooting/how-to-migrate-from-supabase-auth-helpers-to-ssr-package-5NRunM)
- **PKCE Flow**: [OAuth 2.0 PKCE Explained](https://supabase.com/docs/guides/auth/sessions/pkce-flow)
- **Security Sessions**: [Token Security & Refresh](https://supabase.com/docs/guides/auth/sessions)
- **Next.js Docs**: [Server Components](https://nextjs.org/docs/app/building-your-application/rendering/server-components)
- **GitHub Issues**: [Supabase Auth Helpers Archive](https://github.com/supabase/auth-helpers)
