import aiohttp
import os
import json
from typing import Optional

class MoltbookClient:
    def __init__(self, api_key: str):
        self.base_url = "https://www.moltbook.com/api/v1"
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def check_claim_status(self) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/agents/status", headers=self.headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status", "unknown")
                return "error"

    async def post_update(self, content: str, title: Optional[str] = None, submolt: str = "general"):
        payload = {
            "submolt": submolt,
            "content": content
        }
        if title:
            payload["title"] = title
            
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/posts", headers=self.headers, json=payload) as resp:
                return await resp.json()
