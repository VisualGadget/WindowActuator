import gc

import esp
from machine import Pin, reset_cause

# Put the motor driver into a safe state before application code starts.
Pin(4, Pin.OUT, value=0)
Pin(13, Pin.OUT, value=0)
Pin(15, Pin.OUT, value=0)

esp.osdebug(None)
print(f'Boot reset cause: {reset_cause()}')

# import uos
# uos.dupterm(None, 1) # disable REPL on UART(0)

# import webrepl
# webrepl.start(password='')

gc.collect()
