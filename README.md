# Window Actuator 1 (WA1)
Window driver to automate room ventilation with Home Assistant control. MQTT-over-WiFi device based on ESP8266 and MicroPython.

## Setup environment
```
sudo apt install -y python3-pip python3-venv picocom

sudo usermod -a -G dialout $USER
sudo reboot
```
From project root:
```
python3 -m venv venv
source venv/bin/activate
pip install micropython-esp8266-stubs esptool
```

## Build uPython firmware (optional)
microdot and utemplate libraries must be freezed into uPython firmware due to insufficient RAM amount.

Read and run **build.sh** to compile **firmware.bin**.

## Flash firmware
Connect Wemos D1 mini board with USB cable and run **flash.sh** to write base uPython firmware. Than upload project sources with **upload-src.sh**.
