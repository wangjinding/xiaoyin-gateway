#!/usr/bin/env bash
# 在 Firecracker microVM（Kata）里跑智能体；对外仍暴露 127.0.0.1:8899
# 两条隧道：VM→网关(10.88.0.1:8808)、宿主/nginx→VM(127.0.0.1:8899)
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
VM_IP="${DSH_VM_IP:-10.88.0.3}"
VM_PORT=8899
NAME=xiaoyin-agent-vm
STATE="$PWD/home/state"

mkdir -p "$STATE"
rm -f "$STATE/web-token" "$STATE/web-port"

# ── 1. 隧道 ──────────────────────────────────────────────────────
# 只杀自己记过 PID 的 socat —— 绝不能按端口杀（8808 是网关本体，杀了会被 supervisor 重启，抖动）
for f in "$STATE/socat-gw.pid" "$STATE/socat-web.pid"; do
  [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true
  rm -f "$f"
done
sleep 1
# VM → 网关（只绑网桥地址，外部访问不到）
setsid socat TCP-LISTEN:8808,bind=10.88.0.1,fork,reuseaddr TCP:127.0.0.1:8808 \
  >/tmp/dsh-vm-socat-gw.log 2>&1 < /dev/null &
echo $! > "$STATE/socat-gw.pid"
# 宿主/nginx → VM
setsid socat TCP-LISTEN:8899,bind=127.0.0.1,fork,reuseaddr TCP:"$VM_IP":8899 \
  >/tmp/dsh-vm-socat-web.log 2>&1 < /dev/null &
echo $! > "$STATE/socat-web.pid"

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

# VM 版模型覆盖层：baseURL 指向网桥网关（缺失时生成）
if [ ! -s home/profiles/gateway/providers.vm.yml ]; then
  XIAOYIN_GATEWAY_KEY="$KEY" python3 sync-providers.py >/dev/null 2>&1 || true
  sed 's#http://127.0.0.1:8808/v1#http://10.88.0.1:8808/v1#g' \
      home/profiles/gateway/providers.gen.yml \
      > home/profiles/gateway/providers.vm.yml 2>/dev/null || true
fi

# 清理上次异常退出留下的残留：陈旧的 nerdctl 名字记录 + CNI 固定 IP 占用
# （不清理会报 "name is already used" 或新容器拿不到 IP，VM 里只剩 lo）
rm -f /var/lib/nerdctl/*/names/default/"$NAME" 2>/dev/null || true
rm -f /var/lib/cni/networks/agent-net/"$VM_IP" 2>/dev/null || true

nerdctl rm -f "$NAME" >/dev/null 2>&1 || true
nerdctl run -d --name "$NAME" \
  --runtime io.containerd.kata.v2 --network agent-net --ip "$VM_IP" \
  --memory 1536m --cpus 2 \
  -v "$PWD:/app-ro:ro" \
  -v "$PWD/vm-home:/home-dsh" \
  -e DSH_HOME=/home-dsh -e XIAOYIN_GATEWAY_KEY="$KEY" \
  docker.io/library/node:22-slim /app-ro/vm-entrypoint.sh >/dev/null

# ── 3. 等 token（VM 日志里打印）──────────────────────────────────
for i in $(seq 1 60); do
  sleep 2
  TOK="$(nerdctl logs "$NAME" 2>&1 | tr -d '\r' | { grep -oE 'token=[A-Za-z0-9_-]+' || true; } | tail -1 | cut -d= -f2)"
  if [ -n "${TOK:-}" ]; then
    printf '%s' "$TOK" > "$STATE/web-token"
    printf '%s' "$VM_PORT" > "$STATE/web-port"
    python3 -c "import sys; sys.path.insert(0,'$REPO'); from scripts.ports import write_port; write_port('agent', $VM_PORT)" 2>/dev/null || true
    # nginx 上游可能停留在旧的随机端口 → 每次启动同步一次
    python3 "$REPO/scripts/sync-nginx-ports.py" >/dev/null 2>&1 || true
    echo "[agent-vm] 就绪：VM $VM_IP:$VM_PORT（第 $((i*2)) 秒）"
    exit 0
  fi
  if ! nerdctl ps --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; then
    echo "[agent-vm] 容器已退出，日志：" >&2
    nerdctl logs "$NAME" 2>&1 | tail -20 >&2
    exit 1
  fi
done
echo "[agent-vm] 120 秒内没等到 token" >&2
nerdctl logs "$NAME" 2>&1 | tail -20 >&2
exit 1

# ── 4. 看护：容器退出就重启自己（supervisor 负责再把脚本拉起来）────────
echo "[agent-vm] 进入看护循环（每 30 秒检查）"
while sleep 30; do
  if ! nerdctl ps --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; then
    echo "[agent-vm] 容器已退出，重新拉起"
    exec "$0"
  fi
done
