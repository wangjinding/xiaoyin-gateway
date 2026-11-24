#!/bin/sh
# 在 Firecracker microVM 里启动「小银智能体」
# 代码在 /app-ro（只读），数据在 /home-dsh（宿主挂载），工作区在 /workspace（宿主挂载）
set -e
export NO_COLOR=1
export AGENT_HOST=0.0.0.0
export AGENT_PORT=8901
export GATEWAY_KEY="${GATEWAY_KEY:-$XIAOYIN_GATEWAY_KEY}"
export GATEWAY_BASE="${GATEWAY_BASE:-http://10.88.0.1:8808/v1}"
export TZ=Asia/Shanghai

mkdir -p /home-dsh/state /workspace

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

echo "[vm] 启动小银智能体"
exec node /home-dsh/agent-app/src/server.js
