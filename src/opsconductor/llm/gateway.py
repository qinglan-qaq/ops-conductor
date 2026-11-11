"""聊天模型网关：协议定义，以及 stub 与 OpenAI 兼容的 HTTP 实现。

调用方只依赖 :class:`ChatModel` 的 ``complete_json`` 接口：传入系统与用户
提示，返回解析后的 JSON 对象。生产实现是 :class:`HttpChatModel`，测试与离线
场景使用 :class:`StubChatModel`。
"""

import json
from typing import Any, Protocol

import httpx


class ChatModel(Protocol):
    """返回 JSON 对象的最小聊天模型协议。

    Note:
        实现必须返回 JSON 对象（``dict``），而不是任意文本；无法产出 JSON 时
        应抛出异常，而不是返回空结果。
    """

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]: ...


class StubChatModel:
    """按顺序返回预置 JSON 响应的确定性模型。

    Attributes:
        responses: 待消费的响应队列，每调用一次弹出一个。

    Note:
        队列耗尽时 ``complete_json`` 抛出 ``RuntimeError``。``system`` 与
        ``user`` 提示会被忽略，因此测试输出完全可预测。
    """

    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """返回队首的预置响应。

        Args:
            system: 系统提示；stub 忽略它。
            user: 用户提示；stub 忽略它。

        Returns:
            下一个预置的 JSON 对象。

        Raises:
            RuntimeError: 已没有剩余响应。
        """

        if not self.responses:
            raise RuntimeError("no stub response left")
        return self.responses.pop(0)


class HttpChatModel:
    """返回解析后 JSON 的最小 OpenAI 兼容 chat completions 客户端。

    Attributes:
        base_url: API 根地址，构造时去掉末尾斜杠。
        api_key: 以 Bearer 方式发送的 API key。
        model: 请求体中使用的模型名。

    Note:
        每次调用新建一个 ``httpx.AsyncClient``（30 秒超时），并强制
        ``response_format`` 为 ``json_object``。本类不重试、不缓存。
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """调用 chat completions 并解析首个 choice 的 JSON 内容。

        Args:
            system: 系统提示。
            user: 用户提示。

        Returns:
            首个 choice 消息内容解析后的 JSON 对象。

        Raises:
            httpx.HTTPStatusError: 服务端返回非 2xx 状态。
            httpx.RequestError: 连接、超时等传输层错误。
            json.JSONDecodeError: 消息内容不是合法 JSON。
            KeyError: 响应缺少 ``choices`` 或消息字段。
        """
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
