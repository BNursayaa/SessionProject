// Add this to your Arduino sketch (UNO)
// Call printTelemetryJson(...) once per second after reading sensors.

void printTelemetryJson(
  float tempC,
  float amps,
  long vibration,
  long pulses,
  int pwm,
  bool isRunning
) {
  Serial.print(F("{\"temp_c\":"));
  Serial.print(tempC, 2);
  Serial.print(F(",\"amps\":"));
  Serial.print(amps, 2);
  Serial.print(F(",\"vibration\":"));
  Serial.print(vibration);
  Serial.print(F(",\"pulses\":"));
  Serial.print(pulses);
  Serial.print(F(",\"pwm\":"));
  Serial.print(pwm);
  Serial.print(F(",\"is_running\":"));
  Serial.print(isRunning ? F("true") : F("false"));
  Serial.println(F("}"));
}

