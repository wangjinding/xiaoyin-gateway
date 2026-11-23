#!/usr/bin/env python3
"""按 data/ports.json 同步 nginx 反代的上游端口，并在变化时 reload。

为什么需要它：网关和智能体启动时端口是**动态**的（被占用就换一个），
但 nginx 的 proxy_pass 是静态配置。这里把两个 location 的上游端口改成实际值：

    proxy/root.conf   → 127.0.0.1:<gateway 端口>
    proxy/agent.conf  → 127.0.0.1:<agent 端口>

幂等：端口没变就什么都不做（不 reload，不打断连接）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ports import read_ports  # noqa: E402

#: 1Panel 站点配置目录（不同机器路径不同 → 可用环境变量覆盖）
SITE = Path(os.environ.get(
    "GATEWAY_NGINX_DIR",
    "/opt/1panel/www/sites/api.wangjinding.com/proxy",
))
ROOT_CONF = SITE / "root.conf"
AGENT_CONF = SITE / "agent.conf"

#: proxy_pass http://127.0.0.1:8808   /  http://127.0.0.1:8899/
PASS_RE = re.compile(r"(proxy_pass\s+http://127\.0\.0\.1:)(\d+)(/?;)")


def _rewrite(path: Path, port: int) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    new = PASS_RE.sub(lambda m: f"{m.group(1)}{port}{m.group(3)}", text)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _openresty_container() -> str:
    r = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=15,
    )
    for name in (r.stdout or "").splitlines():
        if "openresty" in name.lower():
            return name.strip()
    return ""


def main() -> int:
    ports = read_ports()
    gw, ag = ports.get("gateway"), ports.get("agent")
    if not gw and not ag:
        print("ports.json 里还没有端口，跳过")
        return 0

    changed = []
    if gw and _rewrite(ROOT_CONF, int(gw)):
        changed.append(f"网关 → {gw}")
    if ag and _rewrite(AGENT_CONF, int(ag)):
        changed.append(f"智能体 → {ag}")

    if not changed:
        return 0

    print("nginx 上游已更新：" + "，".join(changed))
    container = _openresty_container()
    if not container:
        print("⚠ 没找到 openresty 容器，配置已改但未 reload", file=sys.stderr)
        return 0
    test = subprocess.run(["docker", "exec", container, "openresty", "-t"],
                          capture_output=True, text=True, timeout=30)
    if test.returncode != 0:
        print("✗ nginx 配置校验失败，未 reload：\n" + (test.stderr or ""), file=sys.stderr)
        return 1
    subprocess.run(["docker", "exec", container, "openresty", "-s", "reload"],
                   capture_output=True, text=True, timeout=30)
    print("✓ 已 reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
