# agent-runtime —— 小银智能体 + Firecracker VM

**2026-11-24 起，DSH 已从 VM 里彻底移除**（代码、node_modules、profile、会话都不在了），
VM 里只跑自研的「小银智能体」（独立项目 `/root/dsh/projects/xiaoyin-agent`）。

| 项 | 值 |
|---|---|
| 进程 | **一个** Node 进程（VM PID 1），多会话 |
| 隔离 | `setpriv --reuid=<用户 uid>`，读写都由内核管 |
| 内存 | ~200 MB（原 DSH 每用户 500 MB） |
| 端口 | VM 8901 → 隧道 `127.0.0.1:8902` → nginx `/agent/` |

## 目录分工

```
agent-runtime/
├── run-vm.sh              启动 VM + 两条 socat 隧道 + 同步 nginx 上游
├── vm-entrypoint.sh       VM 内入口：补系统用户 → 起小银智能体
├── dsh-compat/            DSH 兼容垫片（挂到 VM 的 /home-dsh/node_modules）
│   └── @deepseek-ai/{dsh-tools,dsh-credentials}
├── vm-home/               挂到 VM 的 /home-dsh
│   └── agent-app/         小银智能体运行副本（src/web/skills/plugins/data）
├── vm-workspaces/         挂到 VM 的 /workspace（各用户工作区，700）
├── dsh-compat 挂载        /home-dsh/node_modules（只读）
├── 宿主技能                /root/.dsh/skills → /home-dsh/dsh-skills（只读）
└── 宿主插件                /root/.dsh/profiles/web/local → /home-dsh/dsh-plugins（只读）
```

## 与 DSH 的兼容

| 资源 | 兼容方式 | 说明 |
|---|---|---|
| **技能** | 直接读 `SKILL.md` | 扫描 `dsh-skills/`，`use_skill` 按需加载正文 |
| **插件** | 垫片提供最小 `ctx` | 支持 `apply(ctx)`、`ctx.tools.register`、`ctx.credentials`、`ctx.logger`、`ctx.effect` |
| **工具定义** | `defineTool` 垫片 | DSH 的「属性映射」参数自动转 JSON Schema |

**已实测可加载**：`dsh-agnes-media`、`dsh-comfyui`、`dsh-cwd-compat`、`dsh-opencode-usage`。

**不兼容**（需要 DSH 运行时服务）：
- 依赖 `ctx.webServer` 设置页的交互（路由被跳过，工具仍注册）
- 依赖 `searchProvider`、`subagent`、`session` 等服务的插件（如 `dsh-web-search-free` 会加载失败）
- 插件里写死宿主路径的脚本：VM 里只有挂载进来的目录

## 目录分工

```
agent-runtime/
├── run-vm.sh                 启动 VM（Kata/Firecracker）+ socat 隧道 + nginx 同步
├── vm-entrypoint.sh          VM 内入口：优先起 /home-dsh/agent-app（小银智能体）
├── vm-home/                  挂到 VM 的 /home-dsh（智能体代码、数据、技能、插件）
│   └── agent-app/            ← 小银智能体的运行副本（由 xiaoyin-agent 项目同步）
├── vm-workspaces/            挂到 VM 的 /workspace（各用户工作区，700）
├── home/                     宿主直跑模式用的 DSH_HOME（回退时用）
└── supervisor/xiaoyin-dsh.ini.example
```

## 多用户是怎么隔离的

```
宿主：网关 /agents/entry → 按登录用户发 token，首次访问自动在 VM 里建系统用户
VM  ：小银智能体（单进程，root）
        └─ 每次工具调用：setpriv --reuid=<该用户 uid> ...（cwd = /workspace/<user>）
             /workspace/<user> 是 700，别人（不同 uid）连目录都进不去
```

| 想限制 | 靠什么 |
|---|---|
| 读别人工作区 | 内核（uid + 700） |
| 写别人工作区 | 内核 |
| 看别人会话 | 会话按用户分目录，700；管理端用 root 读 |
| 连别人实例 | 不是多实例——根本没这回事 |

---


网关「智能体」页内嵌的那套 DSH 就住在这个目录。它和宿主机上系统级的那份 `dsh` **完全无关**：

