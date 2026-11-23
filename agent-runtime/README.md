# agent-runtime —— 小银网关内嵌的 DeepSeek Harness

这是**网关自带**的一份 DSH 运行时，和系统里那份 `dsh` 完全无关：

- 自己的 `node_modules`（依赖 `@deepseek-ai/dsh`，版本钉死）
- 自己的 `DSH_HOME`（`agent-runtime/home/`）
- 自己的 profile（`home/profiles/agent/`）
- 模型直接指向网关自己的 `/v1`

## 为什么只依赖 `@deepseek-ai/dsh`

npm 上那些独立 bundle 包（`@deepseek-ai/dsh-base@0.0.1-rc.1` 等）**装不上**：
它们依赖 `@deepseek-ai/dsh-bash-env` / `@deepseek-ai/dsh-tasks`，而这两个**没有发布**（404）。

`@deepseek-ai/dsh` 本体内部自带一整套版本对齐的 bundle（`dsh-base` / `dsh-headless` /
`dsh-llm-pi-ai` …），profile 从本体解析即可。**不要**把 bundle 包写成顶层依赖。

## 安装

```bash
cd agent-runtime
npm ci            # 或首次：npm install
```

依赖约 1.2GB，**不进版本库**（见 .gitignore），部署时跑一次。

## 跑一次

```bash
cd agent-runtime
export DSH_HOME="$PWD/home"
export XIAOYIN_GATEWAY_KEY="<网关的 agent-engine key>"
./node_modules/.bin/dsh --profile agent headless --json "你好"
```

输出是 NDJSON 事件流（`session` / `status` / `thinking` / `tool_call` / `tool_result` /
`text` / `final`），网关的 `app/adapters/dsh_engine.py` 把它翻译成前端事件。

## 端口是动态的

部署时端口可能被占用，所以运行时**不写死端口**：

- `DSH_WEB_PORT` 是**首选**端口（默认 8899）；被占用就自动换一个
- 实际端口写到 `home/state/web-port` 和 `data/ports.json`
- nginx 的 `/agent/` 上游由 `scripts/sync-nginx-ports.py` 按上表改写并 reload
  （supervisor 里 `xiaoyin-port-sync` 每 15 秒检查一次，端口没变就不动）
- 网关同理：`GATEWAY_PORT=auto` 时先试配置里的 `server.port`，占了才换；
  实际端口写进 `data/ports.json` → nginx 的 `/` 上游同步更新

⚠️ profile 的 `cordis.patch.yml` 里**不要**写 `webserver.port` —— 它的优先级高于命令行
`--port`，会把动态端口覆盖成死值（踩过：占住 8899 后运行时起不来、反复重启）。

## 模型按运营商分组

DSH 的模型选择器**原生按 provider 分组**（`state.groups`，`group.id` 就是 provider id）。
`sync-providers.py` 读网关自己的 `data/gateway.yaml`，按供应商生成覆盖层：

```
1min.AI (44) / Agnes AI (10) / OpenCode Go (26) / Dots AI (1) / 小银网关（其他）(1)
```

- 所有 provider 的 `baseURL` 都指向网关 `/v1`，分组只影响显示，路由仍由网关按 model id 决定
- 输出 `home/profiles/gateway/providers.gen.yml`，`run-web.sh` 启动时自动生成并用 `--patch` 叠加
- **改了网关供应商/模型后重启 `xiaoyin-dsh` 即可同步**（不需要手改这个文件）

## 二次开发放哪

| 想加什么 | 位置 |
|---|---|
| 自定义工具（plugin） | `plugins/<name>/`，在 profile 的 `cordis.patch.yml` 里 `insert` |
| 人格 / 系统提示 | profile 的 prompt 配置，或工作区的 `SOUL.md` |
| 权限 | 启动参数 `--permission-mode` / `--approval-policy` |
| 模型 | 网关后台「智能体 → 模型」，适配器会写 `model-overlay.yml` 覆盖 |

## 目录说明

```
agent-runtime/
├── package.json / package-lock.json   依赖锁定
├── node_modules/                      1.2GB，不进库
├── home/                              DSH_HOME
│   ├── profiles/agent/                profile（进库）
│   ├── state/sessions.json            网关会话 → DSH 会话 映射（不进库）
│   ├── workspaces/<slug>/             智能体的工作区（不进库）
│   └── storages/                      会话持久化（不进库）
└── plugins/                           二开入口
```
