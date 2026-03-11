import Dashboard from "../components/Dashboard";

export default function Page() {
  return (
    <div className="container">
      <div className="topbar">
        <div>
          <div className="title">Цифровой двойник: электродвигатель</div>
          <div className="subtitle">Мониторинг (real‑time) + предиктивное обслуживание (MVP)</div>
        </div>
        <div className="pill">
          <span style={{ opacity: 0.9 }}>API:</span>
          <code style={{ fontSize: 12, opacity: 0.9 }}>{process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"}</code>
        </div>
      </div>
      <Dashboard />
    </div>
  );
}

