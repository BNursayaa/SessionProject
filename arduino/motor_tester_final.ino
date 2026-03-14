#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SD.h>
#include <MPU6050.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>

#define PIN_IN1 6         // PWM на драйвер (скорость)
#define PIN_IN2 7         // DIR на драйвер (направление)
#define PIN_ENC_A 8
#define PIN_ENC_B 9
#define PIN_ENC_SW 10
#define PIN_PULSE 3       // счётчик (Interrupt 1 на UNO)
#define PIN_DS18B20 2
#define SD_CS 4

const int PWM_STEP = 10;
const int PWM_MIN_SPIN = 30;          // below this: output=0
const int PWM_KICK = 100;             // short kick to overcome inertia
const unsigned long PWM_KICK_MS = 300;

int pwmOutFromSet(int setPwm) {
  if (setPwm < PWM_MIN_SPIN) return 0;
  return constrain(setPwm, 0, 255);
}

LiquidCrystal_I2C lcd(0x27, 16, 2);
MPU6050 mpu(0x68);
OneWire oneWire(PIN_DS18B20);
DallasTemperature sensors(&oneWire);

volatile long pulseCount = 0;
int motorSpeed = 0;               // 0..255 (0 = stop)
int lastPwmOut = 0;               // last applied output PWM (after deadzone)
bool isRunning = false;
unsigned long lastScanTime = 0;

float lastTemp = 0;
float lastAmps = 0;
float vibrationRms = 0.0f; // RMS вибрация (для сайта) — ближе к NASA IMS RMS

float maxTemp = 0;
float maxAmps = 0;
float maxVib = 0.0f;              // пиковая RMS вибрация (для LCD/логов)
int zeroPoint = 512;              // ACS712 zero calibration

void countPulse() {
  pulseCount++;
}

void saveDataToSD();
void showIdleScreen();
void updateIdlePwmLine();
void handleEncoder();
void scanSensors();
void updateResearchDisplay(float tempC, float amps, long pulses, float mvib);
void updateVibrationRms(bool running);
void printTelemetryJson(float tempC, float amps, float vibration, long pulses, int pwm, bool isRunning);
void updateTempNonBlocking();
bool startMotor();
void stopMotor();
void handleSerialControl();


void setup() {
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  pinMode(PIN_ENC_SW, INPUT_PULLUP);
  pinMode(PIN_PULSE, INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(PIN_PULSE), countPulse, FALLING);

  digitalWrite(PIN_IN2, LOW);
  analogWrite(PIN_IN1, 0);

  Wire.begin();
  Wire.setClock(100000);
  lcd.init();
  lcd.backlight();

  Serial.begin(115200);

  lcd.print(F("ACS CALIBRATE..."));
  long sum = 0;
  for (int i = 0; i < 100; i++) {
    sum += analogRead(A0);
    delay(5);
  }
  zeroPoint = sum / 100;

  lcd.clear();
  lcd.print(F("MPU INIT..."));
  mpu.initialize();
  mpu.setSleepEnabled(false);
  delay(500);

  sensors.begin();
  sensors.setResolution(9);
  sensors.setWaitForConversion(false); // обязательно для неблокирующего режима
  updateTempNonBlocking();             // старт первой конверсии

  if (!SD.begin(SD_CS)) {
    lcd.setCursor(0, 1);
    lcd.print(F("SD CARD ERROR!"));
    delay(1000);
  }

  lcd.clear();
  showIdleScreen();
}


void loop() {
  handleSerialControl();

  static bool lastSwState = HIGH;
  bool swState = digitalRead(PIN_ENC_SW);

  if (swState == LOW && lastSwState == HIGH) {
    delay(50); // антидребезг

    if (isRunning) stopMotor();
    else startMotor();
  }
  lastSwState = swState;

  if (isRunning) {
    handleEncoder();         // можно менять PWM во время работы
    updateTempNonBlocking(); // температура без блокировки
    int pwmOut = pwmOutFromSet(motorSpeed);
    bool motorActive = (pwmOut > 0);
    updateVibrationRms(motorActive); // обновляем vibrationRms/maxVib только когда мотор реально крутится

    if (millis() - lastScanTime >= 500) {
      lastScanTime = millis();
      scanSensors();

      float tempC = lastTemp;
      float amps = lastAmps;
      noInterrupts();
      long pulses = pulseCount;
      interrupts();
      float vibNow = vibrationRms;      // RMS (на сайт)
      float mvib = maxVib;              // peak RMS (на LCD)
      int pwmSet = pwmOut;
      bool running = motorActive;

      printTelemetryJson(tempC, amps, vibNow, pulses, pwmSet, running);
      updateResearchDisplay(tempC, amps, pulses, mvib);
    }
  } else {
    updateVibrationRms(false);
    handleEncoder();
  }
}



