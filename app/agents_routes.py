"""智能体路由 —— 只服务「内嵌完整 DSH」这一种形态。

智能体这一层只做身份登记与权限（谁能用、叫什么、什么状态）；
真正的执行与界面全在内嵌的 DeepSeek Harness 进程里（`/agent/`）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from app.agents import Agent, AgentStore, AgentsError

log = logging.getLogger("xiaoyin-gateway.agents")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _offload(fn, *args):
    """把阻塞函数丢到线程池，避免卡住事件循环。"""
    return await asyncio.to_thread(fn, *args)

#: 内嵌 DSH 的首选端口（实际端口是动态的，见 scripts/ports.py）
DSH_PORT_PREFERRED = 8899


def _dsh_port() -> int:
    """当前智能体运行时的实际端口（运行时自报优先，其次端口登记表）。"""
    try:
        from scripts.ports import agent_port
        return agent_port(DSH_PORT_PREFERRED) or DSH_PORT_PREFERRED
    except Exception:  # noqa: BLE001
        return DSH_PORT_PREFERRED

#: 运行时 token 文件
DSH_TOKEN_FILE = (Path(__file__).resolve().parents[1]
                  / "agent-runtime" / "home" / "state" / "web-token")


def can_use_agent(a: Agent, role: str) -> bool:
    """该角色能否使用这个智能体。"""
    if "admin" in a.access_roles:
        return role == "admin"
    if role in a.access_roles:
        return True
    return False


def dsh_runtime_state() -> dict[str, Any]:
    """内嵌 DSH 是否就绪：端口活着 + 拿得到 token。"""
    try:
        tok = DSH_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        tok = ""
    port = _dsh_port()
    alive = False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            alive = True
    except OSError:
        alive = False
    return {"token": tok, "ready": bool(tok) and alive, "port": port}


def install(app: FastAPI, *, store: AgentStore,
            require_auth: Callable, require_admin: Callable,
            json_body: Callable,
            model_index: Callable | None = None) -> None:
    """把智能体路由挂到网关。"""

    # ── 列表 ────────────────────────────────────────────────────────
    @app.get("/agents")
    async def agents_list(request: Request, _auth=Depends(require_auth)):
        require_admin(request)
        store.reload_if_changed()
        role = getattr(request.state, "role", "member")
        agents = store.list(include_retired=True)
        dsh = dsh_runtime_state()
        return {
            "agents": [a.public_dict() for a in agents if can_use_agent(a, role) or role == "admin"],
            "max_agents": store.max_agents,
            "active": store.active_count(),
            "dsh": {"ready": dsh["ready"], "port": dsh["port"]},
        }

    # ── DSH 入口（带 token，所有登录用户可用）────────────────────────
    # 注意：目前所有人共用同一个 DSH 实例（同一 token），隔离靠前端隐藏侧栏，
    #       属于「视觉隔离」；真正的每人独立实例见 agent-runtime/README 的多用户计划。
    @app.get("/agents/dsh/entry")
    async def agents_dsh_entry(request: Request, _auth=Depends(require_auth)):
        st = dsh_runtime_state()
        return {
            "url": f"/agent/?token={st['token']}" if st["token"] else "",
            "ready": st["ready"],
            "port": st["port"],
        }

    # ── 小银智能体入口（按登录用户下发 token，首次访问自动开通）──────
    @app.get("/agents/entry")
    async def agents_entry(request: Request, _auth=Depends(require_auth)):
        account = request.state.account
        name = str(account or "").strip()
        if not name:
            raise HTTPException(401, "未登录")
        try:
            url = await _offload(_ensure_agent_user, name, request.state.role)
        except Exception as e:  # noqa: BLE001 —— 开通失败要如实告诉前端
            raise HTTPException(500, f"智能体开通失败：{e}")
        return {"url": url, "ready": bool(url)}

    # ── 新建 ────────────────────────────────────────────────────────
    @app.post("/agents")
    async def agents_create(request: Request, _auth=Depends(require_auth)):
        require_admin(request)
        body = await json_body(request)
        try:
            slug = str(body.get("slug") or "").strip()
            model_ids, alias_names = model_index() if model_index else ([], [])
            profile_ids: list[str] = []
            a = store.create(
                slug=slug,
                display_name=str(body.get("display_name") or "").strip(),
                description=str(body.get("description") or "").strip(),
                params=body.get("params") if isinstance(body.get("params"), dict) else {},
                access_roles=body.get("access_roles") or ["admin"],
                access_users=body.get("access_users") or [],
                status=str(body.get("status") or "published"),
                model_ids=model_ids, alias_names=alias_names, profile_ids=profile_ids,
            )
        except AgentsError as e:
            raise HTTPException(400, str(e))
        log.info("智能体已创建：%s", a.slug)
        return a.to_dict()

    # ── 修改 ────────────────────────────────────────────────────────
    @app.put("/agents/{slug}")
    async def agents_update(request: Request, slug: str, _auth=Depends(require_auth)):
        require_admin(request)
        body = await json_body(request)
        try:
            a = store.update(slug, body)
        except AgentsError as e:
            raise HTTPException(400, str(e))
        return a.to_dict()

    # ── 归档 / 恢复 ─────────────────────────────────────────────────
    @app.delete("/agents/{slug}")
    async def agents_retire(slug: str, request: Request, _auth=Depends(require_auth)):
        require_admin(request)
        try:
            a = store.retire(slug)
        except AgentsError as e:
            raise HTTPException(400, str(e))
        return a.to_dict()

    @app.post("/agents/{slug}/restore")
    async def agents_restore(slug: str, request: Request, _auth=Depends(require_auth)):
        require_admin(request)
        try:
            a = store.restore(slug)
        except AgentsError as e:
            raise HTTPException(400, str(e))
        return a.to_dict()

    # ── 身份 + 功能开关（控制台用它决定显示哪些入口）────────────────
    @app.get("/auth/me")
    async def auth_me(request: Request, _auth=Depends(require_auth)):
        store.reload_if_changed()
        role = getattr(request.state, "role", "member")
        visible = [a.slug for a in store.list() if can_use_agent(a, role)]
        st = dsh_runtime_state()
        return {
            "account": getattr(request.state, "account", ""),
            "role": role,
            "features": {
                "agents": {
                    "enabled": bool(visible),
                    "can_manage": role == "admin",
                    "visible": visible,
                },
            },
            "dsh": {"ready": st["ready"], "port": st["port"]},
        }


# ── 小银智能体：用户开通与入口 ────────────────────────────────────────
_AGENT_DATA = Path(
    os.environ.get("AGENT_DATA_DIR")
    or str(_PROJECT_ROOT / "agent-runtime" / "vm-home" / "agent-app" / "data")
)
_AGENT_CONTAINER = os.environ.get("AGENT_CONTAINER", "xiaoyin-agent-vm")
_agent_provisioned: set[str] = set()


def _agent_users_path() -> Path:
    return _AGENT_DATA / "users.json"


def _load_agent_users() -> dict:
    try:
        return json.loads(_agent_users_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_agent_users(users: dict) -> None:
    p = _agent_users_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)


def _provision_system_user(name: str, prefer_uid: int | None = None) -> int | None:
    """在 VM 里确保系统用户与工作区存在（幂等），返回其 uid。失败返回 None。"""
    script = (
        f"if ! id -u {name} >/dev/null 2>&1; then "
        + (f"  useradd -M -u {prefer_uid} -s /bin/sh {name} 2>/dev/null || true; " if prefer_uid else "")
        + f"  id -u {name} >/dev/null 2>&1 || useradd -M -s /bin/sh {name} 2>/dev/null || adduser -D -s /bin/sh {name} 2>/dev/null || true; "
        f"fi; "
        f"uid=$(id -u {name} 2>/dev/null || echo ''); "
        f"if [ -n \"$uid\" ]; then "
        f"  mkdir -p /workspace/{name}; chown -R {name}:{name} /workspace/{name} 2>/dev/null || true; "
        f"  chmod 700 /workspace/{name} 2>/dev/null || true; "
        f"  chmod 711 /workspace 2>/dev/null || true; "
        f"fi; "
        f"echo \"$uid\""
    )
    try:
        r = subprocess.run(
            ["nerdctl", "exec", _AGENT_CONTAINER, "sh", "-c", script],
            capture_output=True, timeout=30, check=False, text=True,
        )
        out = (r.stdout or "").strip().splitlines()
        return int(out[-1]) if out and out[-1].isdigit() else None
    except Exception:  # noqa: BLE001
        return None


def _ensure_agent_user(name: str, role: str) -> str:
    """返回该用户的小银智能体入口 URL（含 token）。首次调用会自动开通。"""
    users = _load_agent_users()
    rec = users.get(name)

    if role == "admin":
        rec = rec or {}
        rec.update({"uid": 0, "gid": 0, "workspace": "/workspace", "role": "admin"})
        rec.setdefault("token", "agt-" + secrets.token_urlsafe(24))
        users[name] = rec
        _save_agent_users(users)
        return f"/agent/?token={rec['token']}"

    # 每次都校验一次系统用户（VM 重启会丢掉用户/属主，幂等开销很小）
    live_uid = _provision_system_user(name, (rec or {}).get("uid") or None)

    if not rec or not rec.get("uid"):
        # 新用户：取已有最大值 +1，保证不与历史 uid 冲突
        used = {int(u.get("uid") or 0) for n, u in users.items() if n != "admin"}
        uid = live_uid or (max(used | {1000}) + 1)
        rec = rec or {}
        rec.update({"uid": uid, "gid": uid, "workspace": f"/workspace/{name}", "role": "member"})
        rec.setdefault("token", "agt-" + secrets.token_urlsafe(24))
        users[name] = rec
        _save_agent_users(users)
    elif live_uid and live_uid != rec.get("uid"):
        rec["uid"] = rec["gid"] = live_uid
        _save_agent_users(users)

    _agent_provisioned.add(name)
    return f"/agent/?token={rec['token']}"
