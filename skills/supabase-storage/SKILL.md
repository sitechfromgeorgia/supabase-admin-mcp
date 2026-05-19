---
name: supabase-storage-nextjs-masterclass
description: Implements production-grade file storage in Next.js 15 apps using Supabase Storage with RLS policies, resumable uploads (TUS), Image Transformations, and CDN caching strategies. Use when building secure file upload systems, user avatars, galleries, or handling large files with offline-resilience.
---

# Supabase Storage Masterclass with Next.js 15

## Quick Start

### 1. Install Dependencies

```bash
npm install @supabase/supabase-js tus-js-client
```

### 2. Create Supabase Client

**`src/lib/supabase.ts`** (shared client)
```typescript
import { createClient } from '@supabase/supabase-js';

const projectId = process.env.NEXT_PUBLIC_SUPABASE_PROJECT_ID!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(
  `https://${projectId}.supabase.co`,
  anonKey
);
```

**`src/lib/supabase-server.ts`** (server-only, for RLS bypass if needed)
```typescript
import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';

export async function createServerClient() {
  const cookieStore = await cookies();
  return createClient(
    `https://${process.env.NEXT_PUBLIC_SUPABASE_PROJECT_ID}.supabase.co`,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        persistSession: false,
      },
    }
  );
}
```

### 3. Set Up Bucket with RLS

```sql
-- Create bucket (private)
INSERT INTO storage.buckets (id, name, public)
VALUES ('user-uploads', 'user-uploads', false)
ON CONFLICT (id) DO NOTHING;

-- Enable RLS
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- Policy: Users can upload to their own folder
CREATE POLICY "Users can upload to own folder"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'user-uploads'
  AND (storage.foldername(name))[1] = (auth.uid())::text
);

-- Policy: Users can read their own files
CREATE POLICY "Users can read own files"
ON storage.objects
FOR SELECT
TO authenticated
USING (
  bucket_id = 'user-uploads'
  AND (storage.foldername(name))[1] = (auth.uid())::text
);

-- Policy: Users can delete their own files
CREATE POLICY "Users can delete own files"
ON storage.objects
FOR DELETE
TO authenticated
USING (
  bucket_id = 'user-uploads'
  AND (storage.foldername(name))[1] = (auth.uid())::text
);

-- Policy: Users can update their own files (for upsert)
CREATE POLICY "Users can update own files"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
  bucket_id = 'user-uploads'
  AND (storage.foldername(name))[1] = (auth.uid())::text
);
```

---

## Architecture & Security

### Storage Folder Structure

Always organize uploads by user ID for clean RLS policies:

```
user-uploads/
├── {user-id}/
│   ├── avatars/
│   │   └── avatar.jpg
│   ├── documents/
│   │   └── resume.pdf
│   └── gallery/
│       └── photo-123.jpg
```

The `storage.foldername(name)` function extracts the first path segment, which RLS policies use to verify ownership.

### Private vs Public Buckets

| Aspect | Private Bucket | Public Bucket |
|--------|---|---|
| **RLS Required** | Yes (default) | Yes (still required!) |
| **Access** | Signed URLs only | Public URLs + Signed URLs |
| **Use Case** | Sensitive files, user uploads | Static assets, avatars |
| **Performance** | Slightly slower (auth check) | Faster (no auth overhead) |
| **Security** | Better by default | Requires explicit policies |

**Recommendation:** Use private buckets by default. Generate signed URLs for temporary access.

### MIME Type Validation

**Always validate on both client and server:**

```typescript
// src/lib/validation.ts
const ALLOWED_TYPES = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'application/pdf': 'pdf',
};

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

export function validateFile(file: File): { valid: boolean; error?: string } {
  if (!ALLOWED_TYPES[file.type as keyof typeof ALLOWED_TYPES]) {
    return { valid: false, error: 'Invalid file type' };
  }
  if (file.size > MAX_FILE_SIZE) {
    return { valid: false, error: 'File too large (max 50MB)' };
  }
  return { valid: true };
}
```

**Server Action for Server-Side Validation:**

```typescript
// src/app/actions/upload.ts
'use server';

import { z } from 'zod';

