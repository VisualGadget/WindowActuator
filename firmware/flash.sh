#!/bin/bash

# Flash firmware.bin to ESP8266

et="esptool --port /dev/ttyUSB0 --chip esp8266 --baud 460800"
# $et erase-flash
$et write-flash --flash-size=detect 0 ./bin/firmware.bin

./upload-src.sh
