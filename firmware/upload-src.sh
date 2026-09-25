#!/usr/bin/env bash

set -Eeuo pipefail

firmware_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "$firmware_dir/.." && pwd)
cd "$firmware_dir"

source "$project_root/venv/bin/activate"

commands_file=$(mktemp)
trap 'rm -f "$commands_file"' EXIT
printf '%s\n' \
    'rsync --mirror ../src_alive/html /pyboard/html' > "$commands_file"
rshell --port /dev/ttyUSB0 --file "$commands_file"
esptool --port /dev/ttyUSB0 --chip esp8266 chip-id >/dev/null
