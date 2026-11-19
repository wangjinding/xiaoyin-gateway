"""OpenCode Go 模型的套餐元数据（月度额度 / 是否用请求训练 / 零数据保留）。

**只用于展示，不参与路由与计费。** 数据来自官方 models 接口（实测无需鉴权）：

    GET https://opencode.ai/inference/go/v1/models

其中每个模型带 `go` 字段：

    go: {
      monthly_usage: {"go": 100, "go-plus": 200, "go-teams": 105},
      training: false,      # 是否用你的请求训练模型
      zdr: true,            # 零数据保留（不保留任何内容）
      limited_regions: false,
    }

官方口径（docs/console/go）：`monthly_usage` 是「**只用这一个模型时，各套餐每月额度
能覆盖多少用量**」（文档举例用的是美元）。所以前端展示成「$100/月」这类形式。

设计取舍：
  · 自带 6 小时缓存，失败后 5 分钟重试；
  · 拉取失败一律返回**已有缓存或空 dict** —— `/v1/models` 绝不因此报错或变慢太多
    （首次拉取加 6 秒上限；之后走内存）。
  · 不写进 gateway.yaml：这是上游随时会变的市场信息，不属于网关的静态配置，
    也不该让模型同步脚本再背一层。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request

_URL = "https://opencode.ai/inference/go/v1/models"
log = logging.getLogger("api-gateway.gomodels")
_TTL = 6 * 3600
_RETRY_AFTER_FAIL = 300
_TIMEOUT = 6

_lock = threading.Lock()
_cache: dict[str, dict] = {}
_at = 0.0


def _fetch() -> dict[str, dict]:
    req = urllib.request.Request(
        _URL,
        headers={"Accept": "application/json", "User-Agent": "api-gateway/gomodels"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:      # noqa: S310
        payload = json.loads(resp.read().decode("utf-8", "replace"))

    out: dict[str, dict] = {}
    for m in payload.get("data") or []:
        mid = m.get("id")
        g = m.get("go") or {}
        usage = g.get("monthly_usage") or {}
        if not mid or (not usage and g.get("training") is None):
            continue
        out[mid] = {
            "monthly_usage": {k: int(v) for k, v in usage.items()
                              if isinstance(v, (int, float))},
            "training": bool(g.get("training")),
            "zdr": bool(g.get("zdr")),
        }
    return out


def cache_stamp() -> float:
    """上次成功刷新的时间戳（0 = 还没拿到过）。调用方可据此判断展示数据是否需要重拼。"""
    return _at


def get_go_meta(force: bool = False) -> dict[str, dict]:
    """{model_id: {"monthly_usage": {...}, "training": bool, "zdr": bool}}。

    过期才刷新；刷新失败保留旧数据，并推迟 `_RETRY_AFTER_FAIL` 秒再试。
    """
    global _at
    now = time.time()
    if not force and _cache and now - _at < _TTL:
        return _cache
    if not _lock.acquire(blocking=False):
        return _cache                     # 别的线程正在刷新，先用旧的
    try:
        if force or not _cache or time.time() - _at >= _TTL:
            try:
                fresh = _fetch()
            except Exception as exc:      # noqa: BLE001 —— 展示数据，失败不影响主流程
                # 2026-11-19：一定要留痕 —— 前端这一列空了，运维得能一眼看出是"没拉到"还是"没渲染"
                log.warning("OpenCode Go 元数据拉取失败（前端额度/训练列会空）：%s", exc)
                fresh = None
            if fresh:
                _cache.clear()
                _cache.update(fresh)
                _at = time.time()
                log.info("OpenCode Go 元数据已载入：%d 个模型", len(fresh))
            else:
                _at = time.time() - _TTL + _RETRY_AFTER_FAIL
    finally:
        _lock.release()
    return _cache
