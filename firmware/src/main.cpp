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
  MODE_COUNT = 5
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
  display.setCursor(68, 6);
  display.print("SURGE");
  display.setCursor(68, 16);
  display.print("PREP");
  display.drawLine(68, 27, 122, 27, SSD1306_BLACK);
  display.setCursor(68, 33);
  display.print("ARUCO");
  display.setCursor(68, 44);
  display.print("5x5 #0");

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
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3D)) {
      Serial.println("SSD1306 fallback 0x3D also failed.");
    }
  } else {
    Serial.printf("SSD1306 OLED initialized at 0x%02X\n", foundAddress);
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(0xFF); // Maximum contrast
  }

  renderCurrentMode();
  lastCycleMs = millis();

  Serial.println("\nCommands via Serial:");
  Serial.println("  '0' : ArUco OpenCV 5x5 #0");
  Serial.println("  '1' : QR Code (Web URL)");
  Serial.println("  '2' : ArUco MIP 36h12 #0");
  Serial.println("  '3' : ArUco OpenCV 4x4 #0 (High Motion Tolerance)");
  Serial.println("  '4' : Split View");
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
