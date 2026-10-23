"""调用日志落地（SQLite 持久化，默认保留 90 天）。

为什么需要它
------------
`AccessLog` 是**内存**环形缓冲（重启即丢），`/metrics` 只有聚合计数。出工单时最常被问的是
「谁、什么时候、用哪个模型、失败原因是什么、当时发了什么内容」—— 这些必须落盘可查。

设计取舍
--------
- **零新依赖**：`sqlite3` 是标准库，不引入 ORM / 数据库驱动（与本项目"依赖极简"的基调一致）。
- **不阻塞请求**：`stage()` 只往内存队列 append；后台 task 每 1 秒或攒满 `BATCH` 条批量写库。
  队列满（默认 10000 条）即丢弃并计数，**绝不反压请求**。
- **隐私**：API Key 只存前 8 位（`key_id`）；提示词/回复按 `CALLLOG_CONTENT_MAX` 截断（默认 8000 字）。
- **保留**：默认 90 天，启动时清理一次 + 每 6 小时清理一次（不依赖外部 cron）。
- **只增不改**：日志表不做 UPDATE；清理只按 `ts` 删。

环境变量
--------
- `CALLLOG_DB`            默认 `data/calllog.db`
- `CALLLOG_RETENTION_DAYS` 默认 90
- `CALLLOG_QUEUE_MAX`      默认 10000
- `CALLLOG_CONTENT_MAX`    默认 8000（提示词/回复各自截断长度）
- `CALLLOG_DISABLED=1`     整体关闭（不回退任何现有行为）
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger("calllog")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("CALLLOG_DB") or os.path.join(_ROOT, "data", "calllog.db")
RETENTION_DAYS = int(os.environ.get("CALLLOG_RETENTION_DAYS") or 90)
QUEUE_MAX = int(os.environ.get("CALLLOG_QUEUE_MAX") or 10000)
CONTENT_MAX = int(os.environ.get("CALLLOG_CONTENT_MAX") or 8000)
DISABLED = os.environ.get("CALLLOG_DISABLED", "") not in ("", "0", "false", "False")

BATCH = 200                 # 攒够多少条提交一次
FLUSH_INTERVAL = 1.0        # 最长多久提交一次（秒）
CLEAN_INTERVAL = 6 * 3600   # 清理间隔（秒）

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             REAL    NOT NULL,
    rid            TEXT,
    account        TEXT,
    key_id         TEXT,
    kind           TEXT,
    method         TEXT,
    path           TEXT,
    model          TEXT,
    served         TEXT,
    provider       TEXT,
    caller         TEXT,
    stream         INTEGER DEFAULT 0,
    ok             INTEGER DEFAULT 1,
    status         INTEGER,
    latency_ms     INTEGER,
    ip             TEXT,
    ua             TEXT,
    prompt         TEXT,
    completion     TEXT,
    tok_prompt     INTEGER DEFAULT 0,
    tok_completion INTEGER DEFAULT 0,
    tok_cached     INTEGER DEFAULT 0,
    tok_reasoning  INTEGER DEFAULT 0,
    ver            TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_ts      ON api_calls(ts);
CREATE INDEX IF NOT EXISTS idx_calls_acc_ts  ON api_calls(account, ts);
CREATE INDEX IF NOT EXISTS idx_calls_model   ON api_calls(model, ts);
CREATE INDEX IF NOT EXISTS idx_calls_ok      ON api_calls(ok, ts);
CREATE INDEX IF NOT EXISTS idx_calls_status  ON api_calls(status, ts);
CREATE INDEX IF NOT EXISTS idx_calls_rid     ON api_calls(rid);
"""

_COLUMNS = ("ts", "rid", "account", "key_id", "kind", "method", "path", "model",
            "served", "provider", "caller", "stream", "ok", "status", "latency_ms",
            "ip", "ua", "prompt", "completion",
            "tok_prompt", "tok_completion", "tok_cached", "tok_reasoning", "ver")