const uploadSchema = z.object({
  file: z
    .instanceof(File)
    .refine((f) => f.size <= 50 * 1024 * 1024, 'File too large')
    .refine(
      (f) => ['image/jpeg', 'image/png', 'application/pdf'].includes(f.type),
      'Invalid file type'
    ),
  userId: z.string().uuid(),
});

export async function uploadFile(formData: FormData) {
  const file = formData.get('file') as File;
  const userId = formData.get('userId') as string;

  const validation = uploadSchema.safeParse({ file, userId });
  if (!validation.success) {
    return { error: validation.error.errors[0].message };
  }

  // Validation passed - proceed with upload
}
```

---

## Upload Patterns

### Pattern 1: Standard Client Upload (Small Files <6MB)

```typescript
// src/app/components/upload-simple.tsx
'use client';

import { supabase } from '@/lib/supabase';
import { useCallback, useState } from 'react';

export function SimpleUpload({ userId }: { userId: string }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setUploading(true);
      setError(null);

      try {
        const filePath = `${userId}/avatars/${Date.now()}_${file.name}`;

        const { error: uploadError } = await supabase.storage
          .from('user-uploads')
          .upload(filePath, file, {
            cacheControl: '3600',
            upsert: false,
          });

        if (uploadError) throw uploadError;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed');
      } finally {
        setUploading(false);
      }
    },
    [userId]
  );

  return (
    <div>
      <input type="file" onChange={handleUpload} disabled={uploading} />
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {uploading && <p>Uploading...</p>}
    </div>
  );
}
```

### Pattern 2: Resumable Upload (Large Files >6MB, Unreliable Networks)

```typescript
// src/app/components/upload-resumable.tsx
'use client';

import * as tus from 'tus-js-client';
import { useCallback, useState } from 'react';
import { supabase } from '@/lib/supabase';

export function ResumableUpload({ userId }: { userId: string }) {
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setUploading(true);
      setError(null);

      try {
        const { data: session } = await supabase.auth.getSession();
        if (!session?.session) throw new Error('Not authenticated');

        const filePath = `${userId}/documents/${Date.now()}_${file.name}`;
        const projectId = process.env.NEXT_PUBLIC_SUPABASE_PROJECT_ID;

        return new Promise((resolve, reject) => {
          const upload = new tus.Upload(file, {
            endpoint: `https://${projectId}.storage.supabase.co/storage/v1/upload/resumable`,
            retryDelays: [0, 3000, 5000, 10000, 20000],
            headers: {
              authorization: `Bearer ${session.session.access_token}`,
              'x-upsert': 'true',
            },
            uploadDataDuringCreation: true,
            removeFingerprintOnSuccess: true,
            metadata: {
              bucketName: 'user-uploads',
              objectName: filePath,
              contentType: file.type,
              cacheControl: '3600',
            },
            chunkSize: 6 * 1024 * 1024, // 6MB chunks
            onError(error) {
              setError(error.message);
              reject(error);
            },
            onProgress(bytesUploaded, bytesTotal) {
              const percentage = Math.round((bytesUploaded / bytesTotal) * 100);
              setProgress(percentage);
            },
            onSuccess() {
              setProgress(100);
              setUploading(false);
              resolve({ path: filePath });
            },
          });

          // Resume previous upload if exists
          upload.findPreviousUploads().then((previousUploads) => {
            if (previousUploads.length) {
              upload.resumeFromPreviousUpload(previousUploads[0]);
            }
            upload.start();
          });
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed');
        setUploading(false);
      }
    },
    [userId]
  );

  return (
    <div>
      <input
        type="file"
        onChange={handleUpload}
        disabled={uploading}
        accept="application/pdf,image/*"
      />
      {uploading && (
        <div>
          <progress value={progress} max={100} />
          <p>{progress}%</p>
        </div>
      )}
      {error && <p style={{ color: 'red' }}>{error}</p>}
    </div>
  );
}
```

### Pattern 3: Server-Side Upload (FormData in Server Action)

```typescript
// src/app/actions/upload-server.ts
'use server';

import { createServerClient } from '@/lib/supabase-server';
import { revalidatePath } from 'next/cache';