- 自己的 `node_modules`（只依赖 `@deepseek-ai/dsh`，版本钉死）
- 自己的 `DSH_HOME`（`agent-runtime/home/` 或 VM 里的 `/home-dsh`）
- 自己的 profile（`home/profiles/gateway/`）
- 模型不走公网，直接打网关自己的 `/v1`

## 两种运行方式

| 方式 | 脚本 | 隔离级别 | 说明 |
|---|---|---|---|
| **VM（默认）** | `run-vm.sh` | Firecracker microVM（独立内核） | 智能体跑在微型虚拟机里，看不到宿主任何文件 |
| 宿主直跑（备选） | `run-web.sh` | 进程级（无隔离） | 老方式，VM 装不起来时兜底用 |

> 只支持 Linux + KVM。没有 KVM 的机器用宿主直跑，**但那样智能体能读到 `/root` 下所有文件**。

## 为什么只依赖 `@deepseek-ai/dsh`

npm 上那些独立 bundle 包（`@deepseek-ai/dsh-base@0.0.1-rc.1` 等）**装不上**：
它们依赖 `@deepseek-ai/dsh-bash-env` / `@deepseek-ai/dsh-tasks`，而这两个**没有发布**（404）。

`@deepseek-ai/dsh` 本体内部自带一整套版本对齐的 bundle（`dsh-base` / `dsh-web-app` /
`dsh-headless` / `dsh-llm-pi-ai`），profile 从本体解析即可。**不要**把 bundle 包写成顶层依赖。

---

# 部署（VM 版，从零）

## 0. 前置条件

| 项 | 要求 |
|---|---|
| 系统 | Linux x86_64，内核 ≥ 5.10 |
| 虚拟化 | `/dev/kvm` 可写；虚拟机里部署需要 `kvm_intel.nested=1` |
| 内存 | 智能体 VM 默认 1.5 GB，宿主建议 ≥ 4 GB 空闲 |
| 磁盘 | `/opt/kata` 约 2.1 GB + 镜像 |
| 网络 | 需要访问 GitHub（下载 Firecracker / Kata / nerdctl / CNI） |

## 1. 装依赖

```bash
cd agent-runtime
npm ci                       # 依赖约 1.2 GB，不进版本库
```

## 2. 装 VM 宿主组件

```bash
sudo ./install-vm-host.sh --check   # 先体检，看缺什么
sudo ./install-vm-host.sh           # 安装/补齐（幂等，可重复跑）
```

脚本做七件事：`socat/curl/zstd` → 检查 KVM → 装 Firecracker → 解压 Kata（约 1 GB）→
把 Kata 配成 Firecracker 后端 → 装 nerdctl + CNI 插件 → 建网桥 `agent-net` 并放行 VM→网关。

> 国外站点走代理：脚本默认 `HTTPS_PROXY=http://127.0.0.1:10809`，可用环境变量覆盖。

## 3. 启动

```bash
export XIAOYIN_GATEWAY_KEY="<网关 agent-engine key>"   # 不传就从 data/users.json 里找
./run-vm.sh
```

成功会打印：

```
[agent-vm] 就绪：VM 10.88.0.3:8899（第 22 秒）
```

脚本会：起两条 socat 隧道 → 建 VM（只读挂载代码、独立 home、独立 workspace）→
从日志里抓 `?token=` 写进 `home/state/web-token` → 更新 `data/ports.json` → 同步 nginx 上游 →
进入看护循环（容器掉了自动重拉）。

## 4. 开机自启（supervisor）

```ini
[program:xiaoyin-dsh]
command=/opt/xiaoyin-gateway/agent-runtime/run-vm.sh
directory=/opt/xiaoyin-gateway/agent-runtime
autostart=true
autorestart=true
startsecs=15
stdout_logfile=/opt/1panel/tools/supervisord/log/xiaoyin-dsh.out.log
stderr_logfile=/opt/1panel/tools/supervisord/log/xiaoyin-dsh.err.log
```

示例文件：`supervisor/xiaoyin-dsh.ini.example`

