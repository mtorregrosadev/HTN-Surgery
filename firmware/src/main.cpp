#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <qrcode.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define PIN_SDA 3
#define PIN_SCL 4
#define PIN_BUTTON 9        // ESP32-C3 onboard BOOT button
#define PIN_PRESSURE_ADC 1  // ESP32-C3 ADC1_CH1: 12-bit Analog input for FSR 400/402
#define PIN_PRESSURE_DIG 10 // ESP32-C3 GPIO 10: Digital GPIO

uint8_t activePressurePin = PIN_PRESSURE_ADC; // Default to GPIO 1 for analog FSR 400/402
int adcZeroBaseline = 0;
int contactThresholdHigh = 120;
int contactThresholdLow = 60;
float smoothedRaw = 0.0f;
bool cleanOutputMode = true; // Calm, clean, non-chaotic output

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// Inner data bits (1 = white, 0 = black)
// OpenCV 5x5 #0 (5x5 inner data)
const uint8_t BITS_5X5_0[5][5] = {
  {1, 0, 1, 0, 0},
  {0, 1, 0, 1, 1},
  {0, 1, 1, 0, 0},
  {1, 0, 1, 0, 1},
  {1, 1, 1, 0, 0}
};

// OpenCV 4x4 #0 (4x4 inner data)
const uint8_t BITS_4X4_0[4][4] = {
  {1, 0, 1, 1},
  {0, 1, 0, 1},
  {0, 0, 1, 1},
  {0, 0, 1, 0}
};

// Surge Prep MIP 36h12 #0 (6x6 inner data)
const uint8_t BITS_MIP_0[6][6] = {
  {1, 1, 0, 1, 0, 0},
  {1, 0, 1, 0, 1, 1},
  {0, 1, 1, 0, 0, 0},
  {1, 1, 1, 0, 1, 0},
  {0, 0, 0, 0, 1, 0},
  {0, 1, 1, 1, 0, 1}
};

enum DisplayMode {
  MODE_ARUCO_5X5 = 0,
  MODE_QR_CODE = 1,
  MODE_ARUCO_MIP = 2,
  MODE_ARUCO_4X4 = 3,
  MODE_SPLIT = 4,
  MODE_PRESSURE = 5,
  MODE_COUNT = 6
};

// Pressure Sensor Configuration and State
enum PullMode {
  PULL_DOWN = 0,
  PULL_UP = 1,
  FLOATING = 2
};

PullMode currentPullMode = PULL_DOWN;
bool pressureActiveHigh = true;   // true: HIGH indicates contact; false: LOW indicates contact
bool streamTerminal = true;       // Continuous streaming to serial terminal
bool jsonTerminal = false;        // Output format: true = JSON, false = human-readable text
unsigned long streamIntervalMs = 200; // Terminal streaming rate (5Hz)
unsigned long lastStreamMs = 0;

struct PressureData {
  int rawValue;
  bool isContact;
  bool isAdc;
  float forceEstimateN;
  uint32_t sampleCount;
  unsigned long lastChangeMs;
  unsigned long lastSampleMs;
};

PressureData pressure = {
  0,       // rawValue
  false,   // isContact
  false,   // isAdc
  0.0f,    // forceEstimateN
  0,       // sampleCount
  0,       // lastChangeMs
  0        // lastSampleMs
};

DisplayMode currentMode = MODE_ARUCO_5X5;
bool autoCycle = false;
unsigned long lastCycleMs = 0;
bool lastBtnState = HIGH;

void drawAruco5x5Centered() {
  // Fill entire display with white quiet zone
  display.fillScreen(SSD1306_WHITE);

  // 7x7 modules (1 border + 5 data + 1 border) * 8px = 56px
  const int moduleSize = 8;
  const int totalSize = 7 * moduleSize; // 56px
  const int startX = (SCREEN_WIDTH - totalSize) / 2; // 36
  const int startY = (SCREEN_HEIGHT - totalSize) / 2; // 4

  // Outer black square
  display.fillRect(startX, startY, totalSize, totalSize, SSD1306_BLACK);

  // Inner 5x5 data modules
  for (int r = 0; r < 5; r++) {
    for (int c = 0; c < 5; c++) {
      if (BITS_5X5_0[r][c]) {
        display.fillRect(startX + (c + 1) * moduleSize, startY + (r + 1) * moduleSize, moduleSize, moduleSize, SSD1306_WHITE);
      }
    }
  }
  display.display();
}

