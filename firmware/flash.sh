#!/bin/bash

# Flash firmware.bin to ESP8266

# sudo usermod -a -G dialout $USER
# reboot

source ../venv/bin/activate

et="esptool.py --port /dev/ttyUSB0 --chip esp8266 --baud 460800"
# $et erase_flash
$et write_flash --flash_size=detect 0 ./firmware.bin
