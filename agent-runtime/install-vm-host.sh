#!/usr/bin/env bash
# 安装「智能体跑在 Firecracker microVM 里」所需的宿主组件（幂等，可重复执行）
#
#   ./install-vm-host.sh          安装/补齐
#   ./install-vm-host.sh --check  只体检，不安装
#
# 组件：Firecracker + Kata Containers（runtime-rs）+ nerdctl + CNI 插件 + socat
set -euo pipefail

KATA_VER="${KATA_VER:-4.4.0}"
FC_VER="${FC_VER:-v1.18.0}"
NERDCTL_VER="${NERDCTL_VER:-v2.4.2}"
CNI_VER="${CNI_VER:-v1.10.0}"
NET_NAME="${NET_NAME:-agent-net}"
NET_SUBNET="${NET_SUBNET:-10.88.0.0/24}"
NET_GW="${NET_GW:-10.88.0.1}"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

# 国外站点一律走代理（用户约定）
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:10809}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:10809}"
export https_proxy="$HTTPS_PROXY" http_proxy="$HTTP_PROXY"

ok()   { printf '  \033[32m✅\033[0m %s\n' "$*"; }
skip() { printf '  \033[36m⏭\033[0m %s\n' "$*"; }
miss() { printf '  \033[33m✗\033[0m %s\n' "$*"; }

need_root() { [ "$(id -u)" = 0 ] || { echo "需要 root"; exit 1; }; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== 1/7 基础依赖 =="
for pkg in socat curl zstd; do
  if have "$pkg" || [ "$pkg" = zstd ] && have unzstd; then skip "$pkg 已安装"
  elif [ $CHECK = 1 ]; then miss "$pkg 缺失"
  else apt-get install -y "$pkg" >/dev/null 2>&1 && ok "已装 $pkg"; fi
done

echo "== 2/7 KVM =="
if [ -w /dev/kvm ]; then ok "/dev/kvm 可用"; else
  miss "/dev/kvm 不可用（需要嵌套虚拟化：kvm_intel.nested=1）"; [ $CHECK = 1 ] || exit 1
fi

echo "== 3/7 Firecracker $FC_VER =="
if [ -x /opt/kata/bin/firecracker ]; then skip "已装 $(/opt/kata/bin/firecracker --version 2>/dev/null | head -1)"
elif [ $CHECK = 1 ]; then miss "未安装"
else
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/fc.tgz" \
    "https://github.com/firecracker-microvm/firecracker/releases/download/${FC_VER}/firecracker-${FC_VER}-x86_64.tgz"
  tar -xzf "$tmp/fc.tgz" -C "$tmp"
  install -D -m 755 "$(find "$tmp" -type f -name "firecracker-${FC_VER}-x86_64" | head -1)" /opt/kata/bin/firecracker
  ok "已装 $(/opt/kata/bin/firecracker --version | head -1)"
fi

echo "== 4/7 Kata Containers $KATA_VER =="
if [ -x /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 ]; then skip "Kata 已解压"
elif [ $CHECK = 1 ]; then miss "未安装（约 1GB 下载）"
else
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  curl -fL --retry 3 -o "$tmp/kata.tar.zst" \
    "https://github.com/kata-containers/kata-containers/releases/download/${KATA_VER}/kata-static-${KATA_VER}-amd64.tar.zst"
  zstd -t "$tmp/kata.tar.zst"
  mkdir -p /opt/kata && tar -I zstd -xf "$tmp/kata.tar.zst" -C "$tmp/x" 2>/dev/null || {
    mkdir -p "$tmp/x" && tar -I zstd -xf "$tmp/kata.tar.zst" -C "$tmp/x"; }
  # 包里是 opt/kata/... 结构，铺平
  src=$(find "$tmp/x" -maxdepth 3 -type d -name bin -printf '%h\n' | head -1)
  cp -a "$src"/. /opt/kata/
  ok "Kata 已解压到 /opt/kata"
fi
ln -sf /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 /usr/local/bin/containerd-shim-kata-v2 2>/dev/null || true

echo "== 5/7 让 Kata 用 Firecracker =="
cfg=/etc/kata-containers/configuration.toml
fc_cfg=/opt/kata/share/defaults/kata-containers/runtime-rs/configuration-rs-fc.toml
if [ -f "$cfg" ] && grep -q '/opt/kata/bin/firecracker' "$cfg" 2>/dev/null; then skip "已是 Firecracker 配置"
elif [ $CHECK = 1 ]; then miss "未配置"
elif [ -f "$fc_cfg" ]; then
  mkdir -p /etc/kata-containers && cp "$fc_cfg" "$cfg" && ok "已写入 $cfg"
else
  miss "找不到 $fc_cfg"; exit 1
fi

echo "== 6/7 nerdctl + CNI $NERDCTL_VER / $CNI_VER =="
if have nerdctl; then skip "nerdctl $(nerdctl --version 2>/dev/null | awk '{print $3}')"
elif [ $CHECK = 1 ]; then miss "nerdctl 未安装"
else
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/n.tgz" "https://github.com/containerd/nerdctl/releases/download/${NERDCTL_VER}/nerdctl-${NERDCTL_VER#v}-linux-amd64.tar.gz"
  tar -xzf "$tmp/n.tgz" -C /usr/local/bin nerdctl && ok "nerdctl 已装"
  rm -rf "$tmp"
fi
if [ -x /opt/cni/bin/bridge ]; then skip "CNI 插件已装"
elif [ $CHECK = 1 ]; then miss "CNI 插件缺失"
else
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/cni.tgz" "https://github.com/containernetworking/plugins/releases/download/${CNI_VER}/cni-plugins-linux-amd64-${CNI_VER}.tgz"
  mkdir -p /opt/cni/bin && tar -xzf "$tmp/cni.tgz" -C /opt/cni/bin && ok "CNI 插件已装"
  rm -rf "$tmp"
fi

echo "== 7/7 网络与防火墙 =="
if [ $CHECK = 1 ]; then
  nerdctl network ls 2>/dev/null | grep -q "$NET_NAME" && ok "网络 $NET_NAME 存在" || miss "网络 $NET_NAME 不存在"
else
  nerdctl network ls 2>/dev/null | grep -q "$NET_NAME" \
    && skip "网络 $NET_NAME 已存在" \
    || { nerdctl network create --driver bridge --subnet "$NET_SUBNET" --gateway "$NET_GW" "$NET_NAME" >/dev/null && ok "已建网络 $NET_NAME"; }
  BR=$(ip -o -4 addr show 2>/dev/null | awk -v gw="$NET_GW" '$4 ~ gw"/" {print $2; exit}')
  if [ -n "${BR:-}" ]; then
    iptables -C INPUT -i "$BR" -s "$NET_SUBNET" -p tcp --dport 8808 -j ACCEPT 2>/dev/null \
      && skip "防火墙已放行 VM→网关" \
      || { iptables -I INPUT 1 -i "$BR" -s "$NET_SUBNET" -p tcp --dport 8808 -j ACCEPT && ok "已放行 VM→网关 8808"; }
  else
    miss "找不到网桥，跳过防火墙规则（启动一次 VM 后重跑本脚本）"
  fi
fi

cat <<EOF

下一步：
  1) 确认网关在跑：curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8808/healthz
  2) 启动智能体：$(dirname "$0")/run-vm.sh
  3) supervisor 托管（示例见 agent-runtime/README.md 的「开机自启」）
EOF
