from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from dotenv import load_dotenv
import requests


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Telemetry:
    temp_c: float
    amps: float
    vibration: float
    pulses: int
    pwm: int
    is_running: bool

    def to_api_payload(self) -> dict[str, Any]:
        return {
            "ts": utc_now_iso(),
            "temp_c": float(self.temp_c),
            "amps": float(self.amps),
            "vibration": float(self.vibration),
            "pulses": int(self.pulses),
            "pwm": int(self.pwm),
            "is_running": bool(self.is_running),
        }


def parse_line(line: str) -> Telemetry | None:
    s = line.strip()
    if not s:
        return None

    # JSON per line (recommended)
    if s.startswith("{") and s.endswith("}"):
        obj = json.loads(s)
        return Telemetry(
            temp_c=float(obj["temp_c"]),
            amps=float(obj["amps"]),
            vibration=float(obj["vibration"]),
            pulses=int(obj["pulses"]),
            pwm=int(obj["pwm"]),
            is_running=bool(obj["is_running"]),
        )

    # CSV fallback: temp,amps,vibration,pulses,pwm,is_running
    parts = [p.strip() for p in s.split(",")]
    if len(parts) == 6:
        return Telemetry(
            temp_c=float(parts[0]),
            amps=float(parts[1]),
            vibration=float(parts[2]),
            pulses=int(float(parts[3])),
            pwm=int(float(parts[4])),
            is_running=parts[5].lower() in ("1", "true", "yes", "on"),
        )

    return None


def post_telemetry(api_base: str, telemetry: Telemetry, timeout_s: float = 2.0) -> None:
    url = f"{api_base.rstrip('/')}/api/telemetry"
    payload = telemetry.to_api_payload()
    r = requests.post(url, json=payload, timeout=timeout_s)
    if r.status_code >= 400:
        # FastAPI returns useful JSON validation details for 422; include it in the error.
        detail: Any
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise requests.HTTPError(
            f"{r.status_code} {r.reason} for {url}; payload={payload}; detail={detail}",
            response=r,
        )
    r.raise_for_status()


def simulate_stream(interval_s: float) -> Iterable[Telemetry]:
    is_running = True
    pwm = 120
    pulses = 0
    temp = 28.0
    amps = 0.25
    vib = 90.0

    while True:
        # Random events
        if random.random() < 0.02:
            is_running = not is_running
        if random.random() < 0.08 and is_running:
            pwm = max(30, min(255, pwm + random.choice([-10, 10, 20, -20])))

        if is_running:
            load = pwm / 255.0
            amps = max(0.0, amps * 0.6 + (0.15 + 1.2 * load) * 0.4 + random.uniform(-0.03, 0.03))
            temp = temp + (0.02 + 0.12 * load) + random.uniform(-0.05, 0.05)
            vib = max(0.0, vib * 0.7 + (60 + 500 * load) * 0.3 + random.uniform(-15, 15))
            pulses += int(10 + 120 * load + random.uniform(-2, 2))
        else:
            amps = max(0.0, amps * 0.7 + random.uniform(-0.02, 0.02))
            temp = max(22.0, temp - 0.10 + random.uniform(-0.03, 0.03))
            vib = max(0.0, vib * 0.6 + random.uniform(-5, 5))

        yield Telemetry(temp_c=temp, amps=amps, vibration=vib, pulses=pulses, pwm=pwm if is_running else 0, is_running=is_running)
        time.sleep(interval_s)


def run_simulate(api_base: str, interval_s: float, verbose: bool) -> None:
    for t in simulate_stream(interval_s):
        try:
            post_telemetry(api_base, t)
            if verbose:
                print("POST", t.to_api_payload())
        except Exception as e:
            print(f"[gateway] post failed: {e}", file=sys.stderr)
            time.sleep(1.0)


def run_serial(api_base: str, port: str, baud: int, verbose: bool) -> None:
    try:
        import serial  # type: ignore
    except Exception as e:
        raise SystemExit(f"pyserial not installed: {e}")

    reconnect_delay_s = 1.0

    while True:
        try:
            with serial.Serial(port=port, baudrate=baud, timeout=1) as ser:
                print(f"[gateway] reading serial {port} @ {baud}")
                while True:
                    try:
                        raw = ser.readline()
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        # Common on Windows when the board resets or the COM port is grabbed by another app:
                        # "GetOverlappedResult failed (PermissionError(13, 'Отказано в доступе.', ...))"
                        print(f"[gateway] serial read error: {e}; reconnecting...", file=sys.stderr)
                        break

                    if not raw:
                        continue

                    try:
                        line = raw.decode("utf-8", errors="ignore")
                        t = parse_line(line)
                        if t is None:
                            if verbose:
                                print("[gateway] skip:", line.strip())
                            continue
                        post_telemetry(api_base, t)
                        if verbose:
                            print("POST", t.to_api_payload())
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        print(f"[gateway] error: {e}", file=sys.stderr)
                        time.sleep(0.5)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[gateway] serial open error: {e}; retrying...", file=sys.stderr)

        time.sleep(reconnect_delay_s)


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(description="UNO Serial → Digital Twin backend gateway")
    p.add_argument("--api-base", default=os.getenv("DT_API_BASE", "http://localhost:8000"))
    p.add_argument("--simulate", action="store_true", help="Generate synthetic telemetry (no Arduino needed)")
    p.add_argument("--interval", type=float, default=1.0, help="Simulate interval seconds")
    p.add_argument("--port", default=os.getenv("SERIAL_PORT", "COM3"))
    p.add_argument("--baud", type=int, default=int(os.getenv("SERIAL_BAUD", "9600")))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.simulate:
        run_simulate(args.api_base, args.interval, args.verbose)
    else:
        run_serial(args.api_base, args.port, args.baud, args.verbose)


if __name__ == "__main__":
    main()