void handleSerialControl() {
  static char buf[24];
  static uint8_t idx = 0;

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[idx] = '\0';
      idx = 0;

      for (uint8_t i = 0; buf[i]; i++) {
        if (buf[i] >= 'a' && buf[i] <= 'z') buf[i] = (char)(buf[i] - 32);
      }

      if (!buf[0]) return;

      if (strcmp(buf, "START") == 0) {
        if (!isRunning) startMotor();
      } else if (strcmp(buf, "STOP") == 0) {
        if (isRunning) stopMotor();
      } else if (strcmp(buf, "PWM_UP") == 0) {
        motorSpeed = constrain(motorSpeed + PWM_STEP, 0, 255);
        if (!isRunning) {
          updateIdlePwmLine();
          printTelemetryJson(lastTemp, 0.0f, 0.0f, 0, motorSpeed, false);
        } else {
          int out = pwmOutFromSet(motorSpeed);
          if (out == 0 && lastPwmOut > 0) {
            stopMotor();
            return;
          }
          bool motorActive = (out > 0);
          if (lastPwmOut == 0 && out > 0) {
            analogWrite(PIN_IN1, max(out, PWM_KICK));
            delay(PWM_KICK_MS);
          }
          digitalWrite(PIN_IN2, LOW);
          analogWrite(PIN_IN1, out);
          lastPwmOut = out;

          noInterrupts();
          long pulses = pulseCount;
          interrupts();
          printTelemetryJson(lastTemp, lastAmps, vibrationRms, pulses, out, motorActive);
        }
      } else if (strcmp(buf, "PWM_DOWN") == 0) {
        motorSpeed = constrain(motorSpeed - PWM_STEP, 0, 255);
        if (!isRunning) {
          updateIdlePwmLine();
          printTelemetryJson(lastTemp, 0.0f, 0.0f, 0, motorSpeed, false);
        } else {
          int out = pwmOutFromSet(motorSpeed);
          if (out == 0 && lastPwmOut > 0) {
            stopMotor();
            return;
          }
          bool motorActive = (out > 0);
          if (lastPwmOut == 0 && out > 0) {
            analogWrite(PIN_IN1, max(out, PWM_KICK));
            delay(PWM_KICK_MS);
          }
          digitalWrite(PIN_IN2, LOW);
          analogWrite(PIN_IN1, out);
          lastPwmOut = out;

          noInterrupts();
          long pulses = pulseCount;
          interrupts();
          printTelemetryJson(lastTemp, lastAmps, vibrationRms, pulses, out, motorActive);
        }
      } else if (strcmp(buf, "TOGGLE") == 0) {
        if (isRunning) stopMotor();
        else startMotor();
      }

      return;
    }

    if (idx < sizeof(buf) - 1) {
      buf[idx++] = c;
    }
  }
}

bool startMotor() {
  int pwmOut = pwmOutFromSet(motorSpeed);

  if (pwmOut <= 0) {
    isRunning = false;
    lcd.clear();
    lcd.print(F("SET PWM >= 30"));
    delay(800);
    lcd.clear();
    showIdleScreen();
    return false;
  }

  isRunning = true;
  lastPwmOut = pwmOut;

  noInterrupts();
  pulseCount = 0;
  interrupts();
  maxVib = 0;
  maxAmps = 0;
  maxTemp = 0;

  lcd.clear();
  lcd.print(F("KICKSTARTING..."));
  int kickSpeed = max(pwmOut, PWM_KICK);
  digitalWrite(PIN_IN2, LOW);
  analogWrite(PIN_IN1, kickSpeed);
  delay(PWM_KICK_MS);

  analogWrite(PIN_IN1, pwmOut);
  lcd.clear();
  return true;
}

void stopMotor() {
  isRunning = false;
  lastPwmOut = 0;

  digitalWrite(PIN_IN2, LOW);
  analogWrite(PIN_IN1, 0);

  noInterrupts();
  long pulsesSnap = pulseCount;
  interrupts();

  (void)pulsesSnap;
  printTelemetryJson(lastTemp, 0.0f, 0.0f, 0, motorSpeed, false);

  saveDataToSD();
  lcd.clear();
  showIdleScreen();
}

void updateVibrationRms(bool running) {
  static float lp = 0.0f;                // low-pass baseline (сырой суммы)
  static unsigned long lastSampleMs = 0; // частота выборки
  static unsigned long windowStartMs = 0;
  static float sumSq = 0.0f;
  static unsigned int n = 0;

  const unsigned long sampleEveryMs = 20;   // ~50 Hz
  const unsigned long windowMs = 1000;      // RMS window

  unsigned long now = millis();
  if (windowStartMs == 0) windowStartMs = now;

  if (now - lastSampleMs < sampleEveryMs) {
  } else {
    lastSampleMs = now;

    int16_t ax, ay, az;
    mpu.getAcceleration(&ax, &ay, &az);

    long raw = (long)abs(ax) + (long)abs(ay) + (long)abs(az); // 32-bit sum
    if (lp == 0.0f) lp = (float)raw;
    lp = lp * 0.98f + (float)raw * 0.02f;

    float dyn = (float)labs(raw - (long)lp) / 100.0f; // dyn scale
    if (running) {
      sumSq += dyn * dyn;
      n++;
    }
  }

  if (now - windowStartMs >= windowMs) {
    if (running && n > 0) {
      vibrationRms = sqrt(sumSq / (float)n);
      if (vibrationRms > maxVib) maxVib = vibrationRms;
    } else {
      vibrationRms = 0.0f;
    }
    sumSq = 0.0f;
    n = 0;
    windowStartMs = now;
  }
}

