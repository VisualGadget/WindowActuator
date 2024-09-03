# This file is executed on every boot (including wake-boot from deep sleep)

import esp
esp.osdebug(None)

# import uos
# uos.dupterm(None, 1) # disable REPL on UART(0)

# import webrepl
# webrepl.start(password='')

import gc
gc.collect()
