"""进程内 Run 仓储。

Run 记录不可变；仓储仍对读写做深拷贝，避免调用方绕过锁修改内部对象。
最多保留最近 20 条，超出后淘汰最旧一条；服务重启即丢。
"""

from __future__ import annotations

import copy
from collections import OrderedDict
from threading import RLock

from opsconductor.dispatch.domain.runs import AgentRun


class InMemoryRunRepository:
    """由 ``RLock`` 保护的最近 Run 仓储。"""

    def __init__(self, max_runs: int = 20) -> None:
        if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 1:
            raise ValueError("max_runs must be a positive integer")
        self._max_runs = max_runs
        self._runs: OrderedDict[str, AgentRun] = OrderedDict()
        self._lock = RLock()

    def save(self, run: AgentRun) -> None:
        """保存一条 Run；超过容量时淘汰最旧一条。"""
        with self._lock:
            self._runs[run.id] = copy.deepcopy(run)
            while len(self._runs) > self._max_runs:
                self._runs.popitem(last=False)

    def get(self, run_id: str) -> AgentRun | None:
        """按 ID 返回深拷贝；未知 ID 返回 ``None``。"""
        with self._lock:
            run = self._runs.get(run_id)
            return copy.deepcopy(run) if run is not None else None

    def list(self, limit: int = 3) -> tuple[AgentRun, ...]:
        """按最新在前返回最多 ``limit`` 条深拷贝。"""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return ()
        with self._lock:
            newest_first = list(self._runs.values())[::-1]
            return tuple(copy.deepcopy(run) for run in newest_first[:limit])

    def latest(self) -> AgentRun | None:
        """返回最新一条深拷贝；空仓储返回 ``None``。"""
        with self._lock:
            if not self._runs:
                return None
            last_key = next(reversed(self._runs))
            return copy.deepcopy(self._runs[last_key])


__all__ = ["InMemoryRunRepository"]
