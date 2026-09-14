#!/usr/bin/env bash
# 研究室 CA でサーバ証明書を発行する。IP が変わったらこれだけ作り直す。(#55)
#
#   scripts/tls/make-server-cert.sh                 # 既定の名前・アドレスで発行
#   scripts/tls/make-server-cert.sh 192.168.1.20    # アドレスを追加
#
# iPad 側は CA を信頼しているので、**サーバ証明書を作り直しても iPad の
# 設定はやり直さなくてよい。**
#
# SAN に入れるもの:
#   localhost / 127.0.0.1
#   <hostname>.local            mDNS（avahi）。iPad が引けるかは端末で確認する
#   172.20.10.2〜172.20.10.14   iPhone テザリングの範囲（/28）
#   10.42.0.1                   以前の whill-demo アクセスポイント
#   いま PC に付いている IPv4    自動で拾う
#   引数で渡したアドレス
#
# Apple の要件に合わせる: SAN 必須、EKU serverAuth、RSA 2048 以上、
# 有効期間 825 日以内（ここでは 397 日）。
set -euo pipefail

dir="${WHILL_TLS_DIR:-${HOME}/.config/whill/tls}"
days="${WHILL_TLS_SERVER_DAYS:-397}"

if [ ! -f "${dir}/ca.key" ] || [ ! -f "${dir}/ca.crt" ]; then
  echo "CA が無い: ${dir}。先に scripts/tls/make-ca.sh を実行すること" >&2
  exit 1
fi

host="$(hostname)"
sans=("DNS:localhost" "DNS:${host}.local" "IP:127.0.0.1" "IP:10.42.0.1")
for i in $(seq 2 14); do sans+=("IP:172.20.10.${i}"); done

# いま付いている IPv4（lo 以外）。CA の制約外（グローバル IP）は入れない —
# 入れても iPad が制約違反として拒否するので、入れる意味が無い。
is_private() {
  case "$1" in
    10.*|192.168.*|127.*) return 0 ;;
    172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) return 0 ;;
    *) return 1 ;;
  esac
}
while read -r addr; do
  ip="${addr%/*}"
  if is_private "${ip}"; then sans+=("IP:${ip}"); fi
done < <(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}')

for extra in "$@"; do
  if ! is_private "${extra}"; then
    echo "LAN 内のアドレスではない: ${extra}（CA の制約で iPad が拒否する）" >&2
    exit 1
  fi
  sans+=("IP:${extra}")
done

# 重複を除く（テザリング範囲といまの IP が重なることがある）
san_line="$(printf '%s\n' "${sans[@]}" | awk '!seen[$0]++' | paste -sd, -)"

umask 077
cfg="$(mktemp)"; csr="$(mktemp)"
trap 'rm -f "${cfg}" "${csr}"' EXIT
cat >"${cfg}" <<EOF
[req]
distinguished_name = dn
prompt = no

[dn]
O = whill_console lab
CN = ${host}.local

[v3_server]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
subjectAltName = ${san_line}
EOF

openssl req -new -newkey rsa:2048 -sha256 -nodes \
  -keyout "${dir}/server.key" -out "${csr}" -config "${cfg}" 2>/dev/null
openssl x509 -req -in "${csr}" -CA "${dir}/ca.crt" -CAkey "${dir}/ca.key" \
  -CAcreateserial -days "${days}" -sha256 \
  -extfile "${cfg}" -extensions v3_server -out "${dir}/server.crt" 2>/dev/null

chmod 600 "${dir}/server.key"
chmod 644 "${dir}/server.crt"

echo "サーバ証明書を発行した: ${dir}/server.crt（${days} 日）"
echo "含めた名前とアドレス: ${san_line}"
echo
echo "使うときは:"
echo "  export WHILL_TLS_CERT=${dir}/server.crt"
echo "  export WHILL_TLS_KEY=${dir}/server.key"
echo "  export WHILL_TLS_CA=${dir}/ca.crt"
