# Surge Prep ESP32-C3 Firmware

Firmware for the ESP32-C3 microcontroller driving an I2C OLED display (SSD1306, 128x64) to display ArUco tracking markers and QR codes.

## Hardware Wiring

| OLED Pin | ESP32-C3 Pin | Note |
|---|---|---|
| **SDA** | **GPIO 3** | I2C Data |
| **SCL** | **GPIO 4** | I2C Clock |
| **VCC** | **5V** (or 3.3V) | Power |
| **GND** | **GND** | Ground |

## Display Modes

The firmware renders fiducial markers with an explicit white quiet zone border so cameras can cleanly distinguish the outer black boundary on an OLED display:

1. **Mode 0 (`'0'`)**: ArUco OpenCV 5×5 #0 (Large centered, default marker tracked by the web app).
2. **Mode 1 (`'1'`)**: QR Code pointing to `http://127.0.0.1:5173/` (with quiet zone and text label).
3. **Mode 2 (`'2'`)**: ArUco Surge Prep MIP 36h12 #0.
4. **Mode 3 (`'3'`)**: ArUco OpenCV 4×4 #0.
5. **Mode 4 (`'4'`)**: Split View (ArUco 5×5 #0 + text status).

## Switching Modes

- **Onboard BOOT Button (GPIO 9)**: Press to cycle through screens.
- **USB Serial (115200 baud)**:
  - Send `'0'`, `'1'`, `'2'`, `'3'`, or `'4'` to select mode directly.
  - Send `' '` (space) or `'n'` for next screen.
  - Send `'a'` to toggle automatic 6-second cycling.

## Build and Flash

```bash
cd firmware
pio run --target upload
```
