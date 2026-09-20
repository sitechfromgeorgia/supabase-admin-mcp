#!/usr/bin/env python3
"""Verify a supabase-admin-mcp installation against a live instance.

Checks, in order:
  1. Connectivity + execute_sql RPC available.
  2. read_only = true really blocks writes (read-only transaction enforcement).
  3. read_only = false allows writes (probe table created and dropped).

Usage:
  SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/verify_setup.py

Exit code 0 = all checks passed. The probe table is cleaned up in every path.
"""

import asyncio
import os
import sys

import httpx

BASE = os.environ.get("SUPABASE_URL", "https://data.asistent.ge").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
RPC = f"{BASE}/rest/v1/rpc/execute_sql"
PROBE = "_mcp_verify_tmp"


async def call(client: httpx.AsyncClient, query: str, read_only: bool) -> httpx.Response:
    return await client.post(RPC, json={"query": query, "read_only": read_only})


async def main() -> int:
    if not KEY:
        print("FAIL: SUPABASE_SERVICE_KEY is not set")
        return 1

    ok = True
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        r = await call(client, "select 1 as ok", True)
        if r.status_code == 200 and "ok" in r.text:
            print("PASS 1/3  connectivity + execute_sql RPC")
        else:
            print(f"FAIL 1/3  connectivity (HTTP {r.status_code}): {r.text[:200]}")
            ok = False

        r = await call(client, f"create table public.{PROBE}(x int)", True)
        if r.status_code >= 400 and "read-only" in r.text.lower():
            print("PASS 2/3  read_only=true blocks writes")
        else:
            print(f"FAIL 2/3  read_only=true did NOT block a write (HTTP {r.status_code}) — re-run MIGRATION.sql")
            ok = False

        r = await call(client, f"create table if not exists public.{PROBE}(x int)", False)
        created = r.status_code == 200
        r2 = await call(client, f"drop table if exists public.{PROBE}", False)
        if created and r2.status_code == 200:
            print("PASS 3/3  read_only=false allows writes (+ cleanup ok)")
        else:
            print(f"FAIL 3/3  write path (create HTTP {r.status_code}, drop HTTP {r2.status_code})")
            ok = False

    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — see FAIL lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
