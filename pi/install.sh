#!/usr/bin/env bash
set -euo pipefail
[[ $(uname -s) == Linux ]] || { echo 'Run this installer on the Raspberry Pi.'; exit 1; }
project_dir=$(cd "$(dirname "$0")/.." && pwd)
run_user=$(id -un)
[[ "$run_user" != root ]] || { echo 'Run as the Pi user, not sudo bash; the script requests sudo when needed.'; exit 1; }
[[ "$project_dir" != *' '* ]] || { echo 'Use an installation path without spaces.'; exit 1; }
sudo -v
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip openssl avahi-daemon espeak-ng alsa-utils curl
python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/pi/requirements.txt"
bash "$project_dir/pi/make_certs.sh" "$(hostname -s).local"
if [[ ! -e "$project_dir/pi/bridge.env" ]]; then
  printf '# Set the Zeus camera MJPEG address once it joins the hotspot.\n# CAMERA_URL=http://CAMERA_IP:9000/mjpg\n' > "$project_dir/pi/bridge.env"
fi
chmod 600 "$project_dir/pi/bridge.env"
if [[ ! -e "$project_dir/pi/navigation.env" ]]; then
  cp "$project_dir/pi/navigation.env.example" "$project_dir/pi/navigation.env"
fi
chmod 600 "$project_dir/pi/navigation.env"
unit=/etc/systemd/system/guidedog.service
if sudo test -e "$unit"; then
  sudo cp -a "$unit" "$unit.backup-$(date +%Y%m%d-%H%M%S)"
fi
sudo tee "$unit" >/dev/null <<EOF
[Unit]
Description=Guide Dog camera, Arduino and iPhone GPS bridge
Wants=network-online.target
After=network-online.target
[Service]
Type=simple
User=$run_user
SupplementaryGroups=dialout
WorkingDirectory=$project_dir/pi
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=$project_dir/pi/bridge.env
ExecStartPre=/bin/bash $project_dir/pi/make_certs.sh
ExecStart=$project_dir/.venv/bin/python $project_dir/pi/bridge.py
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now avahi-daemon
sudo systemctl daemon-reload
sudo systemctl enable guidedog.service
sudo systemctl restart guidedog.service
for attempt in {1..15}; do
  if curl -fsS http://127.0.0.1:8000/health; then
    printf '\nDashboard: http://%s.local:8000\niPhone setup: http://%s.local:8000/setup.html\n' "$(hostname -s)" "$(hostname -s)"
    exit 0
  fi
  sleep 1
done
sudo journalctl -u guidedog -n 40 --no-pager
exit 1
