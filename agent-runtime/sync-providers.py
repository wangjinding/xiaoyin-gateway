#!/usr/bin/env python3
"""按「运营商」生成 DSH 的 provider 覆盖层。

动机：DSH 的模型选择器**原生按 provider 分组**（state.groups，group.id 就是 provider id）。
如果把 82 个模型全塞进一个 provider，下拉里就是一长条平铺；
按网关自己的供应商拆开，选择器里就会显示成：

    1min.AI        （44 个）
    Agnes AI       （10 个）
    OpenCode Go    （26 个）
    Dots AI        （1 个）

所有 provider 的 baseURL 都指向网关自己的 /v1 —— 分组只影响「看起来」，
真正路由仍由网关按 model id 决定，所以这里可以放心拆。

输出：home/profiles/gateway/providers.gen.yml（启动时用 --patch 叠加）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

RUNTIME = Path(__file__).resolve().parent
REPO = RUNTIME.parent
CONFIG = REPO / "data" / "gateway.yaml"
OUT = RUNTIME / "home" / "profiles" / "gateway" / "providers.gen.yml"

GATEWAY_BASE = os.environ.get("DSH_GATEWAY_BASE", "http://127.0.0.1:8808/v1")
API_KEY_ENV = "XIAOYIN_GATEWAY_KEY"

#: DSH provider id 只允许小写字母/数字/连字符，网关的 key 基本已合规
def _safe(pid: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "-" for c in pid.lower())


def main() -> int:
    if not CONFIG.exists():
        print(f"找不到网关配置：{CONFIG}", file=sys.stderr)
        return 1

    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    provs = raw.get("providers") or {}

    groups: list[tuple[str, str, list[str]]] = []
    seen: set[str] = set()
    for key, p in provs.items():
        models = []
        for m in (p.get("models") or []):
            mid = m.get("id") if isinstance(m, dict) else m
            if not mid or mid in seen:
                continue
            seen.add(mid)
            models.append(mid)
        if models:
            groups.append((_safe(key), str(p.get("name") or key), models))

    # 兜底：网关有、但没列进任何供应商的模型（理论上没有，留着以防万一）
    try:
        import urllib.request
        req = urllib.request.Request(
            GATEWAY_BASE.replace("/v1", "/v1/models"),
            headers={"Authorization": f"Bearer {os.environ.get(API_KEY_ENV, '')}"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        extra = [m["id"] for m in data.get("data", [])
                 if m.get("id") and m["id"] not in seen]
        if extra:
            groups.append(("xiaoyin-extra", "小银网关（其他）", extra))
    except Exception:  # noqa: BLE001 —— 网关没起也能生成（只是少兜底组）
        pass

    if not groups:
        print("网关配置里没有任何供应商模型，跳过", file=sys.stderr)
        return 1

    providers: dict[str, dict] = {}
    for pid, name, models in groups:
        providers[pid] = {
            "displayName": name,
            "api": "openai-completions",
            "baseURL": GATEWAY_BASE,
            "apiKeyEnv": API_KEY_ENV,
            "models": [{"id": m, "name": m} for m in models],
        }

    # 默认模型：保持现状（deepseek-v4.1-flash），落在它所属的供应商下
    default_model = os.environ.get("DSH_DEFAULT_MODEL", "deepseek-v4.1-flash")
    default_provider = next(
        (pid for pid, _, models in groups if default_model in models),
        groups[0][0],
    )
    if default_model not in {m for _, _, ms in groups for m in ms}:
        default_model = groups[0][2][0]

    # 注意：cordis 的 --patch 文件是**条目列表**，不是映射
    body = [
        {"id": "llm-pi-ai", "config": {"providers": providers}},
        {"id": "agent-default-model",
         "config": {"provider": default_provider, "model": default_model}},
    ]
    header = (
        "# 由 agent-runtime/sync-providers.py 自动生成，请勿手改。\n"
        "# 按网关的供应商分组（DSH 的模型选择器按 provider 分组显示）。\n"
        f"# 供应商 {len(providers)} 个 / 模型 {sum(len(v['models']) for v in providers.values())} 个\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    print(f"已生成 {OUT}：{len(providers)} 个供应商 / "
          f"{sum(len(v['models']) for v in providers.values())} 个模型；默认 {default_provider}/{default_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
