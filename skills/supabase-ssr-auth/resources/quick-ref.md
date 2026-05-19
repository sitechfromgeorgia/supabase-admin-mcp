# Quick Reference Card - Supabase SSR Authentication

## 🎯 One-Page Cheat Sheet

### Installation
```bash
npm install @supabase/supabase-js @supabase/ssr
npm uninstall @supabase/auth-helpers-nextjs
```

### Environment Variables
```env
NEXT_PUBLIC_SUPABASE_URL=https://xxxyyyzzz.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxx
NEXT_PUBLIC_SITE_URL=https://yourdomain.com
```

### Project Structure
```
middleware.ts                    ← Intercepts ALL requests, refreshes tokens
├── lib/supabase/
│   ├── client.ts              ← Browser client (Client Components only)
│   ├── server.ts              ← Server client (Server Components, Actions)
│   └── middleware.ts          ← Token refresh logic
├── app/auth/
│   └── actions.ts             ← Server Actions: login, signup, logout
└── app/dashboard/
    └── page.tsx               ← Protected page using getUser()
```

---

## 💻 Essential Code

### Protect a Page
```typescript
// app/dashboard/page.tsx
const { data: { user } } = await supabase.auth.getUser()
if (!user) redirect('/login')
```

### Login Form
```typescript
// Use Server Action from templates
<form action={signIn}>
  <input type="email" name="email" />
  <input type="password" name="password" />
  <button type="submit">Sign In</button>
</form>
```

### API Endpoint
```typescript
// app/api/user/route.ts
const { data: { user } } = await supabase.auth.getUser()
if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 })
```

---

## 🔐 Security Rules (Memorize These)

| Rule | Why |
|------|-----|
| **Use getUser() for auth** | Validates JWT with Supabase, can't be spoofed |
| **Never getSession() on server** | Trusts unvalidated cookie |
| **getClaims() immediately** | Refreshes token, no other code first |
| **httpOnly cookies** | JavaScript can't access (prevents XSS) |
| **PKCE flow required** | Code useless without verifier |
| **Public routes whitelist** | Avoid infinite redirect loops |

---

## 🐛 Debugging Checklist

**"Auth session missing" in production?**
```
✓ NEXT_PUBLIC_SUPABASE_URL = https://...
✓ .env variables set in deployment
✓ Redirect URLs in Supabase Auth → URL Configuration
✓ middleware.ts matcher excludes static files
✓ middleware.ts calls getClaims() FIRST
✓ Protected pages use getUser()
✓ Email templates use {{ .TokenHash }}
```

**Token loops ("Already Used")?**
```
✓ getClaims() called ONLY ONCE in middleware
✓ No async code between createServerClient and getClaims()
```

**Infinite redirects?**
```
✓ isPublicRoute() includes /login, /signup, /auth/callback
✓ Redirect logic checks isPublicRoute() before redirecting
```

---

## 📊 Comparison Table

| Method | Where | Validates | Use For |
|--------|-------|-----------|---------|
| `getUser()` | Server | ✅ JWT signature | Authorization |
| `getSession()` | Server | ❌ No | ❌ NEVER |
| `getUser()` | Client | ✅ HTTP request | Critical auth |
| `getSession()` | Client | ✓ Safe | Quick checks |

---

## ⏱️ Token Lifecycle

```
1. Login: User enters password
   ↓
2. Supabase returns: access_token, refresh_token
   ↓
3. Browser: Cookies set
   ↓
4. Next request: Middleware calls getClaims()
   ↓
5. If expired: Refresh token swapped for new access token
   ↓
6. Response: Updated cookies sent
   ↓
7. Server Component: Renders with fresh session
```

---

## 🚀 5-Minute Setup

```bash
# 1. Install
npm install @supabase/supabase-js @supabase/ssr

# 2. Create .env.local
NEXT_PUBLIC_SUPABASE_URL=...

# 3. Copy middleware.ts (to root)
# 4. Copy lib/supabase/*.ts files
# 5. Copy app/auth/actions.ts
# 6. Copy app/auth/login/page.tsx

# 7. Test
npm run dev
```

---

## 📖 File Navigation

| Need | File | Section |
|------|------|---------|
| Full guide | supabase-ssr-nextjs-15-auth.md | All |
| Code templates | production-templates.md | All |
| Quick ref | quick-reference.md | All |

---

## ✅ Production Checklist

- [ ] Environment variables in deployment
- [ ] NEXT_PUBLIC_SUPABASE_URL uses https://
- [ ] Redirect URLs in Supabase Auth
- [ ] Email templates use {{ .TokenHash }}
- [ ] Middleware matcher excludes static files
- [ ] All protected pages use getUser()
- [ ] revalidatePath() after auth changes
- [ ] Test: Login → refresh → session persists

---

## 🎓 Critical Concepts

**Middleware**: Intercept requests → getClaims() → refresh token if needed → set cookies

**getUser() Security**: Calls Supabase API → validates JWT → cannot be spoofed

**PKCE Flow**: Browser has code_verifier → code only in browser → cannot intercept

**Token Refresh**: Happens in middleware → prevents random logouts

**httpOnly**: JavaScript cannot read → prevents XSS theft
