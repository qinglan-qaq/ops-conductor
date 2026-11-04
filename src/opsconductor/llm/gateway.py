"""Chat model gateway: protocol plus stub and OpenAI-compatible implementations."""

import json
from typing import Any, Protocol

import httpx


class ChatModel(Protocol):
    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]: ...


class StubChatModel:
    """Deterministic model that returns queued JSON responses in order."""

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        if not self.responses:
            raise RuntimeError("no stub response left")
        return self.responses.pop(0)


class HttpChatModel:
    """Minimal OpenAI-compatible chat completions client returning parsed JSON."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
