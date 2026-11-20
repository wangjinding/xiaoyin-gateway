#!/usr/bin/env python3
"""1min.AI 模型清单同步（独立脚本，不动 sync_models.py 的 3 家逻辑）。

为什么单独一个脚本：
  · 1min 走 **OpenAI 兼容 API**（`GET https://api.1min.ai/openai/v1/models`），
    不需要像 OpenCode/Agnes/Dots 那样解析 HTML/JS 文档 —— 抓取链路简单得多。
  · sync_models.py 有 1300 行，`diff()` / `build_plan()` 和那三家强耦合，
    硬塞第四家进去风险大、收益低。分开跑，互不干扰。

用法：
  python scripts/sync_onemin.py            # 只报告
  python scripts/sync_onemin.py --apply    # 真的写盘
  python scripts/sync_onemin.py --json     # JSON 输出

退出码：
  0 = 无变化（或已同步成功）
  1 = 有漂移但没写盘（未加 --apply）
  2 = 抓取 / 解析 / 写盘失败

⚠️ 去重规则（重要）：
  1min 聚合了 OpenAI / DeepSeek / Qwen / GLM / Mistral / Kimi 的模型，
  其中 6 个 id 和 opencode 重名。网关遇到重名会「按 id 调用始终命中先定义的那个」，
  会把 opencode 的主路由抢走 —— 所以本脚本**永远跳过**和其他供应商重名的 id。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CFG = ROOT / "data" / "gateway.yaml"
DEFAULT_ENV = ROOT / "data" / ".env"

PROVIDER = "onemin"
BASE_URL = "https://api.1min.ai/openai/v1"
UA = "xiaoyin-gateway-onemin-sync/1.0 (+ops; contact admin)"


# ── 工具 ────────────────────────────────────────────────────────────

def _load_env(path: Path) -> dict[str, str]:
    """读 data/.env（KEY=VALUE 简单格式）。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _display_name(mid: str) -> str:
    """模型 id → 好看的名字（和手工加进 gateway.yaml 的一致）。"""
    fixes = {
        "qwen": "Qwen", "deepseek": "DeepSeek", "mistral": "Mistral",
        "magistral": "Magistral", "ministral": "Ministral",
        "open-mistral": "Open Mistral", "gpt": "GPT", "o3": "o3", "glm": "GLM",
    }
    parts = mid.split("/")
    if len(parts) == 2:                      # openrouter 风格 moonshotai/kimi-k2.7-code
        vendor, name = parts
        vendor_map = {"moonshotai": "Moonshot", "meta": "Meta", "zai": "Z.AI"}
        v = vendor_map.get(vendor, vendor.title())
        n = name
        for k, v2 in sorted(fixes.items(), key=lambda x: -len(x[0])):
            if n.startswith(k):
                n = v2 + n[len(k):]
                break
        return f"{v} {n}"
    for k, v in sorted(fixes.items(), key=lambda x: -len(x[0])):
        if mid.startswith(k):
            return v + mid[len(k):]
    return mid


def fetch_onemin(api_key: str) -> dict[str, dict]:
    """拉 1min 的模型清单。返回 {id: {"id","display_name","owned_by"}}。"""
    req = urllib.request.Request(
        f"{BASE_URL}/models",
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}（key 失效 / 被限流 / 接口改版）") from e

    items = payload.get("data") or []
    out: dict[str, dict] = {}
    for m in items:
        mid = m.get("id")
        if not mid:
            continue
        out[mid] = {
            "id": mid,
            "display_name": _display_name(mid),
            "owned_by": m.get("owned_by") or "",
        }
    if not out:
        raise RuntimeError("接口没返回任何模型（响应结构可能变了）")
    return out


