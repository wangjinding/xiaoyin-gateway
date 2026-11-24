#!/usr/bin/env bash
# 在 Firecracker microVM（Kata）里跑「小银智能体」；对外暴露 127.0.0.1:8902
# 两条隧道：VM→网关(10.88.0.1:8808)、宿主/nginx→VM(127.0.0.1:8901)
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
VM_IP="${AGENT_VM_IP:-10.88.0.3}"
VM_PORT=8901
NAME=xiaoyin-agent-vm
STATE="$PWD/state"

mkdir -p "$STATE"
rm -f "$STATE/agent-port" "$STATE/web-token" "$STATE/web-port"

# ── 1. 隧道 ──────────────────────────────────────────────────────
# 只杀自己记过 PID 的 socat —— 绝不能按端口杀（8808 是网关本体，杀了会被 supervisor 重启，抖动）
for f in "$STATE/socat-gw.pid" "$STATE/socat-agent.pid"; do
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
  rm -f "$f"
done
sleep 1
# VM → 网关（只绑网桥地址，外部访问不到）
setsid socat TCP-LISTEN:8808,bind=10.88.0.1,fork,reuseaddr TCP:127.0.0.1:8808 \
  >/tmp/agent-vm-socat-gw.log 2>&1 < /dev/null &
echo $! > "$STATE/socat-gw.pid"
# 宿主/nginx → VM
setsid socat TCP-LISTEN:8902,bind=127.0.0.1,fork,reuseaddr TCP:"$VM_IP":8901 \
  >/tmp/agent-vm-socat-web.log 2>&1 < /dev/null &
echo $! > "$STATE/socat-agent.pid"

# 放行 VM 访问网关（幂等；1Panel 的 INPUT 链默认会拦网桥来的包）
BR="$(ip -o -4 addr show 2>/dev/null | awk '/10\.88\.0\.1\//{print $2}' | head -1)"
if [ -n "${BR:-}" ]; then
  iptables -C INPUT -i "$BR" -s 10.88.0.0/24 -p tcp --dport 8808 -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -i "$BR" -s 10.88.0.0/24 -p tcp --dport 8808 -j ACCEPT 2>/dev/null || true
fi

# ── 2. 启动 VM ───────────────────────────────────────────────────
KEY="${XIAOYIN_GATEWAY_KEY:-$(python3 - "$REPO/data/users.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for u in (d.get('users') or {}).values():
        for rec in (u.get('api_keys') or {}).values():
            if isinstance(rec, dict) and rec.get('label') == 'agent-engine':
                print(rec.get('key') or ''); raise SystemExit
except Exception:
    pass
PY
)}"

# 清理上次异常退出留下的残留（不清理会报 "name is already used" 或新容器拿不到 IP）
nerdctl rm -f "$NAME" >/dev/null 2>&1 || true
for _try in 1 2 3 4 5 6 7 8 9 10; do
  nerdctl ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME" || break
  sleep 2
done
# 容器确实没了还报名字冲突 → 说明名字记录陈旧，删掉它
if ! nerdctl ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; then
  rm -f /var/lib/nerdctl/*/names/default/"$NAME" 2>/dev/null || true
fi
# 固定 IP 若被旧容器占着，新容器会拿不到地址（VM 里只剩 lo）
rm -f /var/lib/cni/networks/agent-net/"$VM_IP" 2>/dev/null || true
nerdctl run -d --name "$NAME" \
  --runtime io.containerd.kata.v2 --network agent-net --ip "$VM_IP" \
  --memory 1536m --cpus 2 \
  -v "$PWD:/app-ro:ro" \
  -v "$PWD/vm-home:/home-dsh" \
  -v "$PWD/vm-workspaces:/workspace" \
  -v "/root/.dsh/skills:/home-dsh/dsh-skills:ro" \
  -v "/root/.dsh/profiles/web/local:/home-dsh/dsh-plugins:ro" \
  -v "$PWD/dsh-compat:/home-dsh/node_modules:ro" \
  -e XIAOYIN_GATEWAY_KEY="$KEY" \
  docker.io/library/node:22-slim /app-ro/vm-entrypoint.sh >/dev/null

# ── 3. 等智能体就绪 ──────────────────────────────────────────────
for i in $(seq 1 60); do
  sleep 2
  TOK="$(nerdctl exec "$NAME" sh -c 'wget -q -O- --timeout=2 http://127.0.0.1:8901/api/me >/dev/null 2>&1 && echo up' 2>/dev/null || true)"
  if [ -n "${TOK:-}" ]; then
    printf '%s' "$VM_PORT" > "$STATE/agent-port"
    python3 -c "import sys; sys.path.insert(0,'$REPO'); from scripts.ports import write_port; write_port('agent', $VM_PORT)" 2>/dev/null || true
    # nginx 上游可能停留在旧的随机端口 → 每次启动同步一次
    python3 "$REPO/scripts/sync-nginx-ports.py" >/dev/null 2>&1 || true
    echo "[agent-vm] 就绪：小银智能体 VM $VM_IP:$VM_PORT（第 $((i*2)) 秒）"
    READY=1
    break
  fi
  if ! nerdctl ps --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; then
    echo "[agent-vm] 容器已退出，日志：" >&2
    nerdctl logs "$NAME" 2>&1 | tail -20 >&2
    exit 1
  fi
done
if [ "${READY:-0}" != "1" ]; then
  echo "[agent-vm] 120 秒内智能体没起来" >&2
  nerdctl logs "$NAME" 2>&1 | tail -20 >&2
  exit 1
fi

# ── 4. 看护：容器退出就重启自己（supervisor 负责再把脚本拉起来）────────
echo "[agent-vm] 进入看护循环（每 30 秒检查）"
while sleep 30; do
  if ! nerdctl ps --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; then
    echo "[agent-vm] 容器已退出，重新拉起"
    exec "$0"
  fi
done
