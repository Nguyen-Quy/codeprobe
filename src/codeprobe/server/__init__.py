from __future__ import annotations

from .mcp import create_mcp_server, run_mcp_server

__all__ = ["create_http_app", "create_mcp_server", "run_http_server", "run_mcp_server"]


def __getattr__(name: str):
    if name in ("create_http_app", "run_http_server"):
        try:
            from .http import create_http_app, run_http_server

            handlers = {
                "create_http_app": create_http_app,
                "run_http_server": run_http_server,
            }
            return handlers[name]
        except ImportError as exc:
            raise ImportError(
                f"'{name}' requires optional HTTP dependencies ('fastapi', 'uvicorn'). "
                "Install them with `pip install 'codeprobe[http]'` or `uv pip install fastapi uvicorn`."
            ) from exc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
