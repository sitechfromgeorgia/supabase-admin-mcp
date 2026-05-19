---
name: supabase-edge-functions-serverless-master
description: Developing, testing, and deploying high-performance serverless Edge Functions using Deno and Supabase. Covers setup, CORS handling, connecting to third-party APIs (Stripe, OpenAI), webhook processing, and database interactions.
---

# Supabase Edge Functions (Deno)

## Metadata
- **Name:** Supabase Edge Functions Master
- **Category:** Backend / Serverless
- **Priority:** P1 (Essential for integrations)
- **Domain:** Deno, TypeScript, Webhooks, API Integrations
- **Owner Role:** Backend Engineer
- **Complexity:** Medium to High

## Mission
Extend the database's capabilities by running serverless TypeScript functions at the Edge (globally distributed). Use Edge Functions for:
1.  **Webhooks** (Stripe, Telegram, slack)
2.  **3rd Party APIs** (OpenAI, Resend)
3.  **Complex Business Logic** that is too heavy for SQL functions.

## Core Directives
1.  **One Function = One Responsibility**: Don't build a monolith. `stripe-webhook`, `send-email`, `generate-embedding`.
2.  **Security First**: Verify signatures (webhooks) or JWTs (client calls). use `service_role` key sparingly inside the function.
3.  **Environment Variables**: Never hardcode secrets. Use `Deno.env.get()`.
4.  **Error Handling**: Always return structured JSON errors with appropriate HTTP status codes (4xx client, 5xx server).

## Implementation Guide

### 1. Setup & Boilerplate

**Create Function**
```bash
supabase functions new my-function
```

**Standard Handler Structure (index.ts)**
```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { corsHeaders } from "../_shared/cors.ts"; // Create a shared CORS helper

serve(async (req) => {
  // 1. Handle CORS Preflight
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  try {
    // 2. Main Logic
    const { name } = await req.json();
    
    // ... Perform task ...
    
    // 3. Success Response
    return new Response(JSON.stringify({ message: `Hello ${name}` }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      status: 200,
    });

  } catch (error) {
    // 4. Error Response
    return new Response(JSON.stringify({ error: error.message }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      status: 400,
    });
  }
});
```

### 2. Calling from Client (Next.js)

```typescript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(URL, KEY);

const { data, error } = await supabase.functions.invoke('my-function', {
  body: { name: 'World' },
});
```

### 3. Integrating 3rd Party APIs (e.g., Stripe Webhook)

**Key Challenge**: Verifying the raw body signature.

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import Stripe from 'https://esm.sh/stripe@12.0.0?target=deno';

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY') ?? '', {
  httpClient: Stripe.createFetchHttpClient(),
});

// Crypto provider for signature verification
const cryptoProvider = Stripe.createSubtleCryptoProvider();

serve(async (req) => {
  const signature = req.headers.get('Stripe-Signature');
  
  // Important: Get body as text for verification, NOT json()
  const body = await req.text();

  try {
    const event = await stripe.webhooks.constructEventAsync(
      body,
      signature!,
      Deno.env.get('STRIPE_WEBHOOK_SECRET') ?? '',
      undefined,
      cryptoProvider
    );

    // Handle Event
    if (event.type === 'checkout.session.completed') {
       // ... Update Database ...
    }

    return new Response(JSON.stringify({ received: true }), { status: 200 });
  } catch (err) {
    return new Response(`Webhook Error: ${err.message}`, { status: 400 });
  }
});
```

### 4. Database Access (Service Role)
Sometimes you need to bypass RLS (e.g., inside a webhook).

```typescript
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const supabaseAdmin = createClient(
  Deno.env.get('SUPABASE_URL') ?? '',
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
);

// This insert bypasses RLS
await supabaseAdmin.from('audit_logs').insert({ event: 'function_triggered' });
```

## Checklist before Deploy
- [ ] Secrets added via `supabase secrets set`?
- [ ] CORS headers included for browser calls?
- [ ] `import_map.json` used for dependencies?
- [ ] Tested locally with `supabase functions serve`?
