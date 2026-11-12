"""导出 Vue 离线 fixture：snapshot、10 个阶段详情与集成健康。

该脚本只读后端进程内状态：``reset_service()`` 后读取种子快照，不执行审批、
演示或控制写。生成结果用于 Vue 在 API 不可用时显示「离线数据」，不得被当作
真实业务成功。

用法::

    python scripts/export_dispatch_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opsconductor.dispatch.adapters.container import (  # noqa: E402
    get_integration_registry,
    get_service,
    reset_service,
)
from opsconductor.dispatch.adapters.serialize import (  # noqa: E402
    integrations_payload,
    snapshot_payload,
    stage_detail_payload,
)
from opsconductor.dispatch.application.stages import STAGE_CATALOG  # noqa: E402

OUTPUT = ROOT / "frontend" / "src" / "api" / "fixtures.json"


def main() -> None:
    """重建种子状态并写出确定性 fixture。"""
    reset_service()
    service = get_service()
    registry = get_integration_registry()
    payload = {
        "snapshot": snapshot_payload(service.snapshot()),
        "stages": {
            stage.id: stage_detail_payload(service.get_stage_detail(stage.id))
            for stage in STAGE_CATALOG
        },
        "integrations": integrations_payload(registry),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
