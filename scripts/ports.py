"""端口登记与分配（部署时避免端口被占用导致起不来）。

设计
----
· **首选固定值，被占用就自动换**：配置里写了 8808，但 8808 已被别的程序占了 →
  自动挑一个空闲端口起来，并把实际端口写进 `data/ports.json`。
· `data/ports.json` 是唯一的「实际端口」来源：网关自己写 `gateway`，
  智能体运行时写 `agent`；nginx 的反代配置由 `scripts/sync-nginx-ports.py` 按它生成。
· 端口 0 / auto 等同于「随便挑一个空闲的」。

用法
----
    from scripts.ports import pick_port, write_port, read_ports

    port = pick_port(8808)     # 8808 空闲就用 8808，否则挑一个
    write_port("gateway", port)
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
from pathlib import Path

#: 项目根（本文件在 scripts/ 下）
ROOT = Path(__file__).resolve().parent.parent

#: 实际端口登记表（不入库）
PORTS_FILE = ROOT / "data" / "ports.json"

#: 智能体运行时自己汇报端口的位置（run-web.sh 写）
AGENT_PORT_FILE = ROOT / "agent-runtime" / "home" / "state" / "web-port"


def _is_free(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否可用（能绑上就认为可用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(preferred: int | str | None = None, host: str = "127.0.0.1") -> int:
    """挑一个可用端口：优先用 preferred（0/空/被占用则让系统分配）。"""
    try:
        want = int(preferred) if preferred not in (None, "", "auto") else 0
    except (TypeError, ValueError):
        want = 0

    if want > 0 and _is_free(want, host):
        return want

    # 让系统挑一个空闲端口（绑定后立刻释放；紧接着自己 bind，窗口极短）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, 0))
        return int(s.getsockname()[1])


def read_ports() -> dict[str, int]:
    try:
        raw = json.loads(PORTS_FILE.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in (raw or {}).items() if isinstance(v, (int, str))}
    except Exception:  # noqa: BLE001
        return {}


def write_port(name: str, port: int) -> int:
    """写入/更新登记表（保留其它键）。"""
    data = read_ports()
    data[name] = int(port)
    PORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PORTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, PORTS_FILE)
    return int(port)


def agent_port(default: int = 0) -> int:
    """当前智能体运行时的实际端口（优先运行时自报，其次登记表）。"""
    for cand in (_read_int(AGENT_PORT_FILE), read_ports().get("agent"), default):
        if cand and int(cand) > 0:
            return int(cand)
    return 0


def _read_int(path: Path) -> int | None:
    with contextlib.suppress(Exception):
        return int(path.read_text(encoding="utf-8").strip())
    return None
