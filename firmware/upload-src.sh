#!/usr/bin/env -S rshell --port /dev/ttyUSB0 --file

rsync --mirror ../src_alive /pyboard  # never remove /pyboard from dest!
repl~ import machine~ machine.soft_reset()