```bash
cp agent-runtime/supervisor/xiaoyin-dsh.ini.example \
   /opt/1panel/tools/supervisord/supervisor.d/xiaoyin-dsh.ini
supervisorctl -c /etc/supervisor/supervisord.conf reread && \
supervisorctl -c /etc/supervisor/supervisord.conf update
```

## 5. 验证

```bash
# VM 是否在跑
nerdctl ps | grep xiaoyin-agent-vm

# 宿主→VM 隧道（期望 401 = 活着但要 token）
curl -s -o /dev/null -w '%{http_code}\n' --noproxy '*' http://127.0.0.1:8899/

# 公网入口（期望 303）
TOKEN=$(cat agent-runtime/home/state/web-token)
curl -s -o /dev/null -w '%{http_code}\n' "https://api.wangjinding.com/agent/?token=$TOKEN"

# 隔离验证：VM 里应该看不到宿主文件
nerdctl exec xiaoyin-agent-vm ls /root 2>&1 | head -1   # 期望看不到宿主内容
```

---

## 网络拓扑

```
浏览器 ──https──→ nginx /agent/ ──→ 127.0.0.1:8899 (socat)
                                        │
                                        ▼
                            ┌───────────────────────────┐
                            │  Firecracker microVM      │
                            │  eth0 10.88.0.3           │
                            │  ┌─────────────────────┐  │
                            │  │ DSH :8899           │  │
                            │  │ /app-ro   代码只读  │  │
                            │  │ /home-dsh 会话/配置 │  │
                            │  │ /workspace 工作区   │  │
                            │  └─────────────────────┘  │
                            └───────────┬───────────────┘
                                        │ 10.88.0.1:8808
                                        ▼
                            socat → 127.0.0.1:8808（小银网关）
```

两条隧道 **都只绑回环/网桥**，不对外：

| 隧道 | 监听 | 转发到 | 用途 |
|---|---|---|---|
| VM → 网关 | `10.88.0.1:8808` | `127.0.0.1:8808` | 智能体调模型 |
| 宿主 → VM | `127.0.0.1:8899` | `10.88.0.3:8899` | nginx 反代 |

防火墙只在网桥接口放行 `10.88.0.0/24 → 8808`（1Panel 的 INPUT 链默认会拦网桥来的包）。

## 端口是动态的

- `DSH_VM_IP` 可覆盖 VM 地址（默认 `10.88.0.3`），VM 内固定监听 `8899`
- 网关侧仍是动态的：`GATEWAY_PORT=auto` 先试配置里的 `server.port`，占了才换，
  实际端口写进 `data/ports.json`
- nginx 上游由 `scripts/sync-nginx-ports.py` 改写到 `127.0.0.1:<port>` 并 reload
- **同步时机：`run-vm.sh` / `run.py` 各自启动时各跑一次**，不常驻守护

⚠️ profile 的 `cordis.patch.yml` 里**不要**写 `webserver.port` —— 优先级高于命令行
`--port`，会把动态端口覆盖成死值（踩过：占住 8899 后运行时起不来、反复重启）。

## 权限档位

VM 里已和宿主硬件级隔离，所以三档都开着（`home/profiles/gateway/cordis.patch.yml`）：

| 档位 | 沙箱 | 说明 |
|---|---|---|
| 只读模式 | `read-only` | 不改任何文件 |
| 标准模式 | `workspace-write` | 只能写工作区 |
| **完全访问（默认）** | `danger-full-access` | 不限读写（仅限 VM 内） |

设置入口：智能体界面 → `更多` → `设置` → `通用设置` → `权限`。

> 注意：DSH 的沙箱**只管写不管读**。宿主直跑方式下「标准模式」挡不住 `cat .env`——
> 这正是改成 VM 的原因。

## 模型按运营商分组

DSH 的模型选择器**原生按 provider 分组**（`state.groups`，`group.id` 就是 provider id）。
`sync-providers.py` 读网关的 `data/gateway.yaml`，按供应商生成覆盖层：

```
1min.AI (44) / Agnes AI (10) / OpenCode Go (26) / Dots AI (1) / 小银网关（其他）(1)
```

