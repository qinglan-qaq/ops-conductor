from opsconductor.config import Settings


def test_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.setenv("OPSCONDUCTOR_L3_BATCH_THRESHOLD", "2")
    settings = Settings(_env_file=None)
    assert settings.l3_batch_threshold == 2
    assert settings.approval_timeout_minutes == 30
    assert settings.stub_llm is True
    assert settings.database_url.startswith("postgresql+psycopg://")
