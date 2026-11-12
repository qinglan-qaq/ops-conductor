"""跨境调度 API 冒烟测试夹具。

每个测试都从全新的内存服务开始，避免审批裁决、目标创建等写操作在用例之间
泄漏；``TestClient`` 使用上下文管理器以触发 FastAPI 生命周期。
"""

import pytest
from fastapi.testclient import TestClient

from opsconductor.api.main import app
from opsconductor.dispatch.adapters.container import reset_service


@pytest.fixture
def client():
    """返回重置过调度状态的 HTTP 测试客户端。"""
    reset_service()
    with TestClient(app) as test_client:
        yield test_client
