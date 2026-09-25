#!/usr/bin/env bash

set -Eeuo pipefail

firmware_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$firmware_dir"

# Flash firmware.bin to ESP8266

source "$firmware_dir/../venv/bin/activate"

firmware_image="$firmware_dir/bin/firmware.bin"
test -s "$firmware_image"

esptool --port /dev/ttyUSB0 --chip esp8266 --baud 460800 \
    write-flash --flash-size=detect 0 "$firmware_image"

esptool --port /dev/ttyUSB0 --chip esp8266 \
    verify-flash --flash-size=detect 0 "$firmware_image"

"$firmware_dir/upload-src.sh"
