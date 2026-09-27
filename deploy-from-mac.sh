#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
target="${1:-pi@pi.local}"
[[ "$target" != -* ]] || exit 1
# Check access before copying or changing the remote installation.
ssh "$target" 'hostname; uname -m; mkdir -p ~/guide-dog-live'
# Preserve any earlier deployment and its certificates.
ssh "$target" 'if test -f ~/guide-dog-live/pi/bridge.py; then cp -a ~/guide-dog-live ~/guide-dog-live.backup-$(date +%Y%m%d-%H%M%S); fi'
scp -r pi dashboard "$target:guide-dog-live/"
ssh -t "$target" 'bash ~/guide-dog-live/pi/install.sh'
