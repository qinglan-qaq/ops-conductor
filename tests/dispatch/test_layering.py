"""分层依赖测试：domain 与 application 不得反向依赖外层。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "opsconductor" / "dispatch"
FORBIDDEN_DOMAIN = (
    "opsconductor.dispatch.application",
    "opsconductor.dispatch.adapters",
    "fastapi",
    "sqlalchemy",
    "pydantic",
)
FORBIDDEN_APPLICATION = ("opsconductor.dispatch.adapters",)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_domain_does_not_import_outer_layers() -> None:
    for path in sorted((ROOT / "domain").glob("*.py")):
        for name in _imports(path):
            assert not any(
                name.startswith(prefix) for prefix in FORBIDDEN_DOMAIN
            ), f"{path.name} imports {name}"


def test_application_does_not_import_adapters() -> None:
    for path in sorted((ROOT / "application").glob("*.py")):
        for name in _imports(path):
            assert not any(
                name.startswith(prefix) for prefix in FORBIDDEN_APPLICATION
            ), f"{path.name} imports {name}"
