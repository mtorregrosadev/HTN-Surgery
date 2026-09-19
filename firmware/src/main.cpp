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
#define PIN_BUTTON 9 // ESP32-C3 onboard BOOT button

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// Marker definitions
// 1 = White (Lit), 0 = Black (Dark)
// OpenCV 5x5 #0 (9x9 grid with 1-module white border)
const uint8_t ARUCO_5X5_ID0[9][9] = {
  {1, 1, 1, 1, 1, 1, 1, 1, 1},
  {1, 0, 0, 0, 0, 0, 0, 0, 1},
  {1, 0, 1, 0, 1, 0, 0, 0, 1},
  {1, 0, 0, 1, 0, 1, 1, 0, 1},
  {1, 0, 0, 1, 1, 0, 0, 0, 1},
  {1, 0, 1, 0, 1, 0, 1, 0, 1},
  {1, 0, 1, 1, 1, 0, 0, 0, 1},
  {1, 0, 0, 0, 0, 0, 0, 0, 1},
  {1, 1, 1, 1, 1, 1, 1, 1, 1}
};

// Surge Prep MIP 36h12 #0 (10x10 grid with 1-module white border)
const uint8_t ARUCO_MIP_ID0[10][10] = {
  {1, 1, 1, 1, 1, 1, 1, 1, 1, 1},
  {1, 0, 0, 0, 0, 0, 0, 0, 0, 1},
  {1, 0, 1, 1, 0, 1, 0, 0, 0, 1},
  {1, 0, 1, 0, 1, 0, 1, 1, 0, 1},
  {1, 0, 0, 1, 1, 0, 0, 0, 0, 1},
  {1, 0, 1, 1, 1, 0, 1, 0, 0, 1},
  {1, 0, 0, 0, 0, 0, 1, 0, 0, 1},
  {1, 0, 0, 1, 1, 1, 0, 1, 0, 1},
  {1, 0, 0, 0, 0, 0, 0, 0, 0, 1},
  {1, 1, 1, 1, 1, 1, 1, 1, 1, 1}
};

// OpenCV 4x4 #0 (8x8 grid with 1-module white border)
const uint8_t ARUCO_4X4_ID0[8][8] = {
  {1, 1, 1, 1, 1, 1, 1, 1},
  {1, 0, 0, 0, 0, 0, 0, 1},
  {1, 0, 1, 0, 1, 1, 0, 1},
  {1, 0, 0, 1, 0, 1, 0, 1},
  {1, 0, 0, 0, 1, 1, 0, 1},
  {1, 0, 0, 0, 1, 0, 0, 1},
  {1, 0, 0, 0, 0, 0, 0, 1},
  {1, 1, 1, 1, 1, 1, 1, 1}
};

enum DisplayMode {
  MODE_ARUCO_5X5 = 0,
  MODE_QR_CODE = 1,
  MODE_ARUCO_MIP = 2,
  MODE_ARUCO_4X4 = 3,
  MODE_SPLIT = 4,
  MODE_COUNT = 5
};

DisplayMode currentMode = MODE_ARUCO_5X5;
bool autoCycle = false;
unsigned long lastCycleMs = 0;
bool lastBtnState = HIGH;

void drawAruco5x5Centered() {
  display.clearDisplay();
  const int moduleSize = 7;
  const int totalSize = 9 * moduleSize; // 63px
  const int startX = (SCREEN_WIDTH - totalSize) / 2; // ~32
  const int startY = (SCREEN_HEIGHT - totalSize) / 2; // 0

  for (int r = 0; r < 9; r++) {
    for (int c = 0; c < 9; c++) {
      uint16_t color = ARUCO_5X5_ID0[r][c] ? SSD1306_WHITE : SSD1306_BLACK;
      display.fillRect(startX + c * moduleSize, startY + r * moduleSize, moduleSize, moduleSize, color);
    }
  }
  display.display();
}

void drawArucoMipCentered() {
  display.clearDisplay();
  const int moduleSize = 6;
  const int totalSize = 10 * moduleSize; // 60px
  const int startX = (SCREEN_WIDTH - totalSize) / 2; // 34
  const int startY = (SCREEN_HEIGHT - totalSize) / 2; // 2

  for (int r = 0; r < 10; r++) {
    for (int c = 0; c < 10; c++) {
      uint16_t color = ARUCO_MIP_ID0[r][c] ? SSD1306_WHITE : SSD1306_BLACK;
      display.fillRect(startX + c * moduleSize, startY + r * moduleSize, moduleSize, moduleSize, color);
    }
  }
  display.display();
}

void drawAruco4x4Centered() {
  display.clearDisplay();
  const int moduleSize = 8;
  const int totalSize = 8 * moduleSize; // 64px
  const int startX = (SCREEN_WIDTH - totalSize) / 2; // 32
  const int startY = 0;

  for (int r = 0; r < 8; r++) {
    for (int c = 0; c < 8; c++) {
      uint16_t color = ARUCO_4X4_ID0[r][c] ? SSD1306_WHITE : SSD1306_BLACK;
      display.fillRect(startX + c * moduleSize, startY + r * moduleSize, moduleSize, moduleSize, color);
    }
  }
  display.display();
}

