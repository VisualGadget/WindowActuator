#!/bin/bash

# source ../venv/bin/activate
# pip install rshell
# or
# sudo apt install pyboard-rshell
#
# sudo usermod -a -G dialout $USER
# reboot

# udevadm info --name /dev/ttyUSB*
rshell --port /dev/ttyUSB0

# cd /pyboard/
# ...
