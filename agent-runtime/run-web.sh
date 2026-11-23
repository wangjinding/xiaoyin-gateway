#!/usr/bin/env bash
# 启动「完整 DSH Web 版」。
#   · 端口默认由系统分配（DSH_WEB_PORT=0），避免部署时端口被占用；
#     实际端口写到 home/state/web-port 和 data/ports.json，nginx 据此生成反代。
#   · token 落盘（home/state/web-token），供网关 /agent 引导跳转。
set -euo pipefail
cd "$(dirname "$0")"

PREFER_PORT="${DSH_WEB_PORT:-8899}"   # 首选端口；被占用就自动换一个
HOST="${DSH_WEB_HOST:-127.0.0.1}"
PUBLIC_URL="${DSH_PUBLIC_URL:-}"    # 留空 = 用监听地址（相对路径，反代下也能用）
TRUSTED_RAW="${DSH_TRUSTED_HOST:-api.wangjinding.com}"

REPO="$(cd .. && pwd)"
export DSH_HOME="$PWD/home"

# ── 网关 key：优先环境变量，否则从网关数据里按 label 取 ──────────────
if [ -z "${XIAOYIN_GATEWAY_KEY:-}" ]; then
  XIAOYIN_GATEWAY_KEY="$(python3 - "$REPO/data/users.json" <<'PY'
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
)"
  export XIAOYIN_GATEWAY_KEY
fi

STATE="$DSH_HOME/state"
TOKEN_FILE="$STATE/web-token"
PORT_FILE="$STATE/web-port"
mkdir -p "$STATE"
rm -f "$TOKEN_FILE" "$PORT_FILE"

# ── 按网关的供应商分组生成 provider 覆盖层（模型选择器据此分组显示）────
if [ -x ./sync-providers.py ]; then
  ./sync-providers.py || echo "⚠ 供应商分组生成失败，继续用基础配置" >&2
fi

# ── 把网关的实际端口也加进受信主机（nginx 用 127.0.0.1:<网关端口> 回源）──
GW_PORT="$(python3 -c "import sys; sys.path.insert(0,'$REPO'); from scripts.ports import read_ports; print(read_ports().get('gateway',''))" 2>/dev/null || true)"
TRUSTED="$TRUSTED_RAW"
[ -n "$GW_PORT" ] && TRUSTED="$TRUSTED,127.0.0.1:$GW_PORT"
TRUST_ARGS="$(for h in ${TRUSTED//,/ }; do printf -- "--trusted-host %s " "$h"; done)"

OVERLAY="$DSH_HOME/profiles/gateway/providers.gen.yml"
PATCH_ARGS=""
[ -f "$OVERLAY" ] && PATCH_ARGS="--patch $OVERLAY"

PUB_ARGS=""
[ -n "$PUBLIC_URL" ] && PUB_ARGS="--public-url $PUBLIC_URL"

# 先算一个真能用的端口（dsh 自己不会退让：端口占了会直接失败）
PORT="$(python3 -c "import sys; sys.path.insert(0,'$REPO'); from scripts.ports import pick_port; print(pick_port($PREFER_PORT))" 2>/dev/null || echo "$PREFER_PORT")"

# 端口是我们算好传给 dsh 的，直接落盘（日志里若给了 public-url，打印的是域名，解析不出端口）
printf '%s' "$PORT" > "$PORT_FILE"
python3 -c "import sys; sys.path.insert(0,'$REPO'); from scripts.ports import write_port; write_port('agent', int('$PORT'))" 2>/dev/null || true

echo "--- $(date '+%F %T') 启动 dsh web (首选 ${PREFER_PORT}，实际 ${PORT}) ---"

# ── 启动；从输出里抓端口与 token ────────────────────────────────────
exec ./node_modules/.bin/dsh $PATCH_ARGS --profile gateway \
  --host "$HOST" --port "$PORT" --no-open $PUB_ARGS $TRUST_ARGS \
  > >(tee -a /tmp/xiaoyin-dsh-web.log | while IFS= read -r line; do
        printf '%s\n' "$line"
        case "$line" in
          *'dsh web: http'*)
            # 形如：dsh web: http://127.0.0.1:43217/?token=xxxx
            _url="${line#*dsh web: }"
            _hostport="${_url#*://}"; _hostport="${_hostport%%/*}"
            _port="${_hostport##*:}"
            if [ -n "$_port" ] && [ "$_port" != "$_hostport" ]; then
              printf '%s' "$_port" > "$PORT_FILE"
              python3 -c "import sys; sys.path.insert(0,'$REPO'); from scripts.ports import write_port; write_port('agent', int('$_port'))" 2>/dev/null || true
              echo "[agent-runtime] 实际端口 $_port 已登记" >&2
            fi
            printf '%s' "${line##*?token=}" > "$TOKEN_FILE"
            ;;
        esac
      done) 2>&1
