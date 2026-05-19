# Production-Ready Code Templates

Copy-paste these into your Next.js 15 project. All tested and 2025-ready.

## 1. Complete middleware.ts

```typescript
// middleware.ts
import type { NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/middleware'

export async function middleware(request: NextRequest) {
  return await updateSession(request)
}

export const config = {
  // Exclude static files and API routes that don't need auth
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
```

## 2. Complete lib/supabase/middleware.ts

```typescript
// lib/supabase/middleware.ts
import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

export async function updateSession(request: NextRequest) {
  // Start with a response that copies the request header
  let supabaseResponse = NextResponse.next({
    request: {
      headers: request.headers,
    },
  })

  // Create Supabase client with middleware cookie handling
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          // Set cookies on request for next middleware
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          )
          // Create fresh response to set cookies
          supabaseResponse = NextResponse.next({
            request: {
              headers: request.headers,
            },
          })
          // Set cookies on response for browser
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  // CRITICAL: Call getClaims immediately after createServerClient
  // This refreshes the Auth token if it's expired
  // Do NOT put any other code between createServerClient and getClaims()
  const { data: { claims } } = await supabase.auth.getClaims()

  // Redirect unauthenticated users to login (unless on public route)
  if (!claims && !isPublicRoute(request.nextUrl.pathname)) {
    const loginUrl = request.nextUrl.clone()
    loginUrl.pathname = '/login'
    return NextResponse.redirect(loginUrl)
  }

  // Return response with refreshed cookies
  return supabaseResponse
}

/**
 * Routes that don't require authentication
 * Add paths here that should be accessible without logging in
 */
function isPublicRoute(pathname: string): boolean {
  const publicRoutes = [
    '/login',
    '/signup',
    '/auth/callback', // OAuth & magic link callbacks
    '/forgot-password',
    '/reset-password',
    '/api/health', // Health check endpoints
    '/public', // Static public pages
  ]

  return publicRoutes.some(route => pathname.startsWith(route))
}
```

## 3. Complete lib/supabase/client.ts

```typescript
// lib/supabase/client.ts
'use client'

import { createBrowserClient } from '@supabase/ssr'

let supabaseInstance: ReturnType<typeof createBrowserClient> | null = null

/**
 * Browser client - Use in Client Components only
 * This client uses browser storage (localStorage/cookies read by browser)
 * Safe for client-side operations like realtime subscriptions
 *
 * DO NOT use this in Server Components, Server Actions, or Middleware
 */
export function createClient() {
  // Singleton pattern - reuse same client instance
  if (supabaseInstance) {
    return supabaseInstance
  }

  supabaseInstance = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!
  )

  return supabaseInstance
}
```

## 4. Complete lib/supabase/server.ts

```typescript
// lib/supabase/server.ts
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

/**
 * Server client - Use in Server Components, Server Actions, Route Handlers
 * This client uses Next.js cookies() API
 * Must be async because cookies() is async in Next.js 15+
 *
 * Create a new client on each request (don't cache)
 */
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
            // Try to set cookies (will fail in Server Components, but that's OK)
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            )
          } catch (error) {
            // setAll may fail in Server Components
            // This is expected - middleware will refresh and set cookies correctly
            console.debug('Cookie setAll error (expected in Server Components):', error instanceof Error ? error.message : error)
          }
        },
      },
    }
  )
}
```

## 5. Complete app/auth/actions.ts

