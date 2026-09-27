/*
 * guide_dog_firmware.ino  —  Zeus Car "body" firmware for the Guide-Dog robot
 *
 * The Raspberry Pi is the brain. This sketch turns the Arduino into a simple,
 * safe motor + sensor controller that talks to the Pi over the USB cable.
 *
 * SETUP (see PROJECT_GUIDE.md, section 8.2):
 *   1. Download SunFounder's Zeus Car code (github.com/sunfounder/zeus-car).
 *   2. Copy the folder "Zeus_Car" and rename the copy "guide_dog_firmware".
 *   3. Delete Zeus_Car.ino from the copy and put THIS file in its place.
 *      (Keep all the other .h/.cpp files — we reuse SunFounder's drivers.)
 *   4. Install libraries: SoftPWM, IRLremote, ArduinoJson (Library Manager).
 *   5. Slide the shield's small switch to the UPLOAD side, then upload.
 *      Leave it on UPLOAD afterwards so the Pi owns the serial port.
 *
 * PROTOCOL (ASCII lines, 115200 baud, end each line with \n)
 *   Pi -> Arduino
 *     M <angle> <power> <rot>   move. angle -180..180 (0 = forward),
 *                               power 0..100, rot -100..100 (spin)
 *     S                         stop now
 *     L <r> <g> <b>             set RGB strips, 0..255 each
 *     H                         reset compass heading ("this way is 0")
 *     P                         ping (Arduino answers PONG)
 *   Arduino -> Pi
 *     READY                     sent once after boot
 *     T <dist_cm> <ir_bits> <heading>    telemetry, every 100 ms
 *     E OBSTACLE | E TIMEOUT    safety stop happened
 *
 * SAFETY (runs even if the Pi crashes):
 *   - No message from the Pi for 500 ms  -> stop.
 *   - Driving forward and something is closer than 20 cm -> stop.
 */

#include <Arduino.h>
#include "SoftPWM.h"
#include "rgb.h"
#include "compass.h"
#include "car_control.h"
#include "ir_obstacle.h"
#include "ultrasonic.h"

#define CMD_TIMEOUT_MS    500   // watchdog: stop if Pi goes quiet
#define TELEMETRY_MS      100   // 10 telemetry lines per second
#define STOP_DISTANCE_CM  20    // emergency brake distance

char lineBuf[48];
uint8_t lineLen = 0;

unsigned long lastCmdMs = 0;
unsigned long lastTelemetryMs = 0;

int16_t curAngle = 0;
int8_t  curPower = 0;
int8_t  curRot   = 0;

bool isMoving() { return curPower != 0 || curRot != 0; }

void stopCar() {
  curPower = 0;
  curRot = 0;
  carStop();
}

void handleLine(char *line) {
  switch (line[0]) {
    case 'M': {
      int a, p, r;
      if (sscanf(line + 1, "%d %d %d", &a, &p, &r) == 3) {
        curAngle = constrain(a, -180, 180);
        curPower = constrain(p, 0, 100);
        curRot   = constrain(r, -100, 100);
        carMove(curAngle, curPower, curRot, false);
      }
      break;
    }
    case 'S':
      stopCar();
      break;
    case 'L': {
      int r, g, b;
      if (sscanf(line + 1, "%d %d %d", &r, &g, &b) == 3) {
        rgbWrite((uint8_t)constrain(r, 0, 255),
                 (uint8_t)constrain(g, 0, 255),
                 (uint8_t)constrain(b, 0, 255));
      }
      break;
    }
    case 'H':
      carResetHeading();
      break;
    case 'P':
      Serial.println(F("PONG"));
      break;
  }
  lastCmdMs = millis();   // any valid line counts as a heartbeat
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        handleLine(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  SoftPWMBegin();          // must come before motors and LEDs
  rgbBegin();
  rgbWrite(ORANGE);        // booting
  carBegin();              // motors + compass
  irObstacleBegin();
  delay(500);
  rgbWrite(GREEN);         // ready
  Serial.println(F("READY"));
  lastCmdMs = millis();
}

void loop() {
  readSerial();
  unsigned long now = millis();

  // Safety 1: the Pi stopped talking -> stop.
  if (isMoving() && now - lastCmdMs > CMD_TIMEOUT_MS) {
    stopCar();
    rgbWrite(ORANGE);
    Serial.println(F("E TIMEOUT"));
  }

  if (now - lastTelemetryMs >= TELEMETRY_MS) {
    lastTelemetryMs = now;
    float dist = ultrasonicRead();          // cm, <= 0 means no reading
    byte  ir   = irObstacleRead();          // bit flags for L/R IR sensors
    int16_t heading = compassReadAngle();   // degrees

    // Safety 2: going forward-ish and something is right in front -> stop.
    bool forwardish = curPower > 0 && abs(curAngle) <= 45;
    if (forwardish && dist > 0 && dist < STOP_DISTANCE_CM) {
      stopCar();
      rgbWrite(RED);
      Serial.println(F("E OBSTACLE"));
    }

    Serial.print(F("T "));
    Serial.print(dist, 1);
    Serial.print(' ');
    Serial.print(ir);
    Serial.print(' ');
    Serial.println(heading);
  }
}
