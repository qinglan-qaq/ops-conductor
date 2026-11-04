"""用于 API key 认证的凭据哈希。"""

import hashlib


def hash_api_key(value: str) -> str:
    """返回用于存储与查找 key 的十六进制 SHA-256 摘要。

    该摘要是确定性的且不加盐，因此认证时只需在唯一的 ``api_key_hash`` 列上做
    一次等值查找即可定位用户。API key 是高熵密钥，因此这种场景下使用快速且不
    加盐的哈希是可以接受的。

    Args:
        value: 调用方提供的原始 API key，不做任何归一化。

    Returns:
        64 字符的小写十六进制摘要，与持久化所用的 ``String(64)`` 列匹配。

    Warning:
        切勿存储或记录原始 key，也不要将本函数复用于用户自选密码；不加盐的
        SHA-256 不是密码哈希。
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