_INSERT = f"INSERT INTO api_calls ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})"


def _clip(v: Any, n: int = CONTENT_MAX) -> str:
    """内容裁剪：非字符串转字符串，超长截断并标注。"""
    if v is None:
        return ""
    s = v if isinstance(v, str) else str(v)
    if len(s) > n:
        return s[:n] + f"\n…（已截断，共 {len(s)} 字）"
    return s


def prompt_preview(body: str | None, limit: int = 240) -> str:
    """从请求体 JSON 里抽出「用户实际说的话」，给列表做一行预览。

    兼容三种入站格式：
      · OpenAI chat / responses: `messages[-1].content`（字符串或多段 text parts）、`input`
      · Anthropic messages:      `messages[-1].content`（同上）
      · 非 JSON / 解析失败:      退回原文前 limit 字（换行压成空格）
    """
    if not body:
        return ""
    try:
        import json as _json
        d = _json.loads(body)
    except Exception:  # noqa: BLE001
        return " ".join(str(body).split())[:limit]
    text = ""
    msgs = d.get("messages") if isinstance(d, dict) else None
    if not isinstance(msgs, list) or not msgs:
        msgs = d.get("input") if isinstance(d, dict) else None
    if isinstance(msgs, list) and msgs:
        last = msgs[-1]
        if isinstance(last, dict):
            c = last.get("content")
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, dict):
                        t = p.get("text") or p.get("input_text") or p.get("content")
                        if isinstance(t, str):
                            parts.append(t)
                text = " ".join(parts)
        elif isinstance(last, str):
            text = last
    if not text and isinstance(d, dict):
        for k in ("prompt", "content", "text", "input"):
            v = d.get(k)
            if isinstance(v, str) and v:
                text = v
                break
            if isinstance(v, list) and v:      # responses 线的 input 可能是消息数组
                lastv = v[-1]
                if isinstance(lastv, dict) and isinstance(lastv.get("content"), str):
                    text = lastv["content"]
                    break
                if isinstance(lastv, str):
                    text = lastv
                    break
    if not text:
        text = body
    return " ".join(str(text).split())[:limit]


