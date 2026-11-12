"""前端契约测试：Vue 入口与旧设计稿的可用钩子。"""


def test_served_page_contains_vue_hooks(client):
    response = client.get("/dispatch")

    assert response.status_code == 200
    text = response.text
    assert '<div id="app">' in text
    assert "/assets/" in text
    assert "运筹跨境" in text


def test_legacy_page_keeps_old_api_hooks(client):
    response = client.get("/dispatch/legacy")

    assert response.status_code == 200
    text = response.text
    assert "DISPATCH_API" in text
    assert "applySnapshot" in text
    assert "data-agent=" in text
    assert "api-status" in text
