// ESP32-C3 Mini FSR reader -> USB serial.
//
// Wiring (voltage divider):
//   3V3 ---[ FSR ]---+--- FSR_PIN (GPIO3)
//                    |
//                  [10k]
//                    |
//                   GND
//
// On the ESP32-C3 only GPIO0-4 are ADC1 pins. Avoid GPIO2 (boot strap).
//
// Arduino IDE: Board "ESP32C3 Dev Module" (or "LOLIN C3 Mini"),
//   Tools > USB CDC On Boot: ENABLED   <-- required, otherwise Serial prints nothing.
// Output: one line per sample at ~100 Hz:  "F,<0..4095>\n"

#define FSR_PIN 3
#define SAMPLES 8
#define PERIOD_MS 10

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(FSR_PIN, ADC_11db);
}

void loop() {
  static uint32_t next = 0;
  if (millis() < next) return;
  next = millis() + PERIOD_MS;

  uint32_t sum = 0;
  for (int i = 0; i < SAMPLES; i++) sum += analogRead(FSR_PIN);
  Serial.printf("F,%u\n", sum / SAMPLES);
}
