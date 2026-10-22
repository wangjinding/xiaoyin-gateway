# WAF 与 API 访问：为什么 AI 编程客户端会被 403

> 2026-10-22 由真实工单沉淀（成员 `chenghongchang` 反馈「拿 apikey 请求 403」）。

## 现象

```
POST https://127.0.0.1:8808/v1/chat/completions
Authorization: Bearer wjd-...
User-Agent: WorkBuddy/5.8.3        →  HTTP 403
```

同一把 Key 用 `curl`（`content: "hi"`）请求**完全正常 200**，模型、网关、渠道都没问题。

## 根因

`127.0.0.1:8808` 前面挂着 **1Panel 的 WAF（1pwaf）**，它会检查**请求体内容**：

| 请求体里出现 | 结果 |
|---|---|
| `<script>alert(1)</script>` | 403（命中 XSS 规则）|
| `../../etc/passwd` | 403（命中路径穿越规则）|
| `system("ls -la")` | 403（命中命令执行规则）|
| 普通文本 | 200 |

AI 编程客户端（WorkBuddy / Cursor / 各类 CLI）把**用户代码**原样塞进 prompt，
代码里天然带 `../`、`system(`、`<script>` —— 于是**被当成攻击拦掉**。

判断依据（WAF 访问日志）：

```
/opt/1panel/www/sites/127.0.0.1:8808/log/access.log
117.85.65.211 - - [22/Oct/2026:17:40:26 +0800] "POST /v1/chat/completions HTTP/1.1" 403 16711
    "-" "WorkBuddy/5.8.3" "116.228.205.72"        ← 最后一列是真实客户端 IP（经 EO 回源后）
```

**403 响应体大小 16711 / 23682 字节 = WAF 拦截页**（网关自己的错误是 JSON，通常 < 1KB）。
遇到 403 先看这两个数字，就能区分「WAF 拦」还是「网关拒」。

## 处置

给 WAF 的 URL 白名单加一条，让 `/v1/` 下的 AI 接口跳过内容检查：

```json
// /opt/1panel/apps/openresty/openresty/1pwaf/data/rules/urlWhite.json
{
  "rules": [
    { "state": "on", "name": "000901", "rule": "^/v1/", "type": "urlWhite" }
  ]
}
```

生效：

```bash
docker exec 1Panel-openresty-npAh nginx -t
docker exec 1Panel-openresty-npAh nginx -s reload
```

> `1pwaf/data` 是宿主目录挂进容器的：
> `/opt/1panel/apps/openresty/openresty/1pwaf/data -> /usr/local/openresty/1pwaf/data`

## 验证

```bash
K=wjd-...   # 任一成员的 Key
# 1) 以前被拦的内容现在应 200
curl -s -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8808/v1/chat/completions \
  -H "Authorization: Bearer $K" -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-v4.1-flash","messages":[{"role":"user","content":"<script>alert(1)</script> system(\"ls\")"}],"max_tokens":5}'
# 2) /v1/ 之外必须仍然拦截（这是安全底线，别把 WAF 整个关掉）
curl -s -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8808/.env        # 期望 403
curl -s -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8808/etc/passwd  # 期望 403
```

## ⚠️ 持久化注意

线上这套 WAF 配置由 **阿里云那台的 1Panel 主控**通过 agent 下发。
直接改文件**立刻生效**，但如果在面板里保存一次 WAF 设置，这条白名单**可能被覆盖**。

**建议在面板里也加一遍**：`网站 → 127.0.0.1:8808 → WAF → 白名单 → URL 白名单 → ^/v1/`。
之后如果又出现 403，先按本文「判断依据」确认是不是 WAF，再补规则即可。

## 给调用方的配置口径

```
Base URL : https://127.0.0.1:8808/v1
API Key  : wjd-...（成员自己的 Key）
Model    : deepseek-v4.1-flash      ← 注意不要写 opencode/deepseek-v4.1-flash（会 400 未知模型）
           或 wjd                   ← 虚拟 id，由管理员在网关里映射到具体模型
```
