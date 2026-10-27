"""测试替身：假 aiohttp 会话、假配置条目。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class FakeResponse:
    """aiohttp.ClientResponse 的最小替身。"""

    def __init__(self, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class _RequestContext:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        return self._response

    async def __aexit__(self, *exc_info) -> bool:
        return False


class FakeSession:
    """按顺序吐出预置响应，并记录每次请求的入参。"""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses: list[FakeResponse | Exception] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self.responses.pop(0) if self.responses else FakeResponse()
        if isinstance(item, Exception):
            raise item
        return _RequestContext(item)


def make_config_entry(
    options: dict[str, Any] | None = None,
    title: str = "测试路由",
    entry_id: str = "entry_test",
) -> SimpleNamespace:
    """ConfigEntry 替身：协调器只用到 title / entry_id / options。"""
    return SimpleNamespace(options=options or {}, title=title, entry_id=entry_id)