export async function uploadProfilePicture(formData: FormData) {
  try {
    const file = formData.get('file') as File;
    const userId = formData.get('userId') as string;

    if (!file || !userId) {
      return { error: 'Missing file or userId' };
    }

    // Server-side validation
    if (file.size > 5 * 1024 * 1024) {
      return { error: 'File too large' };
    }

    if (!file.type.startsWith('image/')) {
      return { error: 'Must be an image' };
    }

    const supabase = await createServerClient();
    const buffer = await file.arrayBuffer();

    // Upload to storage
    const { data, error: uploadError } = await supabase.storage
      .from('user-uploads')
      .upload(`${userId}/avatars/profile.jpg`, buffer, {
        contentType: file.type,
        cacheControl: '3600',
        upsert: true,
      });

    if (uploadError) throw uploadError;

    // Revalidate user profile cache
    revalidatePath('/profile');

    return { success: true, path: data.path };
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Upload failed' };
  }
}
```

---

## Next.js 15 Integration

### Next.js Image Loader with Supabase Transformations

**`src/lib/supabase-image-loader.ts`** (production-ready)

```typescript
import { ImageLoaderProps } from 'next/image';

const projectId = process.env.NEXT_PUBLIC_SUPABASE_PROJECT_ID;
const baseUrl = `https://${projectId}.supabase.co/storage/v1/render/image/public`;

/**
 * Custom Next.js image loader for Supabase Storage
 * Automatically applies image transformations and optimization
 */
export function supabaseLoader({
  src,
  width,
  quality,
}: ImageLoaderProps): string {
  // Handle signed URLs (private bucket)
  if (src.includes('?token=')) {
    const [urlPart, tokenPart] = src.split('?token=');
    return `${urlPart}?width=${width}&quality=${quality || 75}&token=${tokenPart}`;
  }

  // Handle public bucket URLs
  return `${baseUrl}/${src}?width=${width}&quality=${quality || 75}`;
}
```

**`next.config.ts`**

```typescript
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  images: {
    loader: 'custom',
    loaderFile: './src/lib/supabase-image-loader.ts',
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '*.supabase.co',
        pathname: '/storage/**',
      },
    ],
  },
};

export default nextConfig;
```

### Usage in Components

```typescript
// src/app/components/profile-avatar.tsx
import Image from 'next/image';

export function ProfileAvatar({ userId }: { userId: string }) {
  return (
    <Image
      src={`user-uploads/${userId}/avatars/profile.jpg`}
      alt="Profile"
      width={200}
      height={200}
      priority
    />
  );
}
```

### Optimistic UI with useActionState (React 19)

```typescript
// src/app/components/avatar-uploader.tsx
'use client';

import { uploadProfilePicture } from '@/app/actions/upload-server';
import { useActionState, useRef, useState } from 'react';
import Image from 'next/image';

