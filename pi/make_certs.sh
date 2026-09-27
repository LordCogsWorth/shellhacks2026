#!/usr/bin/env bash
set -euo pipefail
umask 077
PI_HOST="${1:-$(hostname -s).local}"
[[ "$PI_HOST" =~ ^[a-zA-Z0-9.-]+$ ]] || { echo 'Invalid hostname'; exit 1; }
cd "$(dirname "$0")"
mkdir -p certs
cd certs
SAN="DNS:${PI_HOST},DNS:localhost,IP:127.0.0.1"
for address in $(hostname -I 2>/dev/null || true); do
  [[ "$address" == *:* ]] || SAN="${SAN},IP:${address}"
done
if [[ ! -f guidedog-ca.key && ! -f guidedog-ca.crt ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -sha256 \
    -keyout guidedog-ca.key -out guidedog-ca.crt \
    -subj '/CN=Guide Dog Robot Local CA' \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign'
fi
[[ -f guidedog-ca.key && -f guidedog-ca.crt ]] || { echo 'Incomplete CA; restore its missing file.'; exit 1; }
openssl req -newkey rsa:2048 -nodes -sha256 \
  -keyout guidedog.key -out guidedog.csr -subj "/CN=${PI_HOST}"
cat > ext.cnf <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SAN}
EOF
openssl x509 -req -in guidedog.csr -CA guidedog-ca.crt -CAkey guidedog-ca.key \
  -CAcreateserial -days 365 -sha256 -extfile ext.cnf -out guidedog.crt
rm -f guidedog.csr ext.cnf
chmod 600 ./*.key
openssl verify -CAfile guidedog-ca.crt guidedog.crt
openssl x509 -in guidedog-ca.crt -noout -fingerprint -sha256
printf '\nCertificate covers: %s\n' "$SAN"
printf 'iPhone setup: http://%s:8000/setup.html\n' "$PI_HOST"