class CallLogStore:
    """SQLite 调用日志存储。线程安全的单写者 + 单读连接。"""

    def __init__(self, path: str = DB_PATH, *, retention_days: int = RETENTION_DAYS,
                 queue_max: int = QUEUE_MAX, enabled: bool = True) -> None:
        self.path = path
        self.retention_days = retention_days
        self.queue_max = queue_max
        self.enabled = enabled and not DISABLED
        self._q: deque[tuple] = deque()
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self.written = 0
        self.dropped = 0
        self.last_error = ""

    # ── 生命周期 ────────────────────────────────────────────────
    def open(self) -> None:
        if not self.enabled:
            log.info("调用日志已禁用（CALLLOG_DISABLED）")
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.executescript(SCHEMA)
        self._migrate(db)
        db.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._db = db
        log.info("调用日志已就绪: %s（保留 %d 天）", self.path, self.retention_days)
        self.cleanup()

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        """轻量迁移：老库缺 token 列时补上（2026-10-23 加）。"""
        have = {r[1] for r in db.execute("PRAGMA table_info(api_calls)")}
        for col in ("tok_prompt", "tok_completion", "tok_cached", "tok_reasoning"):
            if col not in have:
                db.execute(f"ALTER TABLE api_calls ADD COLUMN {col} INTEGER DEFAULT 0")
                log.info("调用日志表已补列: %s", col)

    async def start(self) -> None:
        self.open()
        if not self.enabled or self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="calllog-writer")
        log.info("调用日志后台写入已启动")

    async def close(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self.flush()
        if self._db:
            self._db.close()
            self._db = None

    async def _loop(self) -> None:
        last_clean = time.time()
        while self._running:
            await asyncio.sleep(FLUSH_INTERVAL)
            try:
                self.flush()
                sweep()
                if time.time() - last_clean > CLEAN_INTERVAL:
                    last_clean = time.time()
                    self.cleanup()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("调用日志写入失败: %s", e)

    # ── 写入 ────────────────────────────────────────────────────
    def stage(self, row: dict[str, Any]) -> None:
        """入队（非阻塞）。队列满则丢弃并计数。"""
        if not self.enabled:
            return
        try:
            tup = tuple(row.get(c) for c in _COLUMNS)
        except Exception:  # noqa: BLE001
            return
        with self._lock:
            if len(self._q) >= self.queue_max:
                self.dropped += 1
                return
            self._q.append(tup)

    def flush(self) -> int:
        """把队列里的行一次批量写库。返回写入条数。"""
        if not self.enabled or self._db is None:
            return 0
        with self._lock:
            if not self._q:
                return 0
            rows = list(self._q)
            self._q.clear()
        try:
            with self._lock:
                self._db.executemany(_INSERT, rows)
                self._db.commit()
            self.written += len(rows)
            return len(rows)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("调用日志批量写入失败（丢弃 %d 条）: %s", len(rows), e)
            return 0

    # ── 清理 ────────────────────────────────────────────────────
    def cleanup(self) -> int:
        if not self.enabled or self._db is None:
            return 0
        cutoff = time.time() - self.retention_days * 86400
        try:
            with self._lock:
                cur = self._db.execute("DELETE FROM api_calls WHERE ts < ?", (cutoff,))
                self._db.commit()
            n = cur.rowcount or 0
            if n:
                log.info("调用日志清理：删除 %d 条（早于 %d 天前）", n, self.retention_days)
            return n
        except Exception as e:  # noqa: BLE001
            log.warning("调用日志清理失败: %s", e)
            return 0

    # ── 查询 ────────────────────────────────────────────────────
    def _where(self, *, start: float | None, end: float | None, account: str | None,
               model: str | None, ok: int | None, status: int | None,
               kind: str | None, q: str | None,
               with_content: bool = False) -> tuple[str, list[Any]]:
        w: list[str] = []
        p: list[Any] = []
        if start is not None:
            w.append("ts >= ?")
            p.append(start)
        if end is not None:
            w.append("ts <= ?")
            p.append(end)
        if account:
            w.append("(account = ? OR caller = ?)")
            p.extend([account, account])
        if model:
            w.append("(model = ? OR served = ?)")
            p.extend([model, model])
        if ok is not None:
            w.append("ok = ?")
            p.append(int(ok))
        if status:
            w.append("status = ?")
            p.append(int(status))
        if kind:
            w.append("kind = ?")
            p.append(kind)
        if q:
            like = f"%{q}%"
            w.append("(rid LIKE ? OR account LIKE ? OR model LIKE ? OR prompt LIKE ? "
                     "OR completion LIKE ? OR ua LIKE ? OR ip LIKE ?)")
            p.extend([like] * 7)
        return (" WHERE " + " AND ".join(w)) if w else "", p

    def query(self, *, start: float | None = None, end: float | None = None,
              account: str | None = None, model: str | None = None,
              ok: int | None = None, status: int | None = None,
              kind: str | None = None, q: str | None = None,
              limit: int = 50, offset: int = 0,
              with_content: bool = False) -> dict[str, Any]:
        """分页查询。with_content=False 时不返回 prompt/completion（列表页省流量）。"""
        if not self.enabled or self._db is None:
            return {"total": 0, "items": [], "enabled": False}
        where, params = self._where(start=start, end=end, account=account, model=model,
                                    ok=ok, status=status, kind=kind, q=q)
        # 列表页也要「内容」列（2026-10-23 老板要求）：始终取 prompt 生成单行预览，
        #   但不把动辄几千字的原文整包吐给列表（with_content=1 才给完整 prompt/completion）。
        cols = ("id, ts, rid, account, key_id, kind, method, path, model, served, provider, "
                "caller, stream, ok, status, latency_ms, ip, ua, ver, prompt")
        if with_content:
            cols += ", completion"
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        try:
            with self._lock:
                total = self._db.execute(f"SELECT COUNT(*) FROM api_calls{where}", params).fetchone()[0]
                rows = self._db.execute(
                    f"SELECT {cols} FROM api_calls{where} ORDER BY ts DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset],
                ).fetchall()
        except Exception as e:  # noqa: BLE001
            log.warning("调用日志查询失败: %s", e)
            return {"total": 0, "items": [], "error": str(e)}
        names = [d[0] for d in self._db.execute(f"SELECT {cols} FROM api_calls LIMIT 0").description]
        items = []
        for r in rows:
            d = dict(zip(names, r))
            d["ts_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["ts"]))
            raw_prompt = d.get("prompt") or ""
            d["prompt_text"] = prompt_preview(raw_prompt)
            if not with_content:
                d.pop("prompt", None)      # 列表只给预览，不吐原文
            items.append(d)
        return {"total": total, "items": items, "limit": limit, "offset": offset}

    def get(self, call_id: int) -> dict[str, Any] | None:
        if not self.enabled or self._db is None:
            return None
        try:
            with self._lock:
                cur = self._db.execute("SELECT * FROM api_calls WHERE id = ?", (int(call_id),))
                row = cur.fetchone()
                names = [d[0] for d in cur.description]
        except Exception:  # noqa: BLE001
            return None
        if not row:
            return None
        d = dict(zip(names, row))
        d["ts_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["ts"]))
        # 详情也带一份「提取出的 content」，弹窗里第一屏就能看到用户说了什么
        d["prompt_text"] = prompt_preview(d.get("prompt"))
        return d

    def stats(self, days: int = 7) -> dict[str, Any]:
        """按天 / 模型 / 账号 / 状态码聚合（前端图表与概览用）。"""
        if not self.enabled or self._db is None:
            return {"enabled": False}
        since = time.time() - max(1, int(days)) * 86400
        out: dict[str, Any] = {"enabled": True, "days": days}
        try:
            with self._lock:
                out["daily"] = [
                    {"date": r[0], "total": r[1], "ok": r[2], "fail": r[3],
                     "avg_ms": round(r[4] or 0, 1)}
                    for r in self._db.execute(
                        "SELECT date(ts, 'unixepoch', 'localtime') d, COUNT(*), "
                        "SUM(ok), SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END), AVG(latency_ms) "
                        "FROM api_calls WHERE ts >= ? GROUP BY d ORDER BY d", (since,))
                ]
                out["models"] = [
                    {"model": r[0], "total": r[1], "fail": r[2], "avg_ms": round(r[3] or 0, 1)}
                    for r in self._db.execute(
                        "SELECT model, COUNT(*), SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END), "
                        "AVG(latency_ms) FROM api_calls WHERE ts >= ? "
                        "GROUP BY model ORDER BY COUNT(*) DESC LIMIT 20", (since,))
                ]
                out["accounts"] = [
                    {"account": r[0], "total": r[1], "fail": r[2]}
                    for r in self._db.execute(
                        "SELECT account, COUNT(*), SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) "
                        "FROM api_calls WHERE ts >= ? GROUP BY account "
                        "ORDER BY COUNT(*) DESC LIMIT 50", (since,))
                ]
                out["statuses"] = [
                    {"status": r[0], "total": r[1]}
                    for r in self._db.execute(
                        "SELECT status, COUNT(*) FROM api_calls WHERE ts >= ? "
                        "GROUP BY status ORDER BY COUNT(*) DESC LIMIT 20", (since,))
                ]
                out["total"] = self._db.execute(
                    "SELECT COUNT(*) FROM api_calls").fetchone()[0]
                out["size_bytes"] = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)
        out["written"] = self.written
        out["dropped"] = self.dropped
        out["queued"] = len(self._q)
        return out

    # ── 聚合（供 /metrics、/health、月度用量导出使用）────────────────────
    def usage_snapshot(self, *, account: str | None = None, days: int = 0) -> dict[str, Any]:
        """按模型/供应商/账号聚合调用数、耗时与 token（形状对齐内存态 `Metrics.snapshot()`）。

        account 非空 → 只算该账号（成员视角）；days=0 → 不限时间（用库内全部，即保留期内）。
        """
        if not self.enabled or self._db is None:
            return {"enabled": False}
        since = time.time() - days * 86400 if days and days > 0 else 0
        conds: list[str] = []
        params: list[Any] = []
        if since:
            conds.append("ts >= ?")
            params.append(since)
        if account:
            conds.append("account = ?")
            params.append(account)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        try:
            with self._lock:
                mcond = f"{where} AND model IS NOT NULL" if where else " WHERE model IS NOT NULL"
                calls = {r[0]: {"ok": r[1] or 0, "fail": r[2] or 0}
                         for r in self._db.execute(
                             f"SELECT model, SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END), "
                             f"SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) "
                             f"FROM api_calls{mcond} GROUP BY model", params)}
                pcond = f"{where} AND provider IS NOT NULL" if where else " WHERE provider IS NOT NULL"
                providers = {r[0] or "?": {"ok": r[1] or 0, "fail": r[2] or 0}
                             for r in self._db.execute(
                                 f"SELECT provider, SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END), "
                                 f"SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) "
                                 f"FROM api_calls{pcond} GROUP BY provider", params)}
                latency: dict[str, Any] = {}
                lcond = (f"{where} AND " if where else " WHERE ") + "model IS NOT NULL AND latency_ms IS NOT NULL"
                for r in self._db.execute(
                        f"SELECT model, COUNT(*), AVG(latency_ms) FROM api_calls{lcond} GROUP BY model",
                        params):
                    latency[r[0]] = {"count": r[1], "avg": round(r[2] or 0, 3)}
                # p50 / p95：表很小，用 offset 取分位值
                for mid, d in list(latency.items()):
                    for key, frac in (("p50", 0.5), ("p95", 0.95)):
                        off = max(0, int((d["count"] - 1) * frac))
                        c2 = (f"{where} AND " if where else " WHERE ") + "model IS ? AND latency_ms IS NOT NULL"
                        row = self._db.execute(
                            f"SELECT latency_ms FROM api_calls{c2} ORDER BY latency_ms LIMIT 1 OFFSET ?",
                            [*params, mid, off]).fetchone()
                        d[key] = row[0] if row else None
                tok = self._db.execute(
                    f"SELECT COALESCE(SUM(tok_prompt),0), COALESCE(SUM(tok_completion),0), "
                    f"COALESCE(SUM(tok_cached),0), COALESCE(SUM(tok_reasoning),0), COUNT(*) "
                    f"FROM api_calls{where}", params).fetchone()
        except Exception as e:  # noqa: BLE001
            log.warning("用量聚合失败: %s", e)
            return {"enabled": False, "error": str(e)}
        return {"enabled": True, "calls": calls, "providers": providers, "latency": latency,
                "tokens": {"prompt": tok[0], "completion": tok[1],
                           "cached": tok[2], "reasoning": tok[3]},
                "total": tok[4], "since": since}

    def usage_monthly(self, month: str | None = None) -> dict[str, Any]:
        """按月统计每个账号的用量（调用数 / 成功失败 / 平均耗时 / 内容字节 / token 不提供）。"""
        if not self.enabled or self._db is None:
            return {"enabled": False, "month": month, "items": []}
        if not month:
            month = time.strftime("%Y-%m")
        try:
            start = time.mktime(time.strptime(month + "-01", "%Y-%m-%d"))
        except ValueError:
            return {"enabled": False, "month": month, "error": "月份格式应为 YYYY-MM", "items": []}
        # 下月 1 号
        y, m = int(month[:4]), int(month[5:7])
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = time.mktime(time.strptime(f"{ny:04d}-{nm:02d}-01", "%Y-%m-%d"))
        try:
            with self._lock:
                rows = self._db.execute(
                    "SELECT account, COUNT(*), SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END), AVG(latency_ms), "
                    "COUNT(DISTINCT model) FROM api_calls WHERE ts >= ? AND ts < ? "
                    "GROUP BY account ORDER BY COUNT(*) DESC", (start, end)).fetchall()
        except Exception as e:  # noqa: BLE001
            return {"enabled": False, "month": month, "error": str(e), "items": []}
        items = [{"account": r[0] or "anonymous", "calls": r[1] or 0, "ok": r[2] or 0,
                  "fail": r[3] or 0, "avg_ms": round(r[4], 1) if r[4] else 0,
                  "models": r[5] or 0} for r in rows]
        return {"enabled": True, "month": month, "items": items,
                "total_calls": sum(i["calls"] for i in items)}

    def export_rows(self, **kw: Any) -> list[dict[str, Any]]:
        """导出用：不带分页，最多 50000 条。"""
        kw.setdefault("limit", 50000)
        kw.setdefault("offset", 0)
        kw["with_content"] = True
        return self.query(**kw).get("items", [])


store = CallLogStore()

# ── 与请求生命周期的双向握手 ──────────────────────────────────────
# 一条调用日志由两半拼成：
#   ① 访问日志条目（AccessLog.add）：kind/model/provider/caller/ok/stream/body/response
#   ② 响应元数据（中间件收尾）：status/耗时/IP/UA/Key 前 8 位
# 但两半的**先后顺序是不确定的**：
#   · 非流式：① 在请求处理中途就 add 了 → ② 后到
#   · 流式：② 在 StreamingResponse 建好就返回了 → ① 要等流真正发完才 add（后到）
# 所以两边都先暂存、谁发现对方已就绪就立刻拼成一行落库。
_PEND_ENTRY: dict[str, dict] = {}   # rid -> 访问日志条目（等 meta）
_PEND_META: dict[str, dict] = {}    # rid -> 响应元数据（等 entry）
_pend_lock = threading.Lock()
_PEND_MAX = 2000
_META_TTL = 300.0                   # 元数据最多等 5 分钟，避免泄漏


def _trim(d: dict[str, dict]) -> None:
    while len(d) > _PEND_MAX:
        try:
            d.pop(next(iter(d)), None)
        except (StopIteration, KeyError):
            break


def _row(entry: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    rid = str(entry.get("rid") or meta.get("rid") or "")
    tok = entry.get("tokens")
    if not tok and rid:
        with _tok_lock:
            tok = TOKENS_BY_RID.pop(rid, None)
    tok = tok or {}
    return {
        "ts": entry.get("ts") or time.time(),
        "rid": entry.get("rid") or meta.get("rid"),
        "account": entry.get("account") or entry.get("caller") or meta.get("account"),
        "key_id": meta.get("key_id", ""),
        "kind": entry.get("kind") or meta.get("kind"),
        "method": entry.get("method") or meta.get("method"),
        "path": entry.get("path") or meta.get("path"),
        "model": entry.get("model"),
        "served": entry.get("served"),
        "provider": entry.get("provider"),
        "caller": entry.get("caller"),
        "stream": 1 if entry.get("stream") else 0,
        "ok": 1 if entry.get("ok") else 0,
        "status": meta.get("status"),
        "latency_ms": meta.get("latency_ms"),
        "ip": meta.get("ip", ""),
        "ua": _clip(meta.get("ua", ""), 200),
        "prompt": _clip(entry.get("body"), CONTENT_MAX),
        "tok_prompt": int(tok.get("prompt_tokens") or 0),
        "tok_completion": int(tok.get("completion_tokens") or 0),
        "tok_cached": int(tok.get("cached_tokens") or 0),
        "tok_reasoning": int(tok.get("reasoning_tokens") or 0),
        "completion": _clip(entry.get("response"), CONTENT_MAX),
        "ver": meta.get("ver", ""),
    }


# token 侧信道：`_record_usage_metrics()` 只知道 token、不知道 rid；请求中间件只知道 rid、
#   不知道 token。用一个按 rid 索引的小字典把两半接起来（AccessLog.add 落库时取走并清空）。
TOKENS_BY_RID: dict[str, dict[str, int]] = {}
_tok_lock = threading.Lock()
_TOK_MAX = 2000


def note_tokens(rid: str, prompt: int, completion: int,
                cached: int = 0, reasoning: int = 0) -> None:
    """记下某次请求的 token 用量（由 `_record_usage_metrics` 调用）。"""
    if not store.enabled or not rid:
        return
    with _tok_lock:
        TOKENS_BY_RID[rid] = {"prompt_tokens": int(prompt or 0),
                              "completion_tokens": int(completion or 0),
                              "cached_tokens": int(cached or 0),
                              "reasoning_tokens": int(reasoning or 0)}
        while len(TOKENS_BY_RID) > _TOK_MAX:
            try:
                TOKENS_BY_RID.pop(next(iter(TOKENS_BY_RID)), None)
            except (StopIteration, KeyError):
                break


def on_access(entry: dict[str, Any]) -> None:
    """`AccessLog.add()` 调用：拿到访问日志条目；若响应元数据已就绪则立即落库。"""
    if not store.enabled:
        return
    rid = str(entry.get("rid") or "")
    if not rid:
        store.stage(_row(entry, {}))
        return
    with _pend_lock:
        meta = _PEND_META.pop(rid, None)
        if meta is None:
            _PEND_ENTRY[rid] = entry
            _trim(_PEND_ENTRY)
            return
    store.stage(_row(entry, meta))


def on_response(rid: str, *, status: int, latency_ms: float, ip: str = "", ua: str = "",
                key_id: str = "", ver: str = "", method: str = "", path: str = "",
                account: str = "", stream: bool = False, body: str = "") -> None:
    """请求中间件收尾调用：补上响应元数据；条目已就绪则立即落库。

    `stream=True` 时条目一定还没到（SSE 还没开始发），只暂存等 `on_access`；
    非流式且没有条目、又是 **/v1/ 下的失败**时，补一条"早失败"记录（例如未知模型 400、
    鉴权 401/403、限流 429）—— 这类请求压根走不到 `_access.add`，但恰恰最需要留痕。
    """
    if not store.enabled:
        return
    rid = str(rid or "")
    meta = {"rid": rid, "status": int(status) if status else None,
            "latency_ms": int(latency_ms), "ip": ip, "ua": ua, "key_id": key_id,
            "ver": ver, "method": method, "path": path, "account": account,
            "kind": "chat" if path.startswith("/v1/") else None,
            "ts": time.time()}
    if rid:
        with _pend_lock:
            entry = _PEND_ENTRY.pop(rid, None)
            if entry is not None:
                store.stage(_row(entry, meta))
                return
            if stream:
                _PEND_META[rid] = meta          # 等 event_stream 收尾时补条目
                _trim(_PEND_META)
                return
    # 没有条目且不是流式：只有 /v1/ 下的失败才补记（成功一定有条目；其余端点不算"调用"）
    if status and int(status) >= 400 and path.startswith("/v1/"):
        # 早失败（未知模型 / 鉴权失败 / 限流）走不到 AccessLog.add，这里用请求体补全信息，
        #   否则日志里只有一行"400、无模型"，排查时看不出客户端到底请求了什么。
        model = ""
        try:
            import json as _json
            model = str((_json.loads(body or "{}") or {}).get("model") or "")
        except Exception:  # noqa: BLE001
            model = ""
        store.stage(_row({"model": model or None, "body": body}, meta))


def sweep() -> int:
    """丢弃超时未配对的暂存项（由后台循环定期调用）。"""
    now = time.time()
    n = 0
    with _pend_lock:
        for d in (_PEND_META,):
            for k in [k for k, v in d.items() if now - float(v.get("ts") or 0) > _META_TTL]:
                d.pop(k, None)
                n += 1
    return n