export function AvatarUploader({ userId }: { userId: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [optimisticImageUrl, setOptimisticImageUrl] = useState<string | null>(null);
  const [state, formAction, isPending] = useActionState(
    async (prevState, formData: FormData) => {
      // Show optimistic image immediately
      const file = formData.get('file') as File;
      if (file) {
        const objectUrl = URL.createObjectURL(file);
        setOptimisticImageUrl(objectUrl);
      }

      const result = await uploadProfilePicture(formData);
      if (!result.error) {
        // Clear optimistic state on success
        setOptimisticImageUrl(null);
      }
      return result;
    },
    { success: false, error: null, path: null }
  );

  return (
    <form action={formAction}>
      <input type="hidden" name="userId" value={userId} />

      <div>
        {optimisticImageUrl ? (
          <Image
            src={optimisticImageUrl}
            alt="Profile (uploading...)"
            width={200}
            height={200}
            className="opacity-50"
          />
        ) : (
          <Image
            src={`user-uploads/${userId}/avatars/profile.jpg`}
            alt="Profile"
            width={200}
            height={200}
          />
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        name="file"
        accept="image/*"
        disabled={isPending}
        onChange={(e) => {
          if (e.target.files?.[0]) {
            // Auto-submit on file select
            const form = e.currentTarget.form;
            form?.requestSubmit();
          }
        }}
      />

      {isPending && <p>Uploading...</p>}
      {state.error && <p style={{ color: 'red' }}>{state.error}</p>}
      {state.success && <p style={{ color: 'green' }}>Avatar updated!</p>}
    </form>
  );
}
```

---

## Advanced: CDN Cache Invalidation

### Problem: Stale Images After Avatar Update

When users replace their avatar, the CDN still serves the old image for up to 60 seconds.

### Solution 1: Version Query Parameter

```typescript
// src/lib/avatar-url.ts
export function getAvatarUrl(userId: string, version: number): string {
  return `user-uploads/${userId}/avatars/profile.jpg?v=${version}`;
}
```

**Usage:**

```typescript
'use client';

import { useState } from 'react';
import Image from 'next/image';
import { getAvatarUrl } from '@/lib/avatar-url';

export function VersionedAvatar({ userId }: { userId: string }) {
  const [version, setVersion] = useState(1);

  const handleAvatarUpdate = async () => {
    // After successful upload, increment version
    setVersion((v) => v + 1);
  };

  return (
    <Image
      src={getAvatarUrl(userId, version)}
      alt="Profile"
      width={200}
      height={200}
      key={version} // Force re-render
    />
  );
}
```

### Solution 2: Timestamp-Based Path (Recommended)

```typescript
// src/app/actions/upload-server.ts
export async function uploadProfilePicture(formData: FormData) {
  // ... validation code ...

  const timestamp = Date.now();
  const filePath = `${userId}/avatars/profile_${timestamp}.jpg`;

  const { data, error } = await supabase.storage
    .from('user-uploads')
    .upload(filePath, buffer, {
      cacheControl: '31536000', // 1 year - since path is unique
      upsert: false,
    });

  // Clean up old avatars (optional)
  await cleanupOldAvatars(userId);

  return { success: true, path: filePath };
}

async function cleanupOldAvatars(userId: string) {
  const supabase = await createServerClient();
  const { data: files } = await supabase.storage
    .from('user-uploads')
    .list(`${userId}/avatars`);

  if (!files) return;

  // Delete all but the 3 most recent
  const sorted = files
    .filter((f) => f.name.startsWith('profile_'))
    .sort((a, b) => (b.metadata?.created_at || 0) - (a.metadata?.created_at || 0));

  const toDelete = sorted.slice(3);
  if (toDelete.length > 0) {
    await supabase.storage
      .from('user-uploads')
      .remove(toDelete.map((f) => `${userId}/avatars/${f.name}`));
  }
}
```

### Solution 3: Next.js revalidateTag

```typescript
// src/app/actions/upload-server.ts
import { revalidateTag } from 'next/cache';

export async function uploadProfilePicture(formData: FormData) {
  // ... upload code ...

  // Invalidate all avatar-related cache
  revalidateTag(`avatar-${userId}`);
  revalidateTag('profile');

  return { success: true, path: data.path };
}
```

**In your fetch calls:**

```typescript
// src/app/components/profile.tsx
async function getProfile(userId: string) {
  return fetch(`/api/profile/${userId}`, {
    next: { tags: [`avatar-${userId}`, 'profile'] },
  }).then((r) => r.json());
}
```

---

## Common Errors & Solutions

### Error: "New row violates row-level security policy for table 'objects'"

**Cause:** RLS policy not matching conditions or missing auth context.

**Solutions:**

1. **Verify bucket_id matches:**
   ```sql
   -- Check that bucket_id in policy matches actual bucket
   SELECT bucket_id FROM storage.objects WHERE id = 'some-file-id';
   ```

2. **Verify folder path matches user ID:**
   ```typescript
   // Ensure path follows pattern: {userId}/folder/file.ext
   const filePath = `${auth.currentUser.id}/avatars/${file.name}`;
   ```

3. **Test policy with simplified version:**
   ```sql
   CREATE POLICY "Debug: Allow all authenticated"
   ON storage.objects
   FOR INSERT
   TO authenticated
   WITH CHECK (bucket_id = 'user-uploads');
   ```

4. **Use server client to bypass RLS (trusted operations only):**
   ```typescript
   // Use SERVICE_ROLE key for admin operations (server-side only)
   const adminClient = createClient(url, serviceRoleKey);
   ```

### Error: "Failed to create resumable upload URL"

**Causes:** Expired session, auth token invalid, or TUS endpoint misconfigured.

```typescript
// Verify session before upload
const { data: { session } } = await supabase.auth.getSession();
if (!session || new Date(session.expires_at! * 1000) < new Date()) {
  // Session expired - refresh
  await supabase.auth.refreshSession();
}
```

### Error: "CORS error when uploading"

**Solution:** Configure CORS in Supabase Storage settings:
- Go to Storage → Policies → CORS
- Add your domain: `https://yourdomain.com`

### Error: "Image not transforming / stuck at original dimensions"

**Causes:**
- Image transformations only available on Pro plan+
- File exceeds transformation size limits
- Incorrect transform parameters

```typescript
// Fallback if transformations unavailable
export function supabaseLoader({
  src,
  width,
  quality,
}: ImageLoaderProps): string {
  try {
    return `https://${projectId}.supabase.co/storage/v1/render/image/public/${src}?width=${width}&quality=${quality || 75}`;
  } catch {
    // Fallback to direct URL without transformation
    return `https://${projectId}.supabase.co/storage/v1/object/public/${src}`;
  }
}
```

---

## Best Practices

### 1. Always Use Signed URLs for Private Buckets

```typescript
// Generate time-limited URLs for secure sharing
async function getFileUrl(userId: string, fileName: string) {
  const { data } = await supabase.storage
    .from('user-uploads')
    .createSignedUrl(`${userId}/documents/${fileName}`, 3600); // 1 hour

  return data?.signedUrl;
}
```

### 2. Implement File Size Limits at Multiple Layers

- **Client:** HTML5 `accept` and file input validation
- **Server Action:** Zod schema validation
- **Browser:** Check `file.size` before upload
- **Storage Policy:** Validate with Postgres triggers if critical

### 3. Use Drag & Drop (React 19 Compatible)

```typescript
// src/app/components/upload-dropzone.tsx
'use client';

import { useRef, useState } from 'react';

export function DropZone({
  onDrop,
}: {
  onDrop: (file: File) => void;
}) {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type !== 'dragleave');
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (files?.[0]) {
      onDrop(files[0]);
    }
    setDragActive(false);
  };

  return (
    <div
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-lg p-8
        ${dragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300'}
      `}
    >
      <input
        ref={inputRef}
        type="file"
        hidden
        onChange={(e) => e.target.files?.[0] && onDrop(e.target.files[0])}
      />
      <button onClick={() => inputRef.current?.click()}>
        Click to upload or drag & drop
      </button>
    </div>
  );
}
```

### 4. Handle Network Interruptions Gracefully

```typescript
// Implement exponential backoff
const retryDelays = [0, 3000, 5000, 10000, 20000, 60000]; // Max 60s between retries

// Use tus-js-client's built-in retry (shown in resumable upload pattern)
// For standard uploads, wrap in retry logic:

async function uploadWithRetry(
  file: File,
  maxRetries = 3
): Promise<string> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const { data, error } = await supabase.storage
        .from('user-uploads')
        .upload(filePath, file);

      if (error) throw error;
      return data.path;
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      await new Promise((resolve) =>
        setTimeout(resolve, retryDelays[i] || 60000)
      );
    }
  }
  throw new Error('Upload failed');
}
```

### 5. Log Upload Events for Analytics

```typescript
// src/app/actions/analytics.ts
'use server';

import { createServerClient } from '@/lib/supabase-server';

export async function logUploadEvent(
  userId: string,
  fileName: string,
  fileSizeBytes: number,
  success: boolean
) {
  const supabase = await createServerClient();

  await supabase.from('upload_events').insert({
    user_id: userId,
    file_name: fileName,
    file_size_bytes: fileSizeBytes,
    success,
    uploaded_at: new Date().toISOString(),
  });
}
```

---

## References

- [Supabase Storage Docs](https://supabase.com/docs/guides/storage)
- [Supabase Storage RLS Policies](https://supabase.com/docs/guides/storage/security/access-control)
- [Supabase Storage Image Transformations](https://supabase.com/docs/guides/storage/serving/image-transformations)
- [Resumable Uploads (TUS Protocol)](https://supabase.com/docs/guides/storage/uploads/resumable-uploads)
- [TUS Protocol Specification](https://tus.io)
- [Next.js Image Optimization](https://nextjs.org/docs/app/building-your-application/optimizing/images)
- [Next.js Server Actions with revalidateTag](https://nextjs.org/docs/app/api-reference/functions/revalidateTag)
- [React 19: useActionState Hook](https://react.dev/reference/react/useActionState)
- [Supabase CDN Caching Guide](https://supabase.com/docs/guides/storage/cdn)
