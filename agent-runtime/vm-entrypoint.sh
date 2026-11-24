#!/bin/sh
# 在 Firecracker microVM 里启动 DSH：代码只读挂载，home 用 VM 内的独立卷
set -e
SRC=/app-ro
: "${DSH_HOME:=/home-dsh}"
export DSH_HOME
export NO_COLOR=1

mkdir -p "$DSH_HOME/state" /workspace
# 首次启动：把 profile 从只读代码目录复制进可写 home
if [ ! -d "$DSH_HOME/profiles/gateway" ]; then
  cp -r "$SRC/home/profiles" "$DSH_HOME/" 2>/dev/null || true
fi
# VM 里没有宿主路径：把工作区根改到 VM 内的 /workspace
sed -i 's#workspaceRoot: .*#workspaceRoot: /workspace#' "$DSH_HOME/profiles/gateway/cordis.patch.yml" 2>/dev/null || true

# 首次启动：把 VM 内的 /workspace 注册为默认工作区（否则界面要手动选目录）
WS="$DSH_HOME/storages/workspace.json"
if [ ! -f "$WS" ]; then
  mkdir -p "$DSH_HOME/storages"
  NOW="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
  cat > "$WS" <<EOF
{
  "unit": { "name": "workspace", "version": 2 },
  "global": { "initialized": true, "workspaceIds": ["ws-local-1"],
              "archivedSessionIds": [], "pinnedSessionIds": [] },
  "tables": { "workspaces": { "ws-local-1": {
      "path": "/workspace", "title": "workspace", "sessionIds": [],
      "createdAt": "$NOW", "updatedAt": "$NOW" } } }
}
EOF
fi

# 优先跑「小银智能体」（自研，单进程多会话）；没有就回退 DSH
if [ -f /home-dsh/agent-app/src/server.js ] && [ "${FORCE_DSH:-0}" != "1" ]; then
  echo "[vm] 启动小银智能体（自研）"
  export AGENT_HOST=0.0.0.0 AGENT_PORT=8901
  export GATEWAY_KEY="${GATEWAY_KEY:-$XIAOYIN_GATEWAY_KEY}"
  export TZ=Asia/Shanghai
  # 容器每次重建都会丢系统用户 → 启动时按 users.json 补齐（幂等）
  node -e '
    const fs = require("fs");
    const { execSync } = require("child_process");
    let users = {};
    try { users = JSON.parse(fs.readFileSync("/home-dsh/agent-app/data/users.json", "utf8")); } catch {}
    for (const [name, u] of Object.entries(users)) {
      if (!u.uid) continue;
      try {
        execSync(`id -u ${name} >/dev/null 2>&1 || useradd -M -u ${u.uid} -s /bin/sh ${name}`, { stdio: "ignore" });
        execSync(`mkdir -p ${u.workspace} && chown -R ${name}:${name} ${u.workspace} && chmod 700 ${u.workspace} && chmod 711 /workspace`, { stdio: "ignore" });
        console.log(`[vm] 用户就绪 ${name} (uid ${u.uid})`);
      } catch (e) { console.error(`[vm] 用户 ${name} 初始化失败: ${e.message}`); }
    }
  '
  echo "[vm] 启动小银智能体（自研）"
  export GATEWAY_BASE="${GATEWAY_BASE:-http://10.88.0.1:8808/v1}"
  exec node /home-dsh/agent-app/src/server.js
fi
echo "[vm] 回退到 DSH"

# DSH 拒绝 0.0.0.0（会检测通配地址），绑定 VM 自己的 eth0 地址
# 读 VM 自己的 eth0 地址（容器刚起时网卡可能还没配好 → 重试最多 15 秒）
VMIP=""
for _i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  VMIP="$(node -e "const n=require('os').networkInterfaces();const e=n.eth0||[];const v4=e.find(x=>x.family==='IPv4'||x.family===4);console.log(v4?v4.address:'')" 2>/dev/null)"
  [ -n "$VMIP" ] && break
  sleep 1
done
if [ -z "$VMIP" ]; then
  echo "[vm] 警告：没拿到 eth0 地址，退回 127.0.0.1（宿主将无法访问）"
  VMIP=127.0.0.1
fi
echo "[vm] 绑定地址 $VMIP:8899"

cd "$SRC"
exec ./node_modules/.bin/dsh \
  --patch "$SRC/home/profiles/gateway/providers.vm.yml" \
  --profile gateway --host "$VMIP" --port 8899 --no-open \
  --trusted-host "$VMIP:8899" --trusted-host 10.88.0.1:8899 \
  --trusted-host 127.0.0.1:8899 --trusted-host api.wangjinding.com