void drawAruco4x4Centered() {
  // Fill entire display with white quiet zone
  display.fillScreen(SSD1306_WHITE);

  // 6x6 modules (1 border + 4 data + 1 border) * 10px = 60px
  const int moduleSize = 10;
  const int totalSize = 6 * moduleSize; // 60px
  const int startX = (SCREEN_WIDTH - totalSize) / 2; // 34
  const int startY = (SCREEN_HEIGHT - totalSize) / 2; // 2

  // Outer black square
  display.fillRect(startX, startY, totalSize, totalSize, SSD1306_BLACK);

  // Inner 4x4 data modules
  for (int r = 0; r < 4; r++) {
    for (int c = 0; c < 4; c++) {
      if (BITS_4X4_0[r][c]) {
        display.fillRect(startX + (c + 1) * moduleSize, startY + (r + 1) * moduleSize, moduleSize, moduleSize, SSD1306_WHITE);
      }
    }
  }
  display.display();
}

void drawArucoMipCentered() {
  // Fill entire display with white quiet zone
  display.fillScreen(SSD1306_WHITE);

  // 8x8 modules (1 border + 6 data + 1 border) * 7px = 56px
  const int moduleSize = 7;
  const int totalSize = 8 * moduleSize; // 56px
  const int startX = (SCREEN_WIDTH - totalSize) / 2; // 36
  const int startY = (SCREEN_HEIGHT - totalSize) / 2; // 4

  // Outer black square
  display.fillRect(startX, startY, totalSize, totalSize, SSD1306_BLACK);

  // Inner 6x6 data modules
  for (int r = 0; r < 6; r++) {
    for (int c = 0; c < 6; c++) {
      if (BITS_MIP_0[r][c]) {
        display.fillRect(startX + (c + 1) * moduleSize, startY + (r + 1) * moduleSize, moduleSize, moduleSize, SSD1306_WHITE);
      }
    }
  }
  display.display();
}

void drawQRCode(const char* payload) {
  display.fillScreen(SSD1306_WHITE);
  QRCode qrcode;
  const int version = 2; // 25x25 modules
  uint8_t qrcodeData[qrcode_getBufferSize(version)];
  qrcode_initText(&qrcode, qrcodeData, version, ECC_LOW, payload);

  const int modulePixel = 2; // 2px per module = 50px
  const int startX = 6;
  const int startY = (SCREEN_HEIGHT - qrcode.size * modulePixel) / 2; // 7

  // Black modules on white background
  for (int y = 0; y < qrcode.size; y++) {
    for (int x = 0; x < qrcode.size; x++) {
      if (qrcode_getModule(&qrcode, x, y)) {
        display.fillRect(startX + x * modulePixel, startY + y * modulePixel, modulePixel, modulePixel, SSD1306_BLACK);
      }
    }
  }

  // Text on the right side
  display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(66, 6);
  display.print("SURGE");
  display.setCursor(66, 16);
  display.print("PREP");
  display.drawLine(66, 27, 122, 27, SSD1306_BLACK);
  display.setCursor(66, 33);
  display.print("QR CODE");
  display.setCursor(66, 45);
  display.print(":5173");

  display.display();
}

const char* getPullModeName() {
  switch (currentPullMode) {
    case PULL_DOWN: return "PULL-DOWN";
    case PULL_UP:   return "PULL-UP";
    case FLOATING:  return "FLOATING";
    default:        return "UNKNOWN";
  }
}

void applyPullMode() {
  if (currentPullMode == PULL_DOWN) {
    pinMode(activePressurePin, INPUT_PULLDOWN);
  } else if (currentPullMode == PULL_UP) {
    pinMode(activePressurePin, INPUT_PULLUP);
  } else {
    pinMode(activePressurePin, INPUT);
  }
}

