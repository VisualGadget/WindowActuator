# Commutation scheme

## Legend

- **PS** - 12V to 5V step down DC-DC converter board
- **W** - Wemos D1 mini board
- **D** - TB6612FNG board
- **M** - 12V DC motor
- **PT** - 10K potentiometer on the output axis of the gearbox

## Scheme
|Power socket|PS pad|
|-|-|
|+12 input power|PS in +|
|GND input power|PS in GND|

|Driver pad|other pads|
|-|-|
|D VM|+12 input power|
|D VCC|W 3V3|
|D GND|PS out GND|
|D STBY|D VCC|
|D PWMA|W D2|
|D AIN1|W D7|
|D AIN2|W D8|
|D A1|M +|
|D A2|M -|

|Wemos pad|PS pad|
|-|-|
|W 5V|PS out +5|
|W GND|PS out GND|

|PT leg|Wemos pad|
|-|-|
|PT 1|W GND|
|PT 2|W A0|
|PT 3|W 3V3|
