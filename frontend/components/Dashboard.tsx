"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
  CartesianGrid
} from "recharts";

type RiskLevel = "normal" | "warning" | "critical";

type HealthOut = {
  status: "ok";
  db_kind: string;
  db_target: string;
  nasa_baseline_active: boolean;
  nasa_baseline_file_exists: boolean;
  ws_clients: number;
};

type TelemetryOut = {
  id: number;
  ts: string;
  temp_c: number;
  amps: number;
  vibration: number;
  pulses: number;
  pwm: number;
  is_running: boolean;
  risk: {
    score: number;
    level: RiskLevel;
    health: number;
    reasons: string[];
    eta_seconds?: number | null;
    eta_label?: string | null;
    recommendations?: string[];
    baseline_z_max?: number | null;
  };
  derived: {
    pulse_rate: number;
  };
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";

function levelColor(level: RiskLevel) {
  if (level === "critical") return "var(--bad)";
  if (level === "warning") return "var(--warn)";
  return "var(--good)";
}

function fmt(n: number, digits = 1) {
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(digits);
}

function fmtDuration(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  const hours = minutes / 60;
  return `${hours.toFixed(1)} h`;
}

function shortTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function Dashboard() {
  const [latest, setLatest] = useState<TelemetryOut | null>(null);
  const [history, setHistory] = useState<TelemetryOut[]>([]);
  const [health, setHealth] = useState<HealthOut | null>(null);
  const [wsStatus, setWsStatus] = useState<"connected" | "disconnected">("disconnected");

  const chartData = useMemo(() => {
    const data = history.slice(-180).map((p) => ({
      t: shortTime(p.ts),
      temp: p.temp_c,
      amps: p.amps,
      vib: p.vibration,
      health: p.risk.health,
      pwmRaw: p.pwm,
      pulseRate: p.derived?.pulse_rate ?? 0
    }));
    return data;
  }, [history]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        const [latestRes, histRes] = await Promise.all([
          fetch(`${API_BASE}/api/latest`),
          fetch(`${API_BASE}/api/history?limit=300`)
        ]);
        const latestJson = (await latestRes.json()) as TelemetryOut;
        const histJson = (await histRes.json()) as { items: TelemetryOut[] };
        if (cancelled) return;
        setLatest(latestJson);
        setHistory(histJson.items ?? []);
      } catch {
        // ignore, UI will still work once WS starts pushing
      }

      try {
        const r = await fetch(`${API_BASE}/api/health`);
        const j = (await r.json()) as HealthOut;
        if (!cancelled) setHealth(j);
      } catch {
        // ignore
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => setWsStatus("connected");
    ws.onclose = () => setWsStatus("disconnected");
    ws.onerror = () => setWsStatus("disconnected");

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg?.type === "telemetry" && msg?.data) {
          const t = msg.data as TelemetryOut;
          setLatest(t);
          setHistory((prev) => {
            const next = [...prev, t];
            return next.length > 2000 ? next.slice(-2000) : next;
          });
        }
      } catch {
        // ignore
      }
    };

    // keepalive to help some proxies; backend ignores client messages
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 15000);

    return () => {
      clearInterval(ping);
      try {
        ws.close();
      } catch {
        // ignore
      }
    };
  }, []);

  const level = latest?.risk.level ?? "normal";
  const color = levelColor(level);
  const etaLabel = latest?.risk.eta_label ?? null;
  const etaSeconds = latest?.risk.eta_seconds ?? null;
  const recommendations = latest?.risk.recommendations ?? [];
  const baselineZ = latest?.risk.baseline_z_max ?? null;
  const pulseRate = latest?.derived?.pulse_rate ?? 0;

  return (
    <div className="grid">
      <div className="panel card">
        <div className="row">
          <div className="cardLabel">Статус</div>
          <div className="pill">
            <span className="dot" style={{ background: wsStatus === "connected" ? "var(--good)" : "var(--bad)" }} />
            WS: {wsStatus}
          </div>
        </div>
        <div className="cardValue" style={{ color }}>
          {level.toUpperCase()}
        </div>
        <div className="reasons">
          {(latest?.risk.reasons ?? []).join(" · ") || "—"}
          {latest?.ts ? (
            <>
              <br />
              <span style={{ opacity: 0.85 }}>Last update:</span> {new Date(latest.ts).toLocaleString()}
            </>
          ) : null}
        </div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Температура</div>
        <div className="cardValue">{fmt(latest?.temp_c ?? 0)}°C</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Ток</div>
        <div className="cardValue">{fmt(latest?.amps ?? 0)} A</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Вибрация</div>
        <div className="cardValue">{Math.round(latest?.vibration ?? 0)}</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">PWM</div>
        <div className="cardValue">{latest?.pwm ?? 0}</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Pulses</div>
        <div className="cardValue">{latest?.pulses ?? 0}</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Pulse rate</div>
        <div className="cardValue">{fmt(pulseRate, 1)} /s</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Running</div>
        <div className="cardValue">{latest?.is_running ? "YES" : "NO"}</div>
      </div>

      <div className="panel card">
        <div className="cardLabel">Health</div>
        <div className="cardValue">{latest?.risk.health ?? 100}/100</div>
      </div>

      <div className="panel chart">
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="cardLabel">PWM + Вибрация (последние точки)</div>
          <div className="pill">
            <span className="dot" style={{ background: color }} />
            Risk score: {fmt(latest?.risk.score ?? 0, 2)}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="t" tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }} />
            <YAxis
              yAxisId="vib"
              domain={[0, 1000]}
              tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }}
              tickFormatter={(v) => Math.round(Number(v))}
              label={{
                value: "Vibration (RMS)",
                angle: -90,
                position: "insideLeft",
                fill: "rgba(230,237,245,0.55)"
              }}
            />
            <YAxis
              yAxisId="pwm"
              orientation="right"
              domain={[0, 255]}
              tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }}
              tickFormatter={(v) => Math.round(Number(v))}
              label={{
                value: "PWM (0–255)",
                angle: 90,
                position: "insideRight",
                fill: "rgba(230,237,245,0.55)"
              }}
            />
            <Tooltip
              contentStyle={{
                background: "rgba(16,26,46,0.95)",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 12
              }}
              labelFormatter={(label) => `Time: ${label}`}
              formatter={(value, name) => {
                if (typeof value !== "number") return [value, name];
                if (name === "Vibration") return [`${fmt(value, 1)}`, "Vibration (RMS)"];
                if (name === "PWM") return [`${fmt(value, 0)} / 255`, "PWM"];
                return [value, name];
              }}
            />
            <Legend />
            <Line yAxisId="vib" type="monotone" dataKey="vib" name="Vibration" stroke="#f59e0b" dot={false} />
            <Line yAxisId="pwm" type="monotone" dataKey="pwmRaw" name="PWM" stroke="#fb7185" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="panel chart">
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="cardLabel">Temp + Amps + Health (последние точки)</div>
          <div className="pill">
            <span className="dot" style={{ background: wsStatus === "connected" ? "var(--good)" : "var(--bad)" }} />
            WS: {wsStatus}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="t" tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }} />
            <YAxis
              yAxisId="temp"
              domain={["dataMin - 2", "dataMax + 2"]}
              tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }}
              label={{
                value: "Temp (°C)",
                angle: -90,
                position: "insideLeft",
                fill: "rgba(230,237,245,0.55)"
              }}
            />
            <YAxis
              yAxisId="health"
              orientation="right"
              domain={[0, 100]}
              tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }}
              tickFormatter={(v) => Math.round(Number(v))}
              label={{
                value: "Health (%)",
                angle: 90,
                position: "insideRight",
                fill: "rgba(230,237,245,0.55)"
              }}
            />
            {/* hidden axis for Amps so it doesn't share scale with Temp/Health */}
            <YAxis yAxisId="amps" hide domain={[0, "dataMax + 0.2"]} />
            <Tooltip
              contentStyle={{
                background: "rgba(16,26,46,0.95)",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 12
              }}
              labelFormatter={(label) => `Time: ${label}`}
              formatter={(value, name) => {
                if (typeof value !== "number") return [value, name];
                if (name === "Temp") return [`${fmt(value, 1)} °C`, "Temp"];
                if (name === "Amps") return [`${fmt(value, 2)} A`, "Amps"];
                if (name === "Health") return [`${fmt(value, 0)} %`, "Health"];
                return [value, name];
              }}
            />
            <Legend />
            <Line yAxisId="temp" type="monotone" dataKey="temp" name="Temp" stroke="#60a5fa" dot={false} />
            <Line yAxisId="amps" type="monotone" dataKey="amps" name="Amps" stroke="#a78bfa" dot={false} />
            <Line yAxisId="health" type="monotone" dataKey="health" name="Health" stroke="#34d399" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="panel wide">
        <div className="sectionTitle">Predictive maintenance (MVP)</div>
        <div className="kv">
          <div className="kvItem">
            <div className="kvKey">ETA</div>
            <div className="kvVal">
              {etaLabel ? `${etaLabel}: ` : ""}
              {fmtDuration(etaSeconds)}
            </div>
          </div>
          <div className="kvItem">
            <div className="kvKey">NASA baseline</div>
            <div className="kvVal">
              {health ? (
                <>
                  file: {health.nasa_baseline_file_exists ? "yes" : "no"} · active:{" "}
                  {health.nasa_baseline_active ? "yes" : "no"}
                </>
              ) : (
                "—"
              )}
            </div>
          </div>
          <div className="kvItem">
            <div className="kvKey">Z-score max</div>
            <div className="kvVal">{baselineZ == null ? "—" : fmt(baselineZ, 2)}</div>
          </div>
          <div className="kvItem">
            <div className="kvKey">DB</div>
            <div className="kvVal">{health ? health.db_kind : "—"}</div>
          </div>
        </div>

        <div className="row" style={{ marginTop: 12, alignItems: "flex-start" }}>
          <div style={{ flex: 1 }}>
            <div className="miniTitle">Recommendations</div>
            <ul className="list">
              {(recommendations.length ? recommendations : ["—"]).map((x, i) => (
                <li key={`${x}-${i}`}>{x}</li>
              ))}
            </ul>
          </div>
          <div style={{ flex: 1 }}>
            <div className="miniTitle">Why (signals)</div>
            <ul className="list">
              {((latest?.risk.reasons ?? []).length ? (latest?.risk.reasons ?? []) : ["—"]).map((x, i) => (
                <li key={`${x}-${i}`}>{x}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
