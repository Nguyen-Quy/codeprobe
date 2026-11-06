from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8033
DEFAULT_CTX_SIZE = 4096
DEFAULT_THREADS = 4


def get_codeprobe_home() -> Path:
    base = Path(os.environ.get("CODEPROBE_HOME", Path.home() / ".codeprobe"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_pid_file() -> Path:
    return get_codeprobe_home() / "llama_server.pid"


def get_log_file() -> Path:
    logs_dir = get_codeprobe_home() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "llama_server.log"


def find_model_path() -> Path | None:
    """Locate local Qwen GGUF model in environment or standard directories."""
    explicit = os.environ.get("CODEPROBE_LOCAL_MODEL_PATH")
    if explicit and Path(explicit).is_file():
        return Path(explicit)

    home = Path.home()
    candidates = [
        home / ".cache/huggingface/hub/qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        home / ".models/qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        home / ".lmstudio/models/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/qwen2.5-coder-3b-instruct-q4_k_m.gguf",
    ]

    for p in candidates:
        if p.is_file():
            return p

    # Search huggingface cache for any qwen 3b gguf
    hf_hub = home / ".cache/huggingface/hub"
    if hf_hub.is_dir():
        for gguf in hf_hub.rglob("*qwen2.5-coder-3b*.gguf"):
            if gguf.is_file():
                return gguf

    return None


def find_llama_server_binary() -> str | None:
    """Find native llama-server binary in PATH or system binaries."""
    explicit = os.environ.get("CODEPROBE_LLAMA_SERVER_BIN")
    if explicit and shutil.which(explicit):
        return explicit

    found = shutil.which("llama-server")
    if found:
        return found

    for std_path in ("/usr/bin/llama-server", "/usr/local/bin/llama-server"):
        if os.path.isfile(std_path) and os.access(std_path, os.X_OK):
            return std_path

    return None


def is_server_alive(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Check if llama-server /health is responsive."""
    url = f"http://{host}:{port}/health"
    try:
        resp = requests.get(url, timeout=0.8)
        return resp.status_code == 200
    except (requests.RequestException, OSError):
        return False


def detect_optimal_gpu_layers() -> int:
    """
    Auto-detect free VRAM via nvidia-smi and calculate optimal layers for Qwen 3B.
    Qwen 2.5 Coder 3B Q4_K_M has 36 layers (~52MB/layer). Reserves 400MB for desktop.
    """
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            free_mb = int(res.stdout.strip().splitlines()[0])
            usable_mb = max(0, free_mb - 400)
            layers = usable_mb // 52
            # Bound safely between 12 and 28 layers for stability on Quadro M1000M
            return min(28, max(12, layers))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 16


def start_server_daemon(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    ctx_size: int = DEFAULT_CTX_SIZE,
    threads: int = DEFAULT_THREADS,
    gpu_layers: int | None = None,
    timeout_wait: float = 12.0,
) -> dict[str, Any]:
    """
    Launch llama-server in the background if not already active.
    """
    if is_server_alive(host=host, port=port):
        return {
            "status": "already_running",
            "host": host,
            "port": port,
            "message": f"Server is already responsive at http://{host}:{port}",
        }

    binary = find_llama_server_binary()
    if not binary:
        raise RuntimeError(
            "llama-server binary not found. Please install llama-cpp (e.g. pacman -S llama-cpp) "
            "or set CODEPROBE_LLAMA_SERVER_BIN."
        )

    model_path = find_model_path()
    if not model_path:
        raise RuntimeError(
            "No local Qwen 3B model found. Set CODEPROBE_LOCAL_MODEL_PATH or place model at "
            "~/.cache/huggingface/hub/qwen2.5-coder-3b-instruct-q4_k_m.gguf."
        )

    cmd = [
        binary,
        "-m",
        str(model_path),
        "-c",
        str(ctx_size),
        "-t",
        str(threads),
        "--host",
        host,
        "--port",
        str(port),
        "--flash-attn",
        "on",
    ]

    # GPU offload layers (auto-detected or overridden)
    ngl = gpu_layers
    if ngl is None:
        if os.environ.get("CODEPROBE_GPU_LAYERS"):
            try:
                ngl = int(os.environ["CODEPROBE_GPU_LAYERS"])
            except ValueError:
                ngl = detect_optimal_gpu_layers()
        else:
            ngl = detect_optimal_gpu_layers()

    if ngl and ngl > 0:
        cmd.extend(["-ngl", str(ngl)])

    log_path = get_log_file()
    with open(log_path, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    pid_path = get_pid_file()
    pid_path.write_text(str(proc.pid), encoding="utf-8")

    # Poll until ready
    start_time = time.time()
    while time.time() - start_time < timeout_wait:
        if is_server_alive(host=host, port=port):
            return {
                "status": "started",
                "pid": proc.pid,
                "host": host,
                "port": port,
                "model": str(model_path),
                "log_file": str(log_path),
            }
        time.sleep(0.3)

    return {
        "status": "spawning",
        "pid": proc.pid,
        "host": host,
        "port": port,
        "model": str(model_path),
        "log_file": str(log_path),
        "note": "Process started; waiting for full context initialization.",
    }


def stop_server_daemon() -> dict[str, Any]:
    """Gracefully terminate background llama-server."""
    pid_path = get_pid_file()
    if not pid_path.is_file():
        return {"status": "not_running", "message": "No PID file found."}

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid = None

    if pid:
        try:
            os.kill(pid, 15)  # SIGTERM
            time.sleep(0.5)
            # Verify if dead
            try:
                os.kill(pid, 0)
                # Still alive, force kill
                os.kill(pid, 9)
            except OSError:
                pass
        except OSError as exc:
            logger.debug("Failed to kill process %s: %s", pid, exc)

    if pid_path.exists():
        pid_path.unlink()

    return {"status": "stopped", "pid": pid}


def get_server_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> dict[str, Any]:
    """Query current server status and configuration."""
    alive = is_server_alive(host=host, port=port)
    pid_path = get_pid_file()
    saved_pid = None
    if pid_path.is_file():
        try:
            saved_pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pass

    return {
        "alive": alive,
        "host": host,
        "port": port,
        "pid": saved_pid,
        "binary": find_llama_server_binary(),
        "model": str(find_model_path() or "Not found"),
        "log_file": str(get_log_file()),
    }
