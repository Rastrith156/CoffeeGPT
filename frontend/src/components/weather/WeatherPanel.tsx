import { T } from '../../styles/theme';

const WEATHER_DATA = [
  { region: "Minas Gerais, BR", temp: "8°C", risk: "CRITICAL", riskColor: T.red, rainfall: "12mm", humidity: "72%", icon: "❄" },
  { region: "Central Highlands, VN", temp: "26°C", risk: "HIGH", riskColor: T.orange, rainfall: "88mm", humidity: "91%", icon: "🌀" },
  { region: "Huila, CO", temp: "18°C", risk: "MEDIUM", riskColor: T.amber, rainfall: "54mm", humidity: "83%", icon: "🌧" },
  { region: "Yirgacheffe, ET", temp: "21°C", risk: "LOW", riskColor: T.green, rainfall: "31mm", humidity: "68%", icon: "☀" },
];

export const WeatherPanel = () => {
  return (
    <div style={{ padding: 24, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 18, fontWeight: 600, color: T.text0, marginBottom: 20, fontFamily: "'Syne', sans-serif" }}>Global Weather Intelligence</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
        {WEATHER_DATA.map((w, i) => (
          <div key={i} style={{ background: T.bg2, borderRadius: 16, border: `1px solid ${T.border}`, padding: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: T.text0, marginBottom: 4 }}>{w.region}</div>
                <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>Synoptic Forecast</div>
              </div>
              <div style={{ fontSize: 24 }}>{w.icon}</div>
            </div>
            <div style={{ display: "flex", gap: 20, marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 10, color: T.text2, marginBottom: 4, fontFamily: "'DM Mono', monospace" }}>TEMP</div>
                <div style={{ fontSize: 20, color: T.text0, fontWeight: 600, fontFamily: "'DM Mono', monospace" }}>{w.temp}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: T.text2, marginBottom: 4, fontFamily: "'DM Mono', monospace" }}>RAIN</div>
                <div style={{ fontSize: 20, color: T.text0, fontWeight: 600, fontFamily: "'DM Mono', monospace" }}>{w.rainfall}</div>
              </div>
            </div>
            <div style={{ padding: "8px 12px", background: T.bg3, borderRadius: 8, borderLeft: `3px solid ${w.riskColor}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 11, color: T.text1 }}>Agronomic Risk</span>
              <span style={{ fontSize: 11, color: w.riskColor, fontWeight: 600, fontFamily: "'DM Mono', monospace", letterSpacing: "0.05em" }}>{w.risk}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