void scanSensors() {
  long rawSum = 0;
  for (int i = 0; i < 10; i++) rawSum += analogRead(A0);
  lastAmps = abs((rawSum / 10) - zeroPoint) * 0.1;
  if (lastAmps < 0.08) lastAmps = 0; // шум
  if (lastAmps > maxAmps) maxAmps = lastAmps;
}

void updateResearchDisplay(float tempC, float amps, long pulses, float mvib) {
  lcd.setCursor(0, 0);
  lcd.print(tempC, 1); lcd.print(F("C "));
  lcd.print(amps, 1);  lcd.print(F("A   "));

  lcd.setCursor(0, 1);
  lcd.print(F("P:"));  lcd.print(pulses);
  lcd.print(F(" MV:")); lcd.print(mvib, 0);
  lcd.print(F("    "));
}

void showIdleScreen() {
  lcd.setCursor(0, 0);
  lcd.print(F("MOTOR: READY    "));
  updateIdlePwmLine();
}

void updateIdlePwmLine() {
  int out = pwmOutFromSet(motorSpeed);
  lcd.setCursor(0, 1);
  lcd.print(F("S:"));
  lcd.print(motorSpeed);
  lcd.print(F(" O:"));
  lcd.print(out);
  lcd.print(F("      "));
}

void handleEncoder() {
  static int lastA = HIGH;
  int currentA = digitalRead(PIN_ENC_A);

  if (currentA != lastA && currentA == LOW) {
    if (digitalRead(PIN_ENC_B) != currentA) motorSpeed += PWM_STEP;
    else motorSpeed -= PWM_STEP;
    motorSpeed = constrain(motorSpeed, 0, 255);

    if (!isRunning) {
      updateIdlePwmLine();
      lastPwmOut = 0;
      printTelemetryJson(lastTemp, 0.0f, 0.0f, 0, motorSpeed, false);
    }

    if (isRunning) {
      digitalWrite(PIN_IN2, LOW);
      int out = pwmOutFromSet(motorSpeed);
      bool motorActive = (out > 0);
      if (out == 0 && lastPwmOut > 0) {
        stopMotor();
        lastA = currentA;
        return;
      }
      if (lastPwmOut == 0 && out > 0) {
        analogWrite(PIN_IN1, max(out, PWM_KICK));
        delay(PWM_KICK_MS);
      }
      analogWrite(PIN_IN1, out);
      lastPwmOut = out;

      noInterrupts();
      long pulses = pulseCount;
      interrupts();

      printTelemetryJson(lastTemp, lastAmps, vibrationRms, pulses, out, motorActive);
    }
  }

  lastA = currentA;
}

void saveDataToSD() {
  lcd.setCursor(0, 0);
  lcd.print(F("WRITING SD...   "));

  File dataFile = SD.open("motor.txt", FILE_WRITE);
  if (dataFile) {
    dataFile.println(F("--- TEST RESULTS ---"));
    dataFile.print(F("PWM SPEED: ")); dataFile.println(motorSpeed);
    dataFile.print(F("MAX TEMP:  ")); dataFile.println(maxTemp);
    dataFile.print(F("MAX AMPS:  ")); dataFile.println(maxAmps);
    dataFile.print(F("MAX VIB:   ")); dataFile.println(maxVib, 3);
    dataFile.print(F("PULSES:    ")); dataFile.println(pulseCount);
    dataFile.println(F("--------------------"));
    dataFile.println("");
    dataFile.close();
    delay(600);
  } else {
    lcd.setCursor(0, 1);
    lcd.print(F("SAVE ERROR!     "));
    delay(1000);
  }
}

void printTelemetryJson(float tempC, float amps, float vibration, long pulses, int pwm, bool isRunningFlag) {
  Serial.print(F("{\"temp_c\":"));
  Serial.print(tempC, 2);
  Serial.print(F(",\"amps\":"));
  Serial.print(amps, 2);
  Serial.print(F(",\"vibration\":"));
  Serial.print(vibration, 3);
  Serial.print(F(",\"pulses\":"));
  Serial.print(pulses);
  Serial.print(F(",\"pwm\":"));
  Serial.print(pwm);
  Serial.print(F(",\"is_running\":"));
  Serial.print(isRunningFlag ? F("true") : F("false"));
  Serial.println(F("}"));
}

void updateTempNonBlocking() {
  static bool pending = false;
  static unsigned long t0 = 0;

  if (!pending) {
    sensors.requestTemperatures();
    pending = true;
    t0 = millis();
    return;
  }

  if (millis() - t0 >= 110) {
    float t = sensors.getTempCByIndex(0);
    lastTemp = t;
    if (t > maxTemp) maxTemp = t;
    pending = false;
  }
}