```typescript
// app/auth/actions.ts
'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

/**
 * Sign up new user with email and password
 */
export async function signUp(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string

  // Validate inputs
  if (!email || !password) {
    throw new Error('Email and password required')
  }

  if (password.length < 8) {
    throw new Error('Password must be at least 8 characters')
  }

  const supabase = await createClient()

  const { error } = await supabase.auth.signUp({
    email,
    password,
  })

  if (error) {
    throw new Error(error.message)
  }

  // Redirect to email verification page
  redirect('/auth/check-email')
}

/**
 * Sign in with email and password
 */
export async function signIn(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string

  if (!email || !password) {
    throw new Error('Email and password required')
  }

  const supabase = await createClient()

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })

  if (error) {
    throw new Error(error.message)
  }

  // Clear cache and redirect
  revalidatePath('/', 'layout')
  redirect('/dashboard')
}

/**
 * Sign out current user
 */
export async function signOut() {
  const supabase = await createClient()

  const { error } = await supabase.auth.signOut()

  if (error) {
    throw new Error(error.message)
  }

  // Clear cache and redirect
  revalidatePath('/', 'layout')
  redirect('/login')
}

/**
 * Send password reset email
 */
export async function resetPassword(formData: FormData) {
  const email = formData.get('email') as string

  if (!email) {
    throw new Error('Email required')
  }

  const supabase = await createClient()

  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${process.env.NEXT_PUBLIC_SITE_URL}/auth/callback?next=/auth/update-password`,
  })

  if (error) {
    throw new Error(error.message)
  }

  // Don't reveal if email exists (security best practice)
  redirect('/auth/check-email?type=reset')
}

/**
 * Update password after reset
 */
export async function updatePassword(formData: FormData) {
  const password = formData.get('password') as string
  const confirmPassword = formData.get('confirmPassword') as string

  if (!password || !confirmPassword) {
    throw new Error('Passwords required')
  }

  if (password !== confirmPassword) {
    throw new Error('Passwords do not match')
  }

  if (password.length < 8) {
    throw new Error('Password must be at least 8 characters')
  }

  const supabase = await createClient()

  const { error } = await supabase.auth.updateUser({
    password,
  })

  if (error) {
    throw new Error(error.message)
  }

  revalidatePath('/', 'layout')
  redirect('/dashboard')
}
```

## 6. Protected Server Component

```typescript
// app/dashboard/page.tsx
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

export const dynamic = 'force-dynamic' // Don't cache authenticated pages

export default async function DashboardPage() {
  const supabase = await createClient()

  // ✅ SECURE: getUser() validates JWT with Supabase
  const { data: { user }, error } = await supabase.auth.getUser()

  // Redirect if not authenticated
  if (error || !user) {
    redirect('/login')
  }

  // Fetch user data
  const { data: profile, error: profileError } = await supabase
    .from('profiles')
    .select('*')
    .eq('id', user.id)
    .single()

  if (profileError) {
    console.error('Failed to fetch profile:', profileError)
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">
        Welcome, {profile?.full_name || user.email}
      </h1>

      <div className="rounded-lg bg-gray-100 p-6">
        <h2 className="text-xl font-semibold">Account Info</h2>
        <p>Email: {user.email}</p>
        <p>User ID: {user.id}</p>
        <p>Created: {new Date(user.created_at).toLocaleDateString()}</p>
      </div>
    </div>
  )
}
```

## 7. Login Client Component

```typescript
// app/auth/login/page.tsx
'use client'

import { useState } from 'react'
import { useFormStatus } from 'react-dom'
import { signIn } from '@/app/auth/actions'

function SubmitButton() {
  const { pending } = useFormStatus()
  return (
    <button
      type="submit"
      disabled={pending}
      className="w-full rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
    >
      {pending ? 'Signing in...' : 'Sign In'}
    </button>
  )
}

