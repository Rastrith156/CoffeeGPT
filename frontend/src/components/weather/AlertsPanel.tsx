import { T } from '../../styles/theme';
import { AlertBadge } from '../shared/AlertBadge';

export const MOCK_ALERTS = [
  { id: "a1", severity: "critical", region: "Brazil", title: "Frost Risk — Minas Gerais", body: "Severe frost event forecast within 72h. Estimated 180k bags at risk.", time: "2m ago", icon: "❄" },
  { id: "a2", severity: "high", region: "Vietnam", title: "Typhoon Track Update", body: "Typhoon Son-Tinh shifted westward. Central Highlands exposure elevated.", time: "18m ago", icon: "🌀" },
  { id: "a3", severity: "high", region: "Market", title: "Arabica Volatility Spike", body: "30-day IV jumped 4.2 pts. Options market pricing tail risk premium.", time: "34m ago", icon: "⚡" },
  { id: "a4", severity: "medium", region: "Colombia", title: "La Niña Confirmation", body: "ENSO outlook confirms La Niña pattern. Potential yield impact in Huila.", time: "1h ago", icon: "🌧" },
  { id: "a5", severity: "low", region: "Ethiopia", title: "Export Volume Strong", body: "Yirgacheffe exports up 12% YoY. Supply-side pressure moderating.", time: "3h ago", icon: "📦" },
];

export const AlertsPanel = () => {
  return (
    <div style={{ padding: 24, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 18, fontWeight: 600, color: T.text0, marginBottom: 20, fontFamily: "'Syne', sans-serif" }}>Real-time Risk Alerts</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {MOCK_ALERTS.map(a => (
          <div key={a.id} style={{ background: T.bg2, borderRadius: 12, border: `1px solid ${T.border}`, padding: 20, display: "flex", gap: 16 }}>
            <div style={{ fontSize: 24 }}>{a.icon}</div>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                <div style={{ fontSize: 15, fontWeight: 600, color: T.text0 }}>{a.title}</div>
                <AlertBadge severity={a.severity} />
              </div>
              <div style={{ fontSize: 13, color: T.text1, lineHeight: 1.6, marginBottom: 10 }}>{a.body}</div>
              <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{a.region} · {a.time}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
