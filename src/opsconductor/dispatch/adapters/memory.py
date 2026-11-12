"""进程内调度仓储。

``InMemoryDispatchRepository`` 实现
:class:`~opsconductor.dispatch.domain.ports.DispatchRepository`：读路径返回深拷贝，
写路径在同一把 ``RLock`` 内执行 mutator，重置时用种子工厂重建状态。Demo 不依赖
PostgreSQL 或 Redis，进程退出即丢弃全部状态。
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from threading import RLock

from opsconductor.dispatch.domain.models import DispatchState


class InMemoryDispatchRepository:
    """以种子工厂初始化、由锁保护的内存仓储。"""

    def __init__(self, seed: Callable[[], DispatchState]) -> None:
        """保存种子工厂并生成初始状态。

        Args:
            seed: 每次调用都返回一份全新种子状态的工厂；重置时复用。
        """
        self._seed = seed
        self._state = seed()
        self._lock = RLock()

    def snapshot(self) -> DispatchState:
        """返回内部状态的深拷贝，调用方无法绕过锁修改仓储。"""
        with self._lock:
            return copy.deepcopy(self._state)

    def mutate(self, mutator: Callable[[DispatchState], None]) -> None:
        """在锁内把 mutator 应用于内部状态。

        Args:
            mutator: 原地修改状态的函数；抛出的异常会原样传播，锁由上下文
                管理器释放。
        """
        with self._lock:
            mutator(self._state)

    def reset(self) -> DispatchState:
        """用种子工厂重建状态并返回重建后的深拷贝。"""
        with self._lock:
            self._state = self._seed()
            return copy.deepcopy(self._state)


__all__ = ["InMemoryDispatchRepository"]
