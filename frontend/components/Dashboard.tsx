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
  CartesianGrid,
  ReferenceLine
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

type ControlAction = "start" | "stop" | "pwm_up" | "pwm_down";

type ControlCommandOut = {
  id: number;
  ts: string;
  action: ControlAction;
  status: "pending" | "claimed" | "done" | "failed";
  source?: string | null;
  claimed_by?: string | null;
  claimed_at?: string | null;
  done_at?: string | null;
  error?: string | null;
};

type ControlStateOut = {
  desired_pwm: number;
  updated_at: string;
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
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  const [controlBusy, setControlBusy] = useState(false);
  const [controlMsg, setControlMsg] = useState<string | null>(null);
  const [desiredPwm, setDesiredPwm] = useState<number>(0);

  const chartData = useMemo(() => {
    const data = history.slice(-180).map((p) => ({
      t: new Date(p.ts).getTime(),
      temp: p.temp_c,
      amps: p.amps,
      vib: p.vibration,
      health: p.risk.health,
      pwmRaw: p.pwm,
      running: p.is_running,
      pulseRate: p.derived?.pulse_rate ?? 0
    }));
    return data;
  }, [history]);

  const runMarkers = useMemo(() => {
    const markers: Array<{ x: number; kind: "start" | "stop" }> = [];
    if (chartData.length < 2) return markers;
    let prev = Boolean(chartData[0]?.running);
    for (let i = 1; i < chartData.length; i++) {
      const cur = Boolean(chartData[i]?.running);
      if (cur !== prev) {
        markers.push({ x: Number(chartData[i]!.t), kind: cur ? "start" : "stop" });
        prev = cur;
      }
    }
    return markers.slice(-10);
  }, [chartData]);

  const session = useMemo(() => {
    if (!history.length) return null;
    let prev = Boolean(history[0]!.is_running);
    let lastStartTs: string | null = prev ? history[0]!.ts : null;
    let lastStopTs: string | null = null;

    for (let i = 1; i < history.length; i++) {
      const cur = Boolean(history[i]!.is_running);
      if (!prev && cur) {
        lastStartTs = history[i]!.ts;
        lastStopTs = null;
      } else if (prev && !cur) {
        lastStopTs = history[i]!.ts;
      }
      prev = cur;
    }

    const running = Boolean(history[history.length - 1]!.is_running);
    const startMs = lastStartTs ? new Date(lastStartTs).getTime() : null;
    const stopMs = lastStopTs ? new Date(lastStopTs).getTime() : null;
    const durSeconds =
      startMs == null ? null : Math.max(0, Math.round(((running ? nowMs : stopMs ?? nowMs) - startMs) / 1000));

    return { running, lastStartTs, lastStopTs, durSeconds };
  }, [history, nowMs]);

  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (wsStatus === "connected") return;
    let cancelled = false;
    const id = setInterval(() => {
      void (async () => {
        try {
          const [latestRes, stateRes, healthRes] = await Promise.all([
            fetch(`${API_BASE}/api/latest`),
            fetch(`${API_BASE}/api/control/state`),
            fetch(`${API_BASE}/api/health`)
          ]);
          if (cancelled) return;
          if (latestRes.ok) {
            const t = (await latestRes.json()) as TelemetryOut;
            setLatest(t);
            setHistory((prev) => {
              const last = prev.length ? prev[prev.length - 1] : null;
              if (last && last.id === t.id) return prev;
              const next = [...prev, t];
              return next.length > 2000 ? next.slice(-2000) : next;
            });
          }
          if (stateRes.ok) {
            const st = (await stateRes.json()) as ControlStateOut;
            if (typeof st?.desired_pwm === "number") setDesiredPwm(st.desired_pwm);
          }
          if (healthRes.ok) setHealth((await healthRes.json()) as HealthOut);
        } catch {
        }
      })();
    }, 1500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [wsStatus]);

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
      }

      try {
        const r = await fetch(`${API_BASE}/api/health`);
        const j = (await r.json()) as HealthOut;
        if (!cancelled) setHealth(j);
      } catch {
      }

      try {
        const r = await fetch(`${API_BASE}/api/control/state`);
        const j = (await r.json()) as ControlStateOut;
        if (!cancelled && typeof j?.desired_pwm === "number") setDesiredPwm(j.desired_pwm);
      } catch {
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    let backoffMs = 500;
    let ws: WebSocket | null = null;
    let ping: ReturnType<typeof setInterval> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const scheduleReconnect = () => {
      if (stopped) return;
      if (retry) clearTimeout(retry);
      retry = setTimeout(() => connect(), backoffMs);
      backoffMs = Math.min(5000, Math.round(backoffMs * 1.6));
    };

    const onMessage = (ev: MessageEvent) => {
      try {
        const msg = JSON.parse(String(ev.data));
        if (msg?.type === "telemetry" && msg?.data) {
          const t = msg.data as TelemetryOut;
          setLatest(t);
          setHistory((prev) => {
            const next = [...prev, t];
            return next.length > 2000 ? next.slice(-2000) : next;
          });
        } else if ((msg?.type === "control_ack" || msg?.type === "control") && msg?.data) {
          const c = msg.data as ControlCommandOut;
          const label =
            c.action === "start"
              ? "Start"
              : c.action === "stop"
                ? "Stop"
                : c.action === "pwm_up"
                  ? "PWM +"
                  : "PWM -";
          const status = c.status?.toUpperCase?.() ?? "";
          setControlMsg(`${label}: ${status}${c.error ? ` (${c.error})` : ""}`);
          setTimeout(() => setControlMsg(null), 2500);
        } else if (msg?.type === "control_state" && msg?.data) {
          const st = msg.data as ControlStateOut;
          if (typeof st?.desired_pwm === "number") setDesiredPwm(st.desired_pwm);
        }
      } catch {
      }
    };

    const connect = () => {
      if (stopped) return;
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        setWsStatus("disconnected");
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        setWsStatus("connected");
        backoffMs = 500;
      };
      ws.onclose = () => {
        setWsStatus("disconnected");
        scheduleReconnect();
      };
      ws.onerror = () => setWsStatus("disconnected");
      ws.onmessage = onMessage;

      if (ping) clearInterval(ping);
      ping = setInterval(() => {
        try {
          if (ws?.readyState === WebSocket.OPEN) ws.send("ping");
        } catch {
        }
      }, 15000);
    };

    connect();

    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      if (ping) clearInterval(ping);
      try {
        ws?.close();
      } catch {
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
  const runningNow = Boolean(latest?.is_running ?? session?.running);
  const lastUpdateAgeSec = latest?.ts ? Math.max(0, Math.round((nowMs - new Date(latest.ts).getTime()) / 1000)) : null;

  async function sendControl(action: ControlAction) {
    setControlBusy(true);
    setControlMsg(null);

    if (action === "pwm_up") setDesiredPwm((p) => Math.min(255, p + 10));
    if (action === "pwm_down") setDesiredPwm((p) => Math.max(0, p - 10));
    try {
      const r = await fetch(`${API_BASE}/api/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, source: "ui" })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || `HTTP ${r.status}`);
      }
      setControlMsg(
        action === "start"
          ? "Start command queued"
          : action === "stop"
            ? "Stop command queued"
            : action === "pwm_up"
              ? "PWM + command queued"
              : "PWM - command queued"
      );
      setTimeout(() => setControlMsg(null), 2000);
    } catch (e) {
      setControlMsg(`Control failed: ${String(e)}`);
      setTimeout(() => setControlMsg(null), 3000);
    } finally {
      setControlBusy(false);
    }
  }

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
                {wsStatus !== "connected" && lastUpdateAgeSec != null ? (
                  <>
                    <br />
                    <span style={{ opacity: 0.85 }}>Age:</span> {lastUpdateAgeSec}s
                  </>
                ) : null}
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
        <div className="cardLabel">PWM (Set)</div>
        <div className="row" style={{ alignItems: "baseline" }}>
          <div className="cardValue" style={{ marginTop: 8 }}>
            {desiredPwm}
          </div>
          <div className="btnGroup" aria-label="PWM controls">
            <button
              className="btn btnSmall"
              disabled={controlBusy}
              onClick={() => sendControl("pwm_down")}
              title="PWM -10"
            >
              -
            </button>
            <button
              className="btn btnSmall"
              disabled={controlBusy}
              onClick={() => sendControl("pwm_up")}
              title="PWM +10"
            >
              +
            </button>
          </div>
        </div>
        <div className="reasons" style={{ marginTop: 8 }}>
          <span style={{ opacity: 0.85 }}>Out PWM:</span> {latest?.pwm ?? 0}
        </div>
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
        <div className="cardLabel">Session</div>
        <div className="row" style={{ alignItems: "baseline" }}>
          <div className="cardValue" style={{ marginTop: 8 }}>
            {session?.running ? "RUNNING" : "STOPPED"}
          </div>
          <div className="btnGroup" aria-label="Session controls">
            {!runningNow ? (
              <button
                className="btn btnPrimary"
                disabled={controlBusy}
                onClick={() => sendControl("start")}
                title="Send START command to the gateway (Arduino)"
              >
                {controlBusy ? "..." : "Start"}
              </button>
            ) : (
              <button
                className="btn btnDanger"
                disabled={controlBusy}
                onClick={() => sendControl("stop")}
                title="Send STOP command to the gateway (Arduino)"
              >
                {controlBusy ? "..." : "Stop"}
              </button>
            )}
          </div>
        </div>
        <div className="reasons">
          {controlMsg ? (
            <>
              <span style={{ opacity: 0.85 }}>Control:</span> {controlMsg}
              <br />
            </>
          ) : null}
          {session?.durSeconds != null ? (
            <>
              <span style={{ opacity: 0.85 }}>Duration:</span> {fmtDuration(session.durSeconds)}
              <br />
            </>
          ) : null}
          {session?.lastStartTs ? (
            <>
              <span style={{ opacity: 0.85 }}>Start:</span> {new Date(session.lastStartTs).toLocaleTimeString()}
              <br />
            </>
          ) : null}
          {session?.lastStopTs ? (
            <>
              <span style={{ opacity: 0.85 }}>Stop:</span> {new Date(session.lastStopTs).toLocaleTimeString()}
            </>
          ) : null}
        </div>
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
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }}
              tickFormatter={(v) =>
                new Date(Number(v)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
              }
            />
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
              labelFormatter={(label) =>
                `Time: ${new Date(Number(label)).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit"
                })}`
              }
              formatter={(value, name) => {
                if (typeof value !== "number") return [value, name];
                if (name === "Vibration") return [`${fmt(value, 1)}`, "Vibration (RMS)"];
                if (name === "PWM") return [`${fmt(value, 0)} / 255`, "PWM"];
                return [value, name];
              }}
            />
            <Legend />
            {runMarkers.map((m, i) => (
              <ReferenceLine
                key={`${m.kind}-${m.x}-${i}`}
                x={m.x}
                yAxisId="vib"
                stroke={m.kind === "start" ? "rgba(52, 211, 153, 0.55)" : "rgba(248, 113, 113, 0.55)"}
                strokeDasharray="3 6"
                label={{
                  value: m.kind === "start" ? "START" : "STOP",
                  position: "insideTop",
                  fill: "rgba(230,237,245,0.55)",
                  fontSize: 10
                }}
              />
            ))}
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
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{ fill: "rgba(230,237,245,0.65)", fontSize: 11 }}
              tickFormatter={(v) =>
                new Date(Number(v)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
              }
            />
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
              labelFormatter={(label) =>
                `Time: ${new Date(Number(label)).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit"
                })}`
              }
              formatter={(value, name) => {
                if (typeof value !== "number") return [value, name];
                if (name === "Temp") return [`${fmt(value, 1)} °C`, "Temp"];
                if (name === "Amps") return [`${fmt(value, 2)} A`, "Amps"];
                if (name === "Health") return [`${fmt(value, 0)} %`, "Health"];
                return [value, name];
              }}
            />
            <Legend />
            {runMarkers.map((m, i) => (
              <ReferenceLine
                key={`${m.kind}-${m.x}-${i}`}
                x={m.x}
                yAxisId="temp"
                stroke={m.kind === "start" ? "rgba(52, 211, 153, 0.45)" : "rgba(248, 113, 113, 0.45)"}
                strokeDasharray="3 6"
              />
            ))}
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
