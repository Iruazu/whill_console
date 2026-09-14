#!/usr/bin/env bash
# 研究室専用の認証局（CA）を作る。**1 回だけ。** (#55)
#
#   scripts/tls/make-ca.sh            # ~/.config/whill/tls/ に作る
#   WHILL_TLS_DIR=/path scripts/tls/make-ca.sh
#
# ## なぜ自前の CA か
#
# iPad の Safari / Chrome は http を https に上げてしまい、http の画面を
# 開けない（2026-09-14 に ERR_SSL_PROTOCOL_ERROR を実測）。自己署名の証明書を
# 直接信頼させる方法だと、IP が変わるたびに iPad 側の設定をやり直すことになる。
# CA を 1 回信頼させておけば、IP が変わってもサーバ証明書を作り直すだけで済む。
#
# ## Name Constraints を付ける理由
#
# 信頼させた CA は、iPad 上で「どのサイトの証明書でも発行できる」権限を持つ。
# 鍵が漏れたら、その iPad に対して任意のサイトを偽装できてしまう。そこで
# この CA が発行できる名前を、LAN 内のアドレス（RFC 1918 と 127/8）と
# `.local` / `localhost` に限る。公開サイトの名前・アドレスは発行できない。
#
# **既にある CA は上書きしない。** 上書きすると、信頼させた全 iPad で
# やり直しになる。作り直すなら明示的に消してから実行すること。
set -euo pipefail

dir="${WHILL_TLS_DIR:-${HOME}/.config/whill/tls}"
days="${WHILL_TLS_CA_DAYS:-3650}"

if [ -e "${dir}/ca.key" ] || [ -e "${dir}/ca.crt" ]; then
  echo "既に CA がある: ${dir}/ca.crt" >&2
  echo "上書きすると、信頼させた iPad すべてで設定をやり直すことになる。" >&2
  echo "本当に作り直すなら ca.key と ca.crt を消してから実行すること。" >&2
  exit 1
fi

umask 077
mkdir -p "${dir}"
chmod 700 "${dir}"

cfg="$(mktemp)"
trap 'rm -f "${cfg}"' EXIT
cat >"${cfg}" <<'EOF'
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3_ca

[dn]
O = whill_console lab
CN = whill_console lab CA

[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical, @nc

[nc]
permitted;IP.1 = 10.0.0.0/255.0.0.0
permitted;IP.2 = 172.16.0.0/255.240.0.0
permitted;IP.3 = 192.168.0.0/255.255.0.0
permitted;IP.4 = 127.0.0.0/255.0.0.0
permitted;DNS.1 = local
permitted;DNS.2 = localhost
EOF

openssl req -x509 -new -newkey rsa:3072 -sha256 -nodes \
  -days "${days}" -keyout "${dir}/ca.key" -out "${dir}/ca.crt" \
  -config "${cfg}" 2>/dev/null

chmod 600 "${dir}/ca.key"
chmod 644 "${dir}/ca.crt"

echo "CA を作った: ${dir}/ca.crt"
echo "鍵: ${dir}/ca.key（600。**git やクラウドに置かないこと**）"
echo "次: scripts/tls/make-server-cert.sh でサーバ証明書を発行する"
