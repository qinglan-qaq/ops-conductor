"""从环境变量读取平台凭据。

本地开发用 ``.env``/OS 环境变量，CI 用 GitHub Actions secrets；生产环境的
Vault/AWS/GCP 适配器在后续切片实现。本类不记录、不打印密钥原值。
"""

from __future__ import annotations

import os

from opsconductor.dispatch.domain.config import Secret


class EnvCredentialProvider:
    """按配置里的变量名读取环境变量。"""

    def has(self, ref: str) -> bool:
        """判断变量是否存在且非空。"""
        return bool(ref) and bool(os.environ.get(ref))

    def get(self, ref: str) -> Secret | None:
        """返回密钥包装；缺失或空值返回 ``None``。"""
        value = os.environ.get(ref)
        if not value:
            return None
        return Secret(value)


__all__ = ["EnvCredentialProvider"]
