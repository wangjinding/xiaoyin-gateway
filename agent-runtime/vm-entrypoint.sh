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

# DSH 拒绝 0.0.0.0（会检测通配地址），绑定 VM 自己的 eth0 地址
# node:22-slim 没有 iproute2 → 用 node 自己读网卡地址
VMIP="$(node -e "const n=require('os').networkInterfaces();const e=n.eth0||[];const v4=e.find(x=>x.family==='IPv4'||x.family===4);console.log(v4?v4.address:'')" 2>/dev/null)"
: "${VMIP:=127.0.0.1}"
echo "[vm] 绑定地址 $VMIP:8899"

cd "$SRC"
exec ./node_modules/.bin/dsh \
  --patch "$SRC/home/profiles/gateway/providers.vm.yml" \
  --profile gateway --host "$VMIP" --port 8899 --no-open \
  --trusted-host "$VMIP:8899" --trusted-host 10.88.0.1:8899 \
  --trusted-host 127.0.0.1:8899 --trusted-host api.wangjinding.com
