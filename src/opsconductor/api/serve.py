"""Conda 原生启动入口。

Uvicorn 不是独立环境，而是安装在本项目 conda 环境中的 ASGI 服务器库。这个模块
让 Demo 直接用当前 conda 环境的 Python 启动，不依赖全局 `uvicorn` 命令：

    conda activate opsconductor
    python -m opsconductor.api.serve --host 127.0.0.1 --port 8010 --reload

底层仍然是 Uvicorn；它负责把 FastAPI app 暴露成 HTTP 服务。需要换端口、热重载
或日志级别时，改这里的参数即可。
"""

from __future__ import annotations

import argparse

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    Returns:
        支持 ``--host``、``--port``、``--reload`` 与 ``--log-level`` 的解析器。
    """
    parser = argparse.ArgumentParser(
        prog="python -m opsconductor.api.serve",
        description="用当前 conda 环境启动 OpsConductor Demo（底层使用 Uvicorn）。",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式热重载；生产环境不要开启",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn 日志级别，默认 info",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """解析参数并启动 ASGI 服务。

    Args:
        argv: 可选的参数列表；``None`` 时读取 ``sys.argv``。
    """
    args = build_parser().parse_args(argv)
    uvicorn.run(
        "opsconductor.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