int contactCandidateCount = 0;
int releaseCandidateCount = 0;

void updateThresholds() {
  contactThresholdHigh = adcZeroBaseline + 80;
  contactThresholdLow  = adcZeroBaseline + 35;
}

void calibrateAdcZero() {
  if (!pressure.isAdc) return;
  delay(100); // Allow circuit to settle
  long sum = 0;
  const int samples = 30;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(activePressurePin);
    delay(3);
  }
  adcZeroBaseline = (int)(sum / samples);
  updateThresholds();
  smoothedRaw = (float)adcZeroBaseline;
  Serial.printf("\n[Calibrated] FSR-402 baseline: %d (Touch: >=%d, Release: <=%d)\n\n",
                adcZeroBaseline, contactThresholdHigh, contactThresholdLow);
}

void initPressureSensor() {
  applyPullMode(); // Anchors pin with internal pull-down to GND when unpressed
  pressure.isAdc = (digitalPinToAnalogChannel(activePressurePin) >= 0);
  if (pressure.isAdc) {
    calibrateAdcZero();
  }
  Serial.printf("[Sensor] Pressure Sensor configured on GPIO %d (%s, Mode: %s)\n",
                activePressurePin,
                getPullModeName(),
                pressure.isAdc ? "12-bit ADC1 Analog (FSR 400/402)" : "Digital GPIO");
  if (!pressure.isAdc) {
    Serial.println("[NOTE] GPIO 10 is digital-only on ESP32-C3. Move signal wire to GPIO 1 for true analog FSR 400/402!");
  }
}

bool updatePressureSensor() {
  unsigned long now = millis();
  int raw = 0;
  bool contact = pressure.isContact;

  if (pressure.isAdc) {
    // 8x oversampling to reject AC mains ripple
    long sum = 0;
    for (int i = 0; i < 8; i++) {
      sum += analogRead(activePressurePin);
    }
    raw = (int)(sum / 8);

    // Responsive EMA filter (60% history, 40% new sample)
    smoothedRaw = 0.60f * smoothedRaw + 0.40f * (float)raw;
    int currentRaw = (int)smoothedRaw;

    // Automatic downward tare: if physical reading is below baseline,
    // immediately adapt baseline down to prevent sensor deafness from touch-at-boot
    if (currentRaw < adcZeroBaseline) {
      adcZeroBaseline = currentRaw;
      updateThresholds();
    }

    // Slow ambient drift compensation when completely idle for > 1.5s
    if (!pressure.isContact && (now - pressure.lastChangeMs > 1500)) {
      if (currentRaw < contactThresholdLow) {
        static unsigned long lastDriftMs = 0;
        if (now - lastDriftMs > 300) {
          lastDriftMs = now;
          if (currentRaw > adcZeroBaseline) {
            adcZeroBaseline++;
            updateThresholds();
          } else if (currentRaw < adcZeroBaseline) {
            adcZeroBaseline--;
            updateThresholds();
          }
        }
      }
    }

    // 2-cycle persistence filter (40ms response, filters transient glitch spikes)
    if (!pressure.isContact) {
      if (currentRaw >= contactThresholdHigh) {
        contactCandidateCount++;
        releaseCandidateCount = 0;
        if (contactCandidateCount >= 2) {
          contact = true;
        }
      } else {
        contactCandidateCount = 0;
      }
    } else {
      if (currentRaw <= contactThresholdLow) {
        contact = false;
        releaseCandidateCount = 0;
        contactCandidateCount = 0;
      }
    }

    int delta = max(0, currentRaw - adcZeroBaseline);
    int span = max(150, 4095 - adcZeroBaseline);
    pressure.forceEstimateN = contact ? ((float)delta / (float)span * 10.0f) : 0.0f;
  } else {
    raw = digitalRead(activePressurePin);
    contact = pressureActiveHigh ? (raw == HIGH) : (raw == LOW);
    pressure.forceEstimateN = contact ? 1.5f : 0.0f;
  }

  pressure.rawValue = raw;
  pressure.sampleCount++;
  pressure.lastSampleMs = now;

  // Debounced state transition (40ms debounce)
  bool stateChanged = false;
  if (contact != pressure.isContact && (now - pressure.lastChangeMs > 40)) {
    pressure.isContact = contact;
    pressure.lastChangeMs = now;
    stateChanged = true;

    // Clean, readable event notification in terminal
    if (jsonTerminal) {
      Serial.printf("{\"event\":\"%s\",\"pin\":%d,\"forceN\":%.2f,\"raw\":%d,\"timestampMs\":%lu}\n",
                    pressure.isContact ? "contact_start" : "contact_end",
                    activePressurePin,
                    pressure.forceEstimateN,
                    pressure.rawValue,
                    now);
    } else if (cleanOutputMode) {
      if (pressure.isContact) {
        Serial.printf("\n>>> [TOUCH] Engaged (Force: %.2f N | raw: %d | delta: %+d)\n",
                      pressure.forceEstimateN, pressure.rawValue, pressure.rawValue - adcZeroBaseline);
      } else {
        Serial.printf("--- [RELEASE] Sensor idle (0.00 N)\n\n");
      }
    } else {
      if (pressure.isContact) {
        Serial.printf(">>> [PRESSURE EVENT] >>> CONTACT DETECTED on Pin %d! Raw=%d | Force=%.2f N <<<\n",
                      activePressurePin, pressure.rawValue, pressure.forceEstimateN);
      } else {
        Serial.printf("--- [PRESSURE EVENT] --- Contact RELEASED on Pin %d. Raw=%d <<<\n",
                      activePressurePin, pressure.rawValue);
      }
    }
  }

  return stateChanged;
}

