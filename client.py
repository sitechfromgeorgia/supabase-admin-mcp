"""
supabase_admin_client.py — service_role Supabase REST client.
All queries via execute_sql RPC + REST API. No DATABASE_URL needed.
"""

import httpx


class SupabaseAdminClient:
    """Supabase client with service_role. All via REST (no direct DB)."""

    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/")
        self.rest = f"{self.base}/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(headers=self.headers)

    async def sql(self, query: str, read_only: bool = True) -> list[dict]:
        r = await self._http.post(f"{self.base}/rest/v1/rpc/execute_sql", json={"query": query, "read_only": read_only})
        if r.status_code == 404:
            raise RuntimeError("execute_sql RPC not found. Run MIGRATION.sql in Supabase Studio first.")
        r.raise_for_status()
        return r.json()

    async def get(self, path: str, params: dict | None = None) -> list[dict]:
        r = await self._http.get(f"{self.rest}/{path.lstrip('/')}", params=params)
        r.raise_for_status()
        return r.json()

    async def storage_get(self, path: str, params: dict | None = None) -> list[dict]:
        r = await self._http.get(f"{self.base}/storage/v1/{path.lstrip('/')}", params=params)
        r.raise_for_status()
        return r.json()

    async def get_one(self, path: str, params: dict | None = None) -> dict | None:
        r = await self._http.get(f"{self.rest}/{path.lstrip('/')}", params={**(params or {}), "limit": 1})
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None
