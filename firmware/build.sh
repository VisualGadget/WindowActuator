#!/bin/bash

# Firmware build

# https://docs.espressif.com/projects/esp8266-rtos-sdk/en/latest/get-started/linux-setup.html

# sudo apt install -y python3-pip python3-venv
# at project root:
# python3 -m venv venv
# source venv/bin/activate
# pip install esptool

fw=$PWD
upy=~/git/micropython  # https://github.com/micropython/micropython repo cloned using Git
espr=~/esp/espressif/xtensa-lx106-elf/bin  # Espressif ESP8266 toolchain

source $fw/../venv/bin/activate

cd $upy
git checkout master
git pull
git submodule update --init

cd $upy/ports/esp8266/
export "PATH=$espr:$PATH"
make -j BOARD=ESP8266_GENERIC FROZEN_MANIFEST=$fw/manifest.py
cp ./build-ESP8266_GENERIC/firmware.bin $fw