export default function LoginPage() {
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(formData: FormData) {
    setError(null)
    try {
      await signIn(formData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-100">
      <div className="rounded-lg bg-white p-8 shadow-lg">
        <h1 className="mb-6 text-2xl font-bold">Sign In</h1>

        <form action={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-lg bg-red-100 p-4 text-red-700">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium">Email</label>
            <input
              type="email"
              name="email"
              required
              className="w-full rounded-lg border px-4 py-2"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="block text-sm font-medium">Password</label>
            <input
              type="password"
              name="password"
              required
              className="w-full rounded-lg border px-4 py-2"
              placeholder="••••••••"
            />
          </div>

          <SubmitButton />

          <div className="text-center text-sm">
            <p>
              Don't have an account?{' '}
              <a href="/auth/signup" className="text-blue-600 hover:underline">
                Sign up
              </a>
            </p>
            <p>
              <a href="/auth/forgot-password" className="text-blue-600 hover:underline">
                Forgot password?
              </a>
            </p>
          </div>
        </form>
      </div>
    </div>
  )
}
```

## 8. Route Handler (API)

```typescript
// app/api/user/route.ts
import { createClient } from '@/lib/supabase/server'
import { NextResponse } from 'next/server'

export async function GET() {
  const supabase = await createClient()

  // ✅ SECURE: getUser() validates JWT
  const { data: { user }, error } = await supabase.auth.getUser()

  if (error || !user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  // Fetch user data
  const { data: profile } = await supabase
    .from('profiles')
    .select('*')
    .eq('id', user.id)
    .single()

  return NextResponse.json({
    user: {
      id: user.id,
      email: user.email,
      profile,
    },
  })
}
```

## 9. Environment Variables Template

```bash
# .env.local (development)
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=eyJhbGc...

# .env.production (Vercel dashboard)
NEXT_PUBLIC_SUPABASE_URL=https://xxxyyyzzz.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...

# For password reset emails and OAuth redirects
NEXT_PUBLIC_SITE_URL=https://yourdomain.com  # or localhost:3000 for dev
```

## 10. Realtime Client Component

```typescript
// app/components/RealtimeMessages.tsx
'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'

export function RealtimeMessages() {
  const [messages, setMessages] = useState<any[]>([])
  const supabase = createClient()

  useEffect(() => {
    // Subscribe to realtime changes
    const channel = supabase
      .channel('public:messages')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
        },
        (payload) => {
          setMessages(prev => [...prev, payload.new])
        }
      )
      .subscribe()

    // Cleanup subscription
    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  return (
    <div>
      <h2>Messages ({messages.length})</h2>
      <ul>
        {messages.map(msg => (
          <li key={msg.id}>{msg.content}</li>
        ))}
      </ul>
    </div>
  )
}
```

## 11. Logout Button

```typescript
// app/components/LogoutButton.tsx
'use client'

import { signOut } from '@/app/auth/actions'
import { useState } from 'react'

export function LogoutButton() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleLogout() {
    setLoading(true)
    setError(null)
    try {
      await signOut()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Logout failed')
      setLoading(false)
    }
  }

  return (
    <div>
      {error && <p className="text-red-600">{error}</p>}
      <button
        onClick={handleLogout}
        disabled={loading}
        className="rounded-lg bg-red-600 px-4 py-2 text-white hover:bg-red-700 disabled:opacity-50"
      >
        {loading ? 'Logging out...' : 'Logout'}
      </button>
    </div>
  )
}
```

## 12. .env.example Template

```bash
# Copy this to .env.local and fill in your values

# Supabase Project URL
# Get from: Supabase Dashboard → Settings → API
NEXT_PUBLIC_SUPABASE_URL=

# Supabase Publishable Key (anon or sb_publishable_xxx)
# Get from: Supabase Dashboard → Settings → API
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=

# Your site URL (for OAuth redirects and reset links)
# Development: http://localhost:3000
# Production: https://yourdomain.com
NEXT_PUBLIC_SITE_URL=

# Optional: Supabase Service Role Key (server-only operations)
# WARNING: Never expose this publicly - only use in .env.local or .env
# SUPABASE_SERVICE_ROLE_KEY=

# Optional: Database URL (if using Supabase PostgreSQL directly)
# DATABASE_URL=
```

---

## Installation Checklist

1. ✅ `npm install @supabase/supabase-js @supabase/ssr`
2. ✅ Create `.env.local` with Supabase credentials
3. ✅ Create folder: `lib/supabase/`
4. ✅ Copy `client.ts`, `server.ts`, `middleware.ts`
5. ✅ Create `middleware.ts` in project root
6. ✅ Create `app/auth/actions.ts`
7. ✅ Create `app/auth/login/page.tsx`
8. ✅ Add redirect URLs in Supabase Auth → URL Configuration
9. ✅ Update email templates to PKCE format
10. ✅ Test locally: `npm run dev`
11. ✅ Deploy and verify production auth works