void streamPressureToTerminal() {
  if (!streamTerminal) return;
  unsigned long now = millis();

  // Calm, clean stream mode: quiet when idle, sleek ASCII bar when pressing
  if (cleanOutputMode && !jsonTerminal) {
    if (pressure.isContact) {
      if (now - lastStreamMs < 150) return; // ~6.6Hz clean updates while pressing
      lastStreamMs = now;

      char bar[16];
      int filled = constrain((int)((pressure.forceEstimateN / 8.0f) * 10), 0, 10);
      bar[0] = '[';
      for (int i = 0; i < 10; i++) bar[i + 1] = (i < filled) ? '=' : '-';
      bar[11] = ']';
      bar[12] = '\0';

      Serial.printf("[FSR] %5.2f N  %s  (raw: %4d | delta: %+d)\n",
                    pressure.forceEstimateN, bar, pressure.rawValue, pressure.rawValue - adcZeroBaseline);
    } else {
      // Idle heartbeat every 2 seconds with live raw reading so user sees what resting value is
      if (now - lastStreamMs < 2000) return;
      lastStreamMs = now;
      Serial.printf("[FSR] Idle (ready) | raw: %4d | base: %4d | thresh: %4d | Pin %d\n",
                    pressure.rawValue, adcZeroBaseline, contactThresholdHigh, activePressurePin);
    }
    return;
  }

  // Verbose stream mode
  if (now - lastStreamMs < streamIntervalMs) return;
  lastStreamMs = now;

  if (jsonTerminal) {
    Serial.printf("{\"type\":\"pressure\",\"pin\":%d,\"isAdc\":%s,\"contact\":%s,\"raw\":%d,\"forceN\":%.2f,\"timestampMs\":%lu}\n",
                  activePressurePin,
                  pressure.isAdc ? "true" : "false",
                  pressure.isContact ? "true" : "false",
                  pressure.rawValue,
                  pressure.forceEstimateN,
                  now);
  } else {
    Serial.printf("[PRESSURE] pin=%d (%s) | state=%-7s | raw=%-4d | force=%.2fN | t=%lums\n",
                  activePressurePin,
                  pressure.isAdc ? "ADC1" : "DIG ",
                  pressure.isContact ? "CONTACT" : "IDLE",
                  pressure.rawValue,
                  pressure.forceEstimateN,
                  now);
  }
}

