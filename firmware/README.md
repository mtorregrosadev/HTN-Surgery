# Surge Prep ESP32-C3 Firmware

Firmware for the ESP32-C3 microcontroller driving an I2C OLED display (SSD1306, 128x64) to display ArUco tracking markers and QR codes.

## Hardware Wiring

| Device Pin | ESP32-C3 Pin | Note |
|---|---|---|
| **OLED SDA** | **GPIO 3** | I2C Data |
| **OLED SCL** | **GPIO 4** | I2C Clock |
| **OLED VCC** | **5V** (or 3.3V) | Power |
| **OLED GND** | **GND** | Ground |
| **FSR 400/402 (Analog)** | **GPIO 1** | **Recommended ADC1 pin** (12-bit 0-4095 continuous analog force) |
| **Pressure Switch (Digital)**| **GPIO 10** | Digital-only GPIO input |

## Display Modes

The display manager renders fiducial markers with an explicit white quiet zone border for optical tracking, plus split and sensor telemetry screens:

1. **Mode 0 (`'0'`)**: ArUco OpenCV 5×5 #0 (Large centered, default marker tracked by the web app).
2. **Mode 1 (`'1'`)**: QR Code pointing to `http://127.0.0.1:5173/` (with quiet zone and text label).
3. **Mode 2 (`'2'`)**: ArUco Surge Prep MIP 36h12 #0.
4. **Mode 3 (`'3'`)**: ArUco OpenCV 4×4 #0.
5. **Mode 4 (`'4'`)**: Split View (ArUco 5×5 #0 + live pressure status).
6. **Mode 5 (`'5'` or `'p'`)**: Pressure Sensor Monitor (live contact state, analog/digital pressure gauge bar, force in Newtons, raw value, sequence number, and TX status).

## Switching Modes & Terminal Sharing

- **Onboard BOOT Button (GPIO 9)**: Press to cycle through all 6 screens.
- **USB Serial Terminal (115200 baud)**:
  - `'0'` - `'5'`: Select display screen directly.
  - `'p'`: Jump directly to Pressure Sensor Monitor screen.
  - `'k'`: Toggle active pin (**GPIO 1 [12-bit ADC1 Analog]** <-> **GPIO 10 [Digital]**).
  - `'c'`: Auto-zero ADC baseline for unpressed FSR 400/402.
  - `'t'` / `'s'`: Toggle continuous pressure streaming in terminal.
  - `'j'`: Toggle JSON telemetry stream vs. human-readable log.
  - `'r'`: Read instantaneous pressure sensor diagnostics.
  - `'i'`: Invert contact detection polarity (`Active HIGH` <-> `Active LOW`).
  - `'u'`: Cycle pull resistor mode (`PULL-DOWN` -> `PULL-UP` -> `FLOATING`).
  - `' '` (space) or `'n'`: Next screen.
  - `'a'`: Toggle automatic 6-second cycling.
  - `'?'` / `'h'`: Print command menu.

## Terminal Output Formats

### Human-Readable Telemetry (default):
```text
[PRESSURE] pin=10 | state=CONTACT | raw=1 | force=1.50N | pull=PULL-DOWN | seq=242 | t=5239ms
```

### Immediate Event Notifications:
```text
>>> [PRESSURE EVENT] >>> CONTACT DETECTED on Pin 10! Raw=1 | Force=1.50 N | Seq=245 | Time=5310 ms <<<
--- [PRESSURE EVENT] --- Contact RELEASED on Pin 10. Raw=0 | Force=0.00 N | Seq=260 | Time=5820 ms ---
```

### JSON Telemetry Mode (`'j'`):
```json
{"type":"pressure","pin":10,"contact":true,"raw":1,"forceN":1.50,"pull":"PULL-DOWN","seq":242,"timestampMs":5239}
```

## Build and Flash

```bash
cd firmware
pio run --target upload
```
