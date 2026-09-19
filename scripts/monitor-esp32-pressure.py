#!/usr/bin/env python3
"""
Monitor and interact with the Surge Prep ESP32 pressure sensor and OLED display.
Reads serial telemetry from the ESP32 on GPIO 10 and provides interactive controls.
"""

import glob
import sys
import time

try:
    import serial
except ImportError:
    print("pyserial is required: pip install pyserial")
    sys.exit(1)


def find_esp32_port() -> str:
    ports = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    if not ports:
        print("Error: No ESP32 serial port found (looked for /dev/cu.usbmodem*, /dev/ttyACM*, /dev/ttyUSB*)")
        sys.exit(1)
    return ports[0]


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else find_esp32_port()
    baud = 115200
    print(f"Connecting to ESP32 on {port} @ {baud} baud...")

    try:
        ser = serial.Serial(port, baud, timeout=0.1)
    except Exception as e:
        print(f"Failed to open port {port}: {e}")
        sys.exit(1)

    print("Connected! Streaming pressure telemetry from GPIO 10.")
    print("Keys: [p]=Pressure screen | [0-5]=Screen mode | [j]=Toggle JSON | [u]=Toggle pull | [r]=Read now | [q]=Quit\n")

    try:
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line:
                print(line, flush=True)
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nExiting monitor.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
