"""前端契约测试：服务端页面必须暴露 API 客户端与快照渲染钩子。"""


def test_served_page_contains_api_hooks(client):
    response = client.get("/dispatch")
    assert response.status_code == 200
    text = response.text
    assert "DISPATCH_API" in text
    assert "applySnapshot" in text
    assert "data-agent=" in text
    assert "api-status" in text
