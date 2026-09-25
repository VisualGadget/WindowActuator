#!/usr/bin/env bash

set -Eeuo pipefail

# Firmware build

# https://docs.espressif.com/projects/esp8266-rtos-sdk/en/latest/get-started/linux-setup.html

fw=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_root=$(cd "$fw/.." && pwd)
upy=~/git/3rd_party/micropython  # https://github.com/micropython/micropython repo cloned using Git
espr=~/esp/espressif/xtensa-lx106-elf/bin  # Espressif ESP8266 toolchain

source "$project_root/venv/bin/activate"

python "$fw/compile_templates.py"

cd "$upy"
git submodule update --init

cd "$upy/ports/esp8266/"
export "PATH=$espr:$PATH"
# make clean
make -j BOARD=ESP8266_GENERIC FROZEN_MANIFEST=$fw/manifest.py
image_prefix="$fw/bin/firmware.elf"
rm -f "${image_prefix}0x00000.bin" "${image_prefix}0x09000.bin" "$fw/bin/firmware.bin"
esptool --chip esp8266 elf2image --flash-size=4MB --flash-mode=qio \
    --output "$image_prefix" ./build-ESP8266_GENERIC/firmware.elf
python makeimg.py \
    "${image_prefix}0x00000.bin" "${image_prefix}0x09000.bin" "$fw/bin/firmware.bin"
test -s "$fw/bin/firmware.bin"
rm -f "${image_prefix}0x00000.bin" "${image_prefix}0x09000.bin"
