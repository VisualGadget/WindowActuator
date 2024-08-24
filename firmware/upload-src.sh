#!/bin/bash

source ../venv/bin/activate

rshell --port /dev/ttyUSB0 "rsync --mirror ../src /pyboard"  # never remove /pyboard from dest!
