# AI 网关项目体检报告（2026-10-23）

> 范围：`/root/dsh/projects/<项目>`（v2.9.15）。方法：跑测试 + 静态检查 + 数据/权限/备份审计 + 真实接口压测。

## 一、已修复（本次体检发现）

| # | 问题 | 严重度 | 处理 |
|---|---|---|---|
| 1 | **225 个测试用例跑不起来**（pytest 未装，`tests/` 6197 行）| 高 | 装入 venv + `requirements-dev.txt` |
| 2 | **4 个用例断言旧内存版 `/logs`**（改读库时引入的回归）| 高 | 断言前 `flush()`；改用 `/logs/calls` 断言管理员视角 |
| 3 | **3 处夹具引用已下线的 `grok-4.6`** | 中 | 改 `grok-4.7` |
| 4 | **测试读写生产库** | 高 | `tests/conftest.py` 把 `CALLLOG_DB` 指向临时目录 |
| 5 | `/logs` 库映射缺 `video_id` | 中 | `api_calls` 增列（自动迁移）|
| 6 | 测试不幂等（失败残留账号）| 低 | 用例开头先删 |

**结果**：218/225 → **225/225 通过**。

## 二、已按建议落地（运维/容量）

| 项 | 内容 |
|---|---|
| **每日备份** | `backup-app-data.sh` + `dsh-gateway-backup.timer`（03:30）：`VACUUM INTO` 快照 + 配置/账号/会话/历史，留 14 份 |
| **备份恢复演练** | `backup-restore-drill.sh`：解包 → 校验 SQLite integrity/行数、JSON 可解析、权限 600（已接入每日报告）|
| **每人 QPS** | `server.rate_limit_rps: null → 20`（按账号桶；实测 120 并发触发 55 个 429）|
| **库体积上限** | `CALLLOG_MAX_BYTES=2GiB`，按「有效数据量」精确收紧到 80% + 按需 VACUUM（含 `wal_checkpoint`）|
| **接口存活监控** | `uptime-check.sh` 接入每日报告：本机/公网/4 台关键服务，进程活着但接口挂也能发现 |
| **WAF 白名单自愈** | `waf-whitelist-guard.sh` + 每小时 timer：`^/v1/` 被面板覆盖时自动补回并 reload |

## 三、评估后**不做**的项（附理由）

| 项 | 为什么不做 |
|---|---|
| **CSP 去掉 `unsafe-eval`** | 产物里的 `new Function` 来自 **vue-i18n 的 JIT 编译器**；去掉会直接打断全部翻译（复现「界面显示变量名」）。站点是登录后的管理台、无内联脚本，风险本来就窄 |
| **FTS5 全文搜索** | 当前 400 行，`LIKE '%kw%'` 全表扫 <10ms；10 万行以后再说 |
| **echarts 按需引入** | 已独立 chunk + 懒加载，只影响 2 个页面，改造收益 < 风险 |
| **熔断/限流/失败计数落盘** | 重启重置是**更安全的默认**（宁可多试一次，不要一直熔断）|
| **sessions token 加密**（上一轮误判）| `app/sessions.py` 早就只存 `sha256("sess:"+token)`，盘上无可用凭证 |

## 四、体检通过项

- SQLite `integrity_check = ok`；索引齐全；文件权限 600
- 安全响应头齐全（CSP / X-Frame-Options: DENY / nosniff）
- **TODO / FIXME：0 处**；53 处 `except Exception` 全部有日志或兜底，无裸 `pass`
- `history.py` 有三重上限（条目数/单条字节/整文件字节）
- `/v1/media/download` 有域名白名单 + 内网地址拦截（SSRF）
- 密码 salt+hash；API Key 明文存储是产品需求（页面需反复复制），靠文件权限 600 兜底
- 阻塞 IO 都走 `_offload` 线程池

## 五、仍然存在的已知取舍（记录在案）

1. **`/logs` 只看自己的**（含 admin）—— 看全站要走「日志 → 调用日志」页签。
2. **实时页列表只给前 8KB 预览**，展开时调 `/logs/entry/{id}` 取全文（避免 200 条大内容拖垮接口）。
3. **`unsafe-eval` 必须保留**（见上）。
4. **WAF 规则以文件为准**：面板保存会覆盖 → 已有每小时自愈兜底，但仍建议最终在面板里也配置一份。
