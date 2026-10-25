# Window Actuator 1 (WA1)
Window driver to automate room ventilation with Home Assistant control. MQTT-over-WiFi device based on ESP8266 and MicroPython.

## Setup environment
```bash
sudo apt install -y picocom

sudo usermod -a -G dialout $USER
sudo reboot
```
From project root:
```bash
uv venv venv
source venv/bin/activate
uv pip install -r pyproject.toml --group dev
```

## Build uPython firmware (optional)
The web server (`wa.httpd`) and the web templates, rendered to Python by utemplate at build time, must be frozen into
the uPython firmware due to the small amount of RAM.

Read and run **build.sh** to compile **firmware.bin**.

## Flash firmware
Connect Wemos D1 mini board with USB cable and run **flash.sh** to write base uPython firmware. Than upload project sources with **upload-src.sh**.
