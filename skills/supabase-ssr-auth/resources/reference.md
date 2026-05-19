# Implementation Reference & Deep Dive

## Token Refresh Flow Diagram (Text)

```
┌─────────────────────────────────────────────────────────────────┐
│                    BROWSER LAYER                                │
│  User navigates to /dashboard                                   │
│  Request includes: Cookie: sb-access-token=...                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MIDDLEWARE LAYER                              │
│                 middleware.ts runs                              │
│                                                                 │
│  1. updateSession(request) called                              │
│  2. createServerClient() initialized with request.cookies      │
│  3. ⚠️  CRITICAL: await supabase.auth.getClaims()              │
│     ├─ Validates JWT signature                                 │
│     ├─ If expired: uses refresh token to get new access token │
│     └─ Sets updated cookie in request object                  │
│  4. Return supabaseResponse with updated response.cookies      │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────▼──────────────┐
          │  Token Status?              │
          └──────────┬─────────┬────────┘
                     │         │
        ┌────────────▼──┐  ┌───▼──────────────┐
        │  Valid        │  │  Needs Refresh   │
        │  (< 5 min)    │  │  (> 5 min expiry)│
        │  Return as-is │  │  Exchange refresh│
        └────────────────┘  │  Get new access  │
                            └─────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SERVER COMPONENT LAYER                           │
│           Page renders in Server Component                      │
│                                                                 │
│  const { data: { user } } = await supabase.auth.getUser()     │
│  ✅ Uses validated session from middleware                      │
│  No additional refresh needed                                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  RESPONSE TO BROWSER                             │
│  Set-Cookie: sb-access-token=<new-token>;                      │
│              HttpOnly; Secure; SameSite=Lax                     │
│                                                                 │
│  HTML response with dashboard content                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Security Guarantees

### 1. getUser() vs getSession() - When to Use

**getUser() - ALWAYS on Server**
```typescript
// ✅ SECURE - Makes HTTP request to Supabase Auth API
const { data: { user } } = await supabase.auth.getUser()

// Validates:
// - JWT signature against Supabase's public keys
// - Token not revoked
// - Session not expired

// Result: Trustworthy for authorization decisions
if (!user) {
  throw new Error('Unauthorized')
}
```

**getSession() - Client-Only**
```typescript
// ❌ INSECURE ON SERVER - Never use in middleware/server code
const { data: { session } } = await supabase.auth.getSession()

// On client (browser):
// ✅ Safe - getSession() is fine
// On server (middleware, server actions):
// ❌ Dangerous - Trusts unvalidated cookie

// Why? Cookies can be modified in browser dev tools
```

### 2. PKCE Flow Security

**How PKCE Protects Auth Code**:
```
1. Browser initiates: window.location = oauth.google.com?client_id=...&code_challenge=...
2. User authorizes on Google
3. Google redirects: yoursite.com/callback?code=abc123def456
4. On same browser/device, exchange:
   POST auth.service/token {
     code: "abc123def456",
     code_verifier: "...",  ← Only browser has this
     client_id: "..."
   }
5. Server returns: { access_token: "...", refresh_token: "..." }
```

**Why It Matters**:
- Code is useless without code_verifier (only original browser has it)
- Code expires in 5 minutes
- Cannot exchange code from different device
- Prevents code interception attacks

### 3. Cookie Security in Production

**Automatic Configuration by @supabase/ssr**:
```typescript
// What @supabase/ssr sets automatically (you don't need to configure):

{
  httpOnly: true,      // ✅ JavaScript cannot access (prevents XSS theft)
  secure: true,        // ✅ HTTPS only (prevents man-in-the-middle)
  sameSite: 'lax',     // ✅ CSRF protection (cross-site requests blocked)
  domain: '.yourdomain.com',  // ✅ Only sent to your domain
  path: '/',
  maxAge: 86400 * 7    // 7 days for refresh token
}
```

**What This Prevents**:
- ❌ XSS: JavaScript (including malicious scripts) cannot read the token
- ❌ CSRF: Cannot be sent from other domains (e.g., evil.com)
- ❌ MITM: HTTPS-only prevents interception
- ❌ Session fixation: SameSite=lax blocks cross-site cookie setting

---

## Production Deployment Checklist

- [ ] Remove `@supabase/auth-helpers-nextjs` completely
- [ ] Environment variables set in deployment platform (Vercel, etc.)
- [ ] NEXT_PUBLIC_SUPABASE_URL uses `https://`
- [ ] Redirect URLs added to Supabase Auth → URL Configuration
- [ ] Email templates updated to PKCE format ({{ .TokenHash }})
- [ ] middleware.ts has correct matcher (excludes static files)
- [ ] Middleware calls getClaims() immediately after createServerClient
- [ ] Server Components use getUser() for authorization
- [ ] All Server Actions use await createClient()
- [ ] Testing: Login → refresh page → verify session persists
- [ ] Testing: Let token expire → refresh page → should auto-refresh
- [ ] Testing: Logout → navigate → should redirect to /login

---

## Common Implementation Mistakes

### ❌ Mistake 1: Using getSession() for Authorization

```typescript
// WRONG - On server
const { data: { session } } = await supabase.auth.getSession()
if (session?.user?.id) {  // Trusts unvalidated cookie!
  // User appears authenticated
}
```

