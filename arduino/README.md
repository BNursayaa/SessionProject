# Arduino UNO → Serial telemetry

Your макет currently shows values on LCD and saves to SD.  
To connect it to the website, the UNO must also print telemetry to **Serial** (USB).

## Recommended format

One JSON object per line (the gateway reads it):

```json
{"temp_c": 36.5, "amps": 0.4, "vibration": 120, "pulses": 1234, "pwm": 150, "is_running": true}
```

## How to integrate

1) In `setup()` add:

- `Serial.begin(9600);`

2) After you update `lastTemp`, `lastAmps`, `vibrationIntensity`, `pulseCount`, `motorSpeed`, `isRunning`,
call the helper from `serial_telemetry_snippet.ino`.