void drawQRCode(const char* payload) {
  display.clearDisplay();
  QRCode qrcode;
  const int version = 2; // 25x25 modules
  uint8_t qrcodeData[qrcode_getBufferSize(version)];
  qrcode_initText(&qrcode, qrcodeData, version, ECC_LOW, payload);

  const int quietBorder = 1; // 1 module border
  const int totalModules = qrcode.size + 2 * quietBorder; // 27
  const int modulePixel = 2; // 2px per module = 54px
  const int startX = 6;
  const int startY = (SCREEN_HEIGHT - totalModules * modulePixel) / 2; // 5

  // Background white quiet zone
  display.fillRect(startX, startY, totalModules * modulePixel, totalModules * modulePixel, SSD1306_WHITE);

  // Black modules
  for (int y = 0; y < qrcode.size; y++) {
    for (int x = 0; x < qrcode.size; x++) {
      if (qrcode_getModule(&qrcode, x, y)) {
        display.fillRect(
          startX + (x + quietBorder) * modulePixel,
          startY + (y + quietBorder) * modulePixel,
          modulePixel, modulePixel,
          SSD1306_BLACK
        );
      }
    }
  }

  // Text on the right side
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(68, 6);
  display.print("SURGE");
  display.setCursor(68, 16);
  display.print("PREP");
  display.drawLine(68, 27, 122, 27, SSD1306_WHITE);
  display.setCursor(68, 32);
  display.print("QR CODE");
  display.setCursor(68, 44);
  display.print("SCAN ME");
  display.setCursor(68, 54);
  display.print(":5173");

  display.display();
}

void drawSplitView() {
  display.clearDisplay();
  // ArUco 5x5 on left (9x9 modules * 7px = 63px)
  const int moduleSize = 7;
  for (int r = 0; r < 9; r++) {
    for (int c = 0; c < 9; c++) {
      uint16_t color = ARUCO_5X5_ID0[r][c] ? SSD1306_WHITE : SSD1306_BLACK;
      display.fillRect(c * moduleSize, r * moduleSize, moduleSize, moduleSize, color);
    }
  }

  // Label on right
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(68, 4);
  display.print("SURGE");
  display.setCursor(68, 14);
  display.print("PREP");
  display.drawLine(68, 24, 122, 24, SSD1306_WHITE);
  display.setCursor(68, 29);
  display.print("ARUCO");
  display.setCursor(68, 39);
  display.print("5x5 #0");
  display.setCursor(68, 51);
  display.print("READY");

  display.display();
}

void renderCurrentMode() {
  switch (currentMode) {
    case MODE_ARUCO_5X5:
      Serial.println("[Display] Mode 0: ArUco OpenCV 5x5 #0 (Centered Large)");
      drawAruco5x5Centered();
      break;
    case MODE_QR_CODE:
      Serial.println("[Display] Mode 1: QR Code (http://127.0.0.1:5173/)");
      drawQRCode("http://127.0.0.1:5173/");
      break;
    case MODE_ARUCO_MIP:
      Serial.println("[Display] Mode 2: ArUco MIP 36h12 #0 (Centered Large)");
      drawArucoMipCentered();
      break;
    case MODE_ARUCO_4X4:
      Serial.println("[Display] Mode 3: ArUco OpenCV 4x4 #0 (Centered Large)");
      drawAruco4x4Centered();
      break;
    case MODE_SPLIT:
      Serial.println("[Display] Mode 4: Split View (ArUco 5x5 + Label)");
      drawSplitView();
      break;
    default:
      break;
  }
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
    // try fallback address
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3D)) {
      Serial.println("SSD1306 fallback 0x3D also failed.");
    }
  } else {
    Serial.printf("SSD1306 OLED initialized at 0x%02X\n", foundAddress);
  }

  renderCurrentMode();
  lastCycleMs = millis();

  Serial.println("\nCommands via Serial:");
  Serial.println("  '0' : ArUco OpenCV 5x5 #0 (Large Centered - Matches Web Default)");
  Serial.println("  '1' : QR Code (Web URL)");
  Serial.println("  '2' : ArUco MIP 36h12 #0");
  Serial.println("  '3' : ArUco OpenCV 4x4 #0");
  Serial.println("  '4' : Split View (ArUco + Text)");
  Serial.println("  'a' : Toggle auto-cycle mode");
  Serial.println("  ' ' : Next screen");
  Serial.println("Or press BOOT button (GPIO 9) to switch screen\n");
}

void loop() {
  // Check Serial input
  if (Serial.available()) {
    char ch = Serial.read();
    if (ch >= '0' && ch <= '4') {
      currentMode = (DisplayMode)(ch - '0');
      renderCurrentMode();
    } else if (ch == ' ' || ch == 'n') {
      currentMode = (DisplayMode)((currentMode + 1) % MODE_COUNT);
      renderCurrentMode();
    } else if (ch == 'a') {
      autoCycle = !autoCycle;
      Serial.printf("Auto-cycle: %s\n", autoCycle ? "ON" : "OFF");
      lastCycleMs = millis();
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