**Why It's Wrong**: Attacker can open DevTools, modify cookie, fake authentication.

**Fix**:
```typescript
// CORRECT
const { data: { user }, error } = await supabase.auth.getUser()
if (error || !user) {
  redirect('/login')
}
// Now you know user is real (Supabase validated it)
```

### ❌ Mistake 2: Wrong Email Template Format

```html
<!-- WRONG - Implicit flow (deprecated) -->
<a href="{{ .ConfirmationURL }}">Confirm Email</a>

<!-- CORRECT - PKCE flow (for SSR) -->
<a href="{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=email_signup">
  Confirm Email
</a>
```

**Why It's Wrong**: Confirmation links don't work because they expect `token_hash`, not `ConfirmationURL`.

### ❌ Mistake 3: Code Between createServerClient and getClaims()

```typescript
// ❌ WRONG
const supabase = createServerClient(...)
console.log('About to get claims')  // Don't do this!
const result = someOtherFunction()  // Definitely don't do this!
await supabase.auth.getClaims()     // Too late for guarantee
```

**Why It's Wrong**: Any async code between these allows race conditions where multiple requests try to refresh simultaneously.

**Fix**:
```typescript
// ✅ CORRECT
const supabase = createServerClient(...)
// Immediately call getClaims - no other code
const { data: { claims } } = await supabase.auth.getClaims()
// Now safe to do other things
```

### ❌ Mistake 4: Mixing auth-helpers and @supabase/ssr

```bash
# ❌ WRONG
npm install @supabase/auth-helpers-nextjs @supabase/ssr

# This causes:
# - Conflicting cookie handling
# - "Invalid Refresh Token: Already Used" errors
# - Random logouts
# - Production failures

# ✅ CORRECT
npm uninstall @supabase/auth-helpers-nextjs
npm install @supabase/ssr
```

---

## Debugging Checklist

### "Auth session missing!" in Production

1. **Verify HTTPS**
   ```bash
   # ✅ Production Vercel URL
   NEXT_PUBLIC_SUPABASE_URL=https://xxxyyyzzz.supabase.co
   
   # ❌ Wrong - localhost in production
   NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321
   ```

2. **Verify Redirect URLs**
   ```
   Supabase Dashboard → Auth → URL Configuration
   Add:
   - https://yourdomain.com/auth/callback
   - https://yourdomain.com/auth/callback/  (with trailing slash)
   - https://www.yourdomain.com/auth/callback
   ```

3. **Verify Middleware Matcher**
   ```typescript
   // middleware.ts
   export const config = {
     matcher: [
       // MUST exclude static files
       '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
     ],
   }
   
   // ❌ If matcher is wrong, middleware never runs, tokens never refresh
   ```

4. **Check Middleware getClaims()**
   ```typescript
   // Add temporary logging
   const { data: { claims } } = await supabase.auth.getClaims()
   console.log('Claims:', claims)  // Should have user ID if authenticated
   ```

5. **Test Cookie Setting**
   ```typescript
   // In middleware response
   supabaseResponse.cookies.setAll(supabaseResponse.cookies.getAll())
   
   // Open DevTools → Application → Cookies → yourdomain.com
   // Should see: sb-access-token, sb-refresh-token
   ```

---

## Performance Optimization

### Minimize Token Refresh Calls

**Default Behavior**: getClaims() is called on EVERY request via middleware.

**Optimization**: Only refresh when needed
```typescript
// Optional: Skip refresh for static routes
function shouldRefreshAuth(pathname: string): boolean {
  const refreshable = ['/api', '/dashboard', '/profile']
  return refreshable.some(path => pathname.startsWith(path))
}

// In middleware:
if (!shouldRefreshAuth(request.nextUrl.pathname)) {
  return supabaseResponse  // Skip refresh for static pages
}

await supabase.auth.getClaims()
```

**Note**: Supabase optimizes this internally (doesn't actually refresh if token is < 5 min from expiry).

---

## Best Practices Summary

1. **Cookie Security Configuration** - Works automatically
2. **Always Call getClaims() Immediately** - No other code first
3. **Use getUser() for Authorization** - Never getSession() on server
4. **Revalidate Cache After Auth Changes** - Use revalidatePath()
5. **Public Routes Whitelist** - Avoid redirect loops

---

## Testing

### Unit Test: getUser() Authorization

```typescript
// __tests__/auth.test.ts
import { createClient } from '@/lib/supabase/server'

jest.mock('@/lib/supabase/server', () => ({
  createClient: jest.fn(),
}))

it('should redirect unauthenticated users', async () => {
  const mockSupabase = {
    auth: {
      getUser: jest.fn().mockResolvedValue({
        data: { user: null },
        error: null,
      }),
    },
  }

  ;(createClient as jest.Mock).mockResolvedValue(mockSupabase)

  // Your component should redirect
  expect(redirect).toHaveBeenCalledWith('/login')
})
```

---

## Key Takeaways

✅ **Middleware**: Intercepts every request, refreshes tokens before Server Components render
✅ **getUser()**: The only secure way to check authentication on the server
✅ **PKCE**: Required for SSR, prevents OAuth code interception
✅ **Cookies**: Automatically configured to be secure (httpOnly, Secure, SameSite)
✅ **Token Refresh**: Happens automatically in middleware, prevents random logouts

---

**This is the foundation for bulletproof Supabase authentication in Next.js 15.**