void drawPressureScreen() {
  display.clearDisplay();

  // Top header bar
  display.fillRect(0, 0, SCREEN_WIDTH, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(4, 2);
  display.print("SURGE PREP PRESSURE");

  // Subtitle with Pin & Mode
  display.setTextColor(SSD1306_WHITE, SSD1306_BLACK);
  display.setCursor(2, 14);
  if (pressure.isAdc) {
    display.printf("PIN: GPIO %d [ADC1 ANALOG]", activePressurePin);
  } else {
    display.printf("PIN: GPIO %d [%s DIG]", activePressurePin, getPullModeName());
  }

  // Contact status box
  if (pressure.isContact) {
    display.fillRect(2, 24, SCREEN_WIDTH - 4, 15, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
    display.setCursor(14, 28);
    display.print("** CONTACT DETECTED **");
  } else {
    display.drawRect(2, 24, SCREEN_WIDTH - 4, 15, SSD1306_WHITE);
    display.setTextColor(SSD1306_WHITE, SSD1306_BLACK);
    display.setCursor(20, 28);
    display.print("IDLE - NO CONTACT");
  }

  // Pressure gauge bar
  display.drawRect(2, 42, SCREEN_WIDTH - 4, 8, SSD1306_WHITE);
  int fillWidth = 0;
  if (pressure.isAdc) {
    int delta = max(0, pressure.rawValue - adcZeroBaseline);
    int span = max(100, 4095 - adcZeroBaseline);
    fillWidth = map(constrain(delta, 0, span), 0, span, 0, SCREEN_WIDTH - 8);
  } else {
    fillWidth = pressure.isContact ? (SCREEN_WIDTH - 8) : 0;
  }
  if (fillWidth > 0) {
    display.fillRect(4, 44, fillWidth, 4, SSD1306_WHITE);
  }

  // Telemetry status line
  display.setTextColor(SSD1306_WHITE, SSD1306_BLACK);
  display.setCursor(2, 54);
  if (pressure.isAdc) {
    display.printf("RAW:%-4d FORCE:%.1fN  %s",
                   pressure.rawValue,
                   pressure.forceEstimateN,
                   streamTerminal ? "TX" : "--");
  } else {
    display.printf("RAW:%d  SEQ:%lu  %s",
                   pressure.rawValue,
                   pressure.sampleCount % 1000,
                   streamTerminal ? "TX:ON" : "TX:OFF");
  }

  display.display();
}

void drawSplitView() {
  display.fillScreen(SSD1306_WHITE);
  // ArUco 5x5 on left (56px)
  const int moduleSize = 8;
  const int totalSize = 56;
  const int startX = 4;
  const int startY = 4;
  display.fillRect(startX, startY, totalSize, totalSize, SSD1306_BLACK);
  for (int r = 0; r < 5; r++) {
    for (int c = 0; c < 5; c++) {
      if (BITS_5X5_0[r][c]) {
        display.fillRect(startX + (c + 1) * moduleSize, startY + (r + 1) * moduleSize, moduleSize, moduleSize, SSD1306_WHITE);
      }
    }
  }

  // Label on right
  display.setTextColor(SSD1306_BLACK, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(68, 4);
  display.print("SURGE");
  display.setCursor(68, 14);
  display.print("PREP");
  display.drawLine(68, 24, 122, 24, SSD1306_BLACK);
  display.setCursor(68, 28);
  display.print("ARUCO");
  display.setCursor(68, 38);
  display.print("5x5 #0");
  display.drawLine(68, 48, 122, 48, SSD1306_BLACK);
  display.setCursor(68, 52);
  display.print(pressure.isContact ? "P:CONTACT" : "P:IDLE");

  display.display();
}

void renderCurrentMode() {
  switch (currentMode) {
    case MODE_ARUCO_5X5:
      Serial.println("[Display] Mode 0: ArUco OpenCV 5x5 #0 (White Quiet Zone)");
      drawAruco5x5Centered();
      break;
    case MODE_QR_CODE:
      Serial.println("[Display] Mode 1: QR Code (http://127.0.0.1:5173/)");
      drawQRCode("http://127.0.0.1:5173/");
      break;
    case MODE_ARUCO_MIP:
      Serial.println("[Display] Mode 2: ArUco MIP 36h12 #0 (White Quiet Zone)");
      drawArucoMipCentered();
      break;
    case MODE_ARUCO_4X4:
      Serial.println("[Display] Mode 3: ArUco OpenCV 4x4 #0 (White Quiet Zone, 10px modules)");
      drawAruco4x4Centered();
      break;
    case MODE_SPLIT:
      Serial.println("[Display] Mode 4: Split View (ArUco 5x5 + Status)");
      drawSplitView();
      break;
    case MODE_PRESSURE:
      Serial.printf("[Display] Mode 5: Pressure Sensor Monitor (GPIO %d - %s)\n",
                    activePressurePin, pressure.isAdc ? "ADC1 Analog" : "Digital");
      drawPressureScreen();
      break;
    default:
      break;
  }
}

void printHelp() {
  Serial.println("\nCommands via Serial:");
  Serial.println("  '0' : ArUco OpenCV 5x5 #0");
  Serial.println("  '1' : QR Code (Web URL)");
  Serial.println("  '2' : ArUco MIP 36h12 #0");
  Serial.println("  '3' : ArUco OpenCV 4x4 #0 (High Motion Tolerance)");
  Serial.println("  '4' : Split View (ArUco + Pressure Status)");
  Serial.println("  '5' : Pressure Sensor Screen");
  Serial.println("  'p' : Switch to Pressure Sensor screen");
  Serial.println("  'k' : Toggle pin (GPIO 1 [ADC1 Analog] <-> GPIO 10 [Digital])");
  Serial.println("  'c' : Auto-zero ADC baseline for unpressed FSR 400/402");
  Serial.println("  'v' : Toggle calm/clean mode vs verbose output");
  Serial.println("  't' : Toggle terminal pressure streaming (ON/OFF)");
  Serial.println("  'j' : Toggle JSON telemetry output (ON/OFF)");
  Serial.println("  'r' : Instantaneous pressure reading & diagnostics");
  Serial.println("  'i' : Invert contact polarity (Active HIGH <-> LOW)");
  Serial.println("  'u' : Cycle pull mode (PULLDOWN -> PULLUP -> FLOATING)");
  Serial.println("  'a' : Toggle auto-cycle mode");
  Serial.println("  ' ' : Next screen");
  Serial.println("  '?' : Print help menu");
  Serial.println("Or press BOOT button (GPIO 9) to switch screen\n");
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);

  // Initialize I2C on pins 3 (SDA) and 4 (SCL)
  Wire.begin(PIN_SDA, PIN_SCL);
  delay(200);

  Serial.println("\n==================================");
  Serial.println("  Surge Prep - ESP32-C3 Display   ");
  Serial.println("==================================");
  Serial.printf("I2C Pins: SDA=%d, SCL=%d\n", PIN_SDA, PIN_SCL);

  // Scan I2C bus
  byte count = 0;
  byte foundAddress = 0x3C; // default
  for (byte address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("Found I2C device at 0x%02X\n", address);
      if (address == 0x3C || address == 0x3D) {
        foundAddress = address;
      }
      count++;
    }
  }
  if (count == 0) {
    Serial.println("No I2C devices found! Check wiring: SDA->3, SCL->4, VCC->5V, GND->GND");
  }

  // Initialize OLED display
  if (!display.begin(SSD1306_SWITCHCAPVCC, foundAddress)) {
    Serial.printf("SSD1306 allocation failed at 0x%02X\n", foundAddress);
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3D)) {
      Serial.println("SSD1306 fallback 0x3D also failed.");
    }
  } else {
    Serial.printf("SSD1306 OLED initialized at 0x%02X\n", foundAddress);
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(0xFF); // Maximum contrast
  }

  // Allow FSR voltage divider to stabilize before calibration
  delay(200);

  // Initialize Pressure Sensor (default to GPIO 1 for ADC)
  initPressureSensor();

  renderCurrentMode();
  lastCycleMs = millis();

  printHelp();
}

