"""Pytest configuration for the golden-task evaluation suite."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: golden task that exercises concurrency and may take longer",
    )