- 所有 provider 的 `baseURL` 都指向网关 `/v1`，分组只影响显示，路由由网关按 model id 决定
- 宿主直跑用 `providers.gen.yml`（`127.0.0.1:8808`）；VM 用 `providers.vm.yml`（`10.88.0.1:8808`）
- 两个文件都是生成物，**不进版本库**；VM 版在缺失时由 `run-vm.sh` 自动生成
- 改了网关供应商/模型后重启 `xiaoyin-dsh` 即可同步

## 二次开发放哪

| 想加什么 | 位置 |
|---|---|
| 自定义工具（plugin） | `plugins/<name>/`，在 profile 的 `cordis.patch.yml` 里 `insert` |
| 人格 / 系统提示 | profile 的 prompt 配置，或工作区的 `SOUL.md` |
| 权限 | 设置页（写回 `cordis.patch.yml` 的 `permission` 块） |
| 模型 | 智能体界面右上角模型选择器 |

## 目录说明

```
agent-runtime/
├── package.json / package-lock.json   依赖锁定
├── node_modules/                      1.2GB，不进库
├── install-vm-host.sh                 装 VM 宿主组件（幂等）
├── run-vm.sh                          ★ 启动 VM 版智能体（默认）
├── vm-entrypoint.sh                   VM 内的入口（只读代码 + 独立 home）
├── run-web.sh                         宿主直跑（备选）
├── sync-providers.py                  生成模型覆盖层
├── supervisor/xiaoyin-dsh.ini.example supervisor 配置样例
├── plugins/                           二开入口
├── home/                              宿主侧 DSH_HOME（直跑用）
│   └── profiles/gateway/              profile（进库）
├── vm-home/                           VM 侧 DSH_HOME（会话/配置，不进库）
├── vm-workspaces/                     用户工作区（宿主挂载到 /workspace，不进库）
└── vm-workspace/                      （可选）宿主侧 vs VM 工作区共享目录
```

## 排错速查

| 症状 | 原因 / 处理 |
|---|---|
| `--host 0.0.0.0 is an unspecified address` | DSH 拒绝通配监听，入口脚本已改成绑 VM 的 eth0 IP |
| 界面一直「重新连接中」 | 少了 `--trusted-host api.wangjinding.com`（浏览器从公网域名进来） |
| `/agent/` 502，但 `curl 127.0.0.1:8899` 正常 | nginx 上游停在旧端口 → `python scripts/sync-nginx-ports.py` |
| VM 里 `ping 10.88.0.1` 通但 8808 连不上 | 1Panel INPUT 链拦了网桥包 → 重跑 `install-vm-host.sh` 补 iptables 规则 |
| `run-vm.sh` 突然什么都不输出就退出 | `set -euo pipefail` + `grep` 无匹配 → 管道后面要带 `|| true` |
| 想清理 VM | `nerdctl rm -f xiaoyin-agent-vm`（工作区在 `vm-home/`，不会丢） |

## 安全边界（重要）

| 能做到 | 做不到 |
|---|---|
| VM 里看不到宿主文件系统、进程树 | VM 仍能访问网关 `10.88.0.1:8808`（必须） |
| 代码只读挂载，改不了源码 | 密钥 `XIAOYIN_GATEWAY_KEY` 在 VM 环境变量里（只能调网关） |
| 崩了删容器重建即回滚 | 内核级逃逸漏洞（需 hypervisor 漏洞，代价极高） |

> 铁律：**上游供应商的 Key（`data/.env`）永远不进 VM**。VM 里只有一把可吊销的网关 Key。

### 智能体的 Key 必须是 member 角色

智能体持有的网关 Key **不能**建在 `admin` 账号下 —— 网关有不少管理员接口
（如 `GET /config` 会返回各供应商 Key），admin 身份会让「VM 隔离」形同虚设。

正确做法：给智能体单独建一个 `member` 角色账号，只铸一把 Key：

```bash
# 账号管理页：用户管理 → 新建 agent（角色 member）→ 给它铸一把 Key（label: agent-engine）
# 或直接查：run-vm.sh 会自动从 data/users.json 里找 label=agent-engine 的那把
```

校验：VM 里用它自己的 Key 打 `/config` 应当 **403**，打 `/v1/models` 应当 **200**。