void loop() {
  // Sample pressure sensor and detect transitions
  bool stateChanged = updatePressureSensor();

  // Share telemetry in terminal periodically
  streamPressureToTerminal();

  // Refresh dynamic screens (Pressure screen or Split View)
  static unsigned long lastDisplayUpdateMs = 0;
  if (currentMode == MODE_PRESSURE) {
    if (stateChanged || (millis() - lastDisplayUpdateMs >= 100)) {
      lastDisplayUpdateMs = millis();
      drawPressureScreen();
    }
  } else if (currentMode == MODE_SPLIT && stateChanged) {
    drawSplitView();
  }

  // Check Serial input
  if (Serial.available()) {
    char ch = Serial.read();
    if (ch >= '0' && ch <= '5') {
      currentMode = (DisplayMode)(ch - '0');
      renderCurrentMode();
    } else if (ch == 'p') {
      currentMode = MODE_PRESSURE;
      renderCurrentMode();
    } else if (ch == 'k') {
      activePressurePin = (activePressurePin == PIN_PRESSURE_ADC) ? PIN_PRESSURE_DIG : PIN_PRESSURE_ADC;
      initPressureSensor();
      if (currentMode == MODE_PRESSURE) {
        renderCurrentMode();
      }
    } else if (ch == 'c') {
      calibrateAdcZero();
    } else if (ch == 'v') {
      cleanOutputMode = !cleanOutputMode;
      Serial.printf("[Terminal] Clean output mode: %s\n", cleanOutputMode ? "ENABLED (Calm)" : "DISABLED (Verbose)");
    } else if (ch == ' ' || ch == 'n') {
      currentMode = (DisplayMode)((currentMode + 1) % MODE_COUNT);
      renderCurrentMode();
    } else if (ch == 'a') {
      autoCycle = !autoCycle;
      Serial.printf("Auto-cycle: %s\n", autoCycle ? "ON" : "OFF");
      lastCycleMs = millis();
    } else if (ch == 't' || ch == 's') {
      streamTerminal = !streamTerminal;
      Serial.printf("[Terminal] Pressure streaming: %s\n", streamTerminal ? "ENABLED" : "DISABLED");
    } else if (ch == 'j') {
      jsonTerminal = !jsonTerminal;
      Serial.printf("[Terminal] JSON output format: %s\n", jsonTerminal ? "ENABLED" : "DISABLED");
    } else if (ch == 'r') {
      Serial.printf("[Pressure Reading] Pin %d: Raw=%d, Contact=%s, Force=%.2f N, Pull=%s, Mode=%s\n",
                    activePressurePin,
                    pressure.rawValue,
                    pressure.isContact ? "YES" : "NO",
                    pressure.forceEstimateN,
                    getPullModeName(),
                    pressure.isAdc ? "ADC1 Analog (FSR 400/402)" : "Digital GPIO");
    } else if (ch == 'i') {
      pressureActiveHigh = !pressureActiveHigh;
      Serial.printf("[Pressure Config] Polarity: Active %s\n", pressureActiveHigh ? "HIGH" : "LOW");
    } else if (ch == 'u') {
      currentPullMode = (PullMode)((currentPullMode + 1) % 3);
      applyPullMode();
      Serial.printf("[Pressure Config] Pull mode: %s\n", getPullModeName());
    } else if (ch == '?' || ch == 'h') {
      printHelp();
    }
  }

  // Check BOOT button (GPIO 9)
  bool btnState = digitalRead(PIN_BUTTON);
  if (btnState == LOW && lastBtnState == HIGH) {
    delay(50); // debounce
    if (digitalRead(PIN_BUTTON) == LOW) {
      currentMode = (DisplayMode)((currentMode + 1) % MODE_COUNT);
      renderCurrentMode();
    }
  }
  lastBtnState = btnState;

  // Auto-cycle if enabled
  if (autoCycle && (millis() - lastCycleMs > 6000)) {
    lastCycleMs = millis();
    currentMode = (DisplayMode)((currentMode + 1) % MODE_COUNT);
    renderCurrentMode();
  }

  delay(20);
}