# ── 主流程 ──────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="1min.AI 模型清单同步（默认只报告，--apply 才写盘）")
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--env", default=str(DEFAULT_ENV))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    cfg_path = Path(args.config)

    # 1) key
    env = _load_env(Path(args.env))
    api_key = os.environ.get("ONEMIN_API_KEY") or env.get("ONEMIN_API_KEY") or ""
    if not api_key:
        msg = "缺少 ONEMIN_API_KEY（data/.env 或环境变量）"
        print(msg, file=sys.stderr)
        return 2

    # 2) 拉模型
    try:
        doc = fetch_onemin(api_key)
    except Exception as e:                                   # noqa: BLE001
        msg = f"抓取 1min 模型失败：{type(e).__name__}: {e}"
        print(msg, file=sys.stderr)
        if args.log:
            _append_log(args.log, msg, 2)
        return 2

    # 3) 读配置
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        msg = f"读配置失败：{type(e).__name__}: {e}"
        print(msg, file=sys.stderr)
        return 2

    providers = cfg.get("providers") or {}
    cur = {m["id"]: m for m in (providers.get(PROVIDER) or {}).get("models") or []}

    # 其他供应商已有的 id —— 永远不往 onemin 里加，避免重名抢路由
    others: dict[str, str] = {}
    for pk, pv in providers.items():
        if pk == PROVIDER:
            continue
        for m in (pv.get("models") or []):
            others.setdefault(m["id"], pk)

    # 4) 算漂移
    added = sorted(mid for mid in doc if mid not in cur and mid not in others)
    skipped_dup = sorted(mid for mid in doc if mid not in cur and mid in others)
    removed = sorted(mid for mid in cur if mid not in doc)     # 配置有、接口没了
    kept = [mid for mid in removed if mid in others]           # 但别家还有 → 不删

    report = {
        "provider": PROVIDER,
        "doc_total": len(doc),
        "cfg_total": len(cur),
        "added": added,
        "removed": [m for m in removed if m not in others],
        "skipped_duplicate": skipped_dup,
        "kept_because_other_provider": kept,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"-- 1min.AI 模型同步（{time.strftime('%Y-%m-%d %H:%M')}）--")
        print(f"   接口 {len(doc)} 个 / 配置 {len(cur)} 个")
        print(f"   新增 {len(added)}   删除 {len(report['removed'])}")
        if skipped_dup:
            print(f"   跳过重名 {len(skipped_dup)}：{', '.join(skipped_dup)}")
        if kept:
            print(f"   别家还有不删 {len(kept)}：{', '.join(kept)}")
        for mid in added:
            print(f"   + {mid}")
        for mid in report["removed"]:
            print(f"   - {mid}")

    drift = bool(added or report["removed"])
    if not args.apply:
        code = 1 if drift else 0
        if drift:
            print("→ 有漂移，未加 --apply，没写盘")
        else:
            print("→ 无变化 ✓")
        return code

    # 5) 写盘
    if not drift:
        print("→ 无需落盘 ✓")
        return 0

    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = cfg_path.with_name(f"{cfg_path.name}.bak-onemin-sync-{ts}")
    shutil.copy2(cfg_path, backup)

    pcfg = providers.setdefault(PROVIDER, {})
    pcfg.setdefault("name", "1min.AI")
    pcfg.setdefault("base_url", BASE_URL)
    pcfg.setdefault("auth", {"token_env": "ONEMIN_API_KEY"})
    pcfg.setdefault("extra_headers", {})

    models = {m["id"]: m for m in (pcfg.get("models") or [])}
    for mid in report["removed"]:
        models.pop(mid, None)
    for mid in added:
        models[mid] = {
            "id": mid,
            "display_name": doc[mid]["display_name"],
            "type": "text",
            "protocols": ["chat/completions"],
        }
    pcfg["models"] = [models[k] for k in sorted(models)]

    # 原子替换
    tmp = cfg_path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096),
        encoding="utf-8",
    )

    # 回读校验
    try:
        check = yaml.safe_load(tmp.read_text(encoding="utf-8"))
        got = {m["id"] for m in (check["providers"][PROVIDER].get("models") or [])}
        want = set(models)
        if got != want:
            raise RuntimeError(f"回读不一致：缺 {sorted(want - got)[:5]} 多 {sorted(got - want)[:5]}")
    except Exception as e:                                   # noqa: BLE001
        tmp.unlink(missing_ok=True)
        shutil.copy2(backup, cfg_path)
        msg = f"回读校验失败，已还原：{type(e).__name__}: {e}"
        print(msg, file=sys.stderr)
        return 2

    tmp.replace(cfg_path)
    print(f"→ 已写盘：+{len(added)} / -{len(report['removed'])}（备份 {backup.name}）")
    return 0


def _append_log(path: str, msg: str, code: int) -> None:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} exit={code} =====\n{msg}\n")
    except Exception:                                        # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
