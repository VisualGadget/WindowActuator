#!/bin/bash

# sudo apt install picocom
#
# sudo usermod -a -G dialout $USER
# reboot

# udevadm info --name /dev/ttyUSB*
picocom /dev/ttyUSB0 --baud 115200 --quiet
