#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
port="${1:-/dev/cu.usbserial-2130}"
avr_dir="$HOME/Library/Arduino15/packages/arduino/tools/avrdude/8.0.0-arduino1"
hex=firmware/build/guide_dog_firmware.ino.hex
[[ -f "$hex" ]] || { echo 'Compiled hex is missing.'; exit 1; }
[[ -x "$avr_dir/bin/avrdude" ]] || { echo 'Expected installed Arduino avrdude not found.'; exit 1; }
echo 'Set Zeus shield to UPLOAD; keep wheels raised. This flashes the ATmega328P Uno, not the ESP32 camera.'
read -r -p 'Press Enter when ready: ' ready
backup="firmware/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
args=(-C "$avr_dir/etc/avrdude.conf" -p atmega328p -c arduino -P "$port" -b 115200)
"$avr_dir/bin/avrdude" "${args[@]}" -n -U "flash:r:$backup/flash.hex:i" -U "eeprom:r:$backup/eeprom.hex:i"
"$avr_dir/bin/avrdude" "${args[@]}" -D -U "flash:w:$hex:i"
echo 'Firmware written and verified. Leave the switch on UPLOAD; connect the Uno USB cable to the Pi.'
