import { useState, useEffect, ReactNode } from "react";
import { T } from "./styles/theme";
import { LiveDot } from "./components/shared/LiveDot";
import { LiveTicker } from "./components/market/LiveTicker";
import { ChatPanel } from "./components/chat/ChatPanel";
import { MarketsPanel } from "./components/market/MarketsPanel";
import { WeatherPanel } from "./components/weather/WeatherPanel";
import { AlertsPanel } from "./components/weather/AlertsPanel";
import { ForecastPanel } from "./components/weather/ForecastPanel";
import { useSharedTick } from "./hooks/useSharedTick";
import { useLivePrice } from "./hooks/useLivePrice";
import { genPriceSeries } from "./utils/mockData";

const css = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Syne:wght@400;600;700;800&family=Inter:wght@300;400;500;600&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: ${T.bg0}; color: ${T.text0}; font-family: 'Inter', sans-serif; overflow: hidden; }
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: ${T.border}; border-radius: 2px; }
  .mono { font-family: 'DM Mono', monospace; }
  .syne { font-family: 'Syne', sans-serif; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  @keyframes slideIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
  @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
  @keyframes glow { 0%,100%{box-shadow:0 0 8px ${T.cyanGlow}} 50%{box-shadow:0 0 20px ${T.cyanGlow}, 0 0 40px ${T.cyanDim}} }
  .live-dot { animation: pulse 2s ease-in-out infinite; }
  .slide-in { animation: slideIn 0.3s ease forwards; }
  .spinning { animation: spin 1s linear infinite; }
  .glow-ring { animation: glow 3s ease-in-out infinite; }
  input:focus, textarea:focus { outline: none; }
  button { cursor: pointer; border: none; background: none; font-family: inherit; }
  
  @media (max-width: 768px) {
    .app-main { grid-template-columns: 1fr !important; }
    .right-panel { display: none !important; }
    .app-header { flex-wrap: wrap; height: auto !important; padding: 10px !important; }
    .nav-buttons { overflow-x: auto; padding-bottom: 4px; width: 100%; }
    .status-right { display: none !important; }
  }
`;

const NAV = [
  { id: "chat", icon: "◈", label: "AI Chat" },
  { id: "markets", icon: "◉", label: "Live Markets" },
  { id: "weather", icon: "◆", label: "Weather Intel" },
  { id: "alerts", icon: "▲", label: "Alerts" },
  { id: "forecast", icon: "⬡", label: "Forecasting" },
];

export default function App() {
  const [activeNav, setActiveNav] = useState("chat");
  const [time, setTime] = useState(new Date());
  
  const arabica = useLivePrice(223.40, 0.0006);
  const robusta = useLivePrice(4105, 0.0005);
  const tick = useSharedTick(1);
  const [arabicaSeries] = useState(() => genPriceSeries(223.40, 14));

  useEffect(() => {
    if (tick > 0) setTime(new Date());
  }, [tick]);

  const panelContent: Record<string, ReactNode> = {
    chat: <ChatPanel />,
    markets: <MarketsPanel arabicaPrice={arabica.price} arabicaDir={arabica.dir} robustaPrice={robusta.price} robustaDir={robusta.dir} />,
    weather: <WeatherPanel />,
    alerts: <AlertsPanel />,
    forecast: <ForecastPanel arabicaSeries={arabicaSeries} />,
  };

  return (
    <>
      <style>{css}</style>
      <div style={{ height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        
        {/* HEADER */}
        <header className="app-header" style={{ height: 52, background: T.bg1, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", padding: "0 20px", gap: 16, flexShrink: 0, zIndex: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginRight: 8 }}>
            <div style={{ width: 32, height: 32, borderRadius: 10, background: `linear-gradient(135deg, ${T.bronze}, #8b4513)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, boxShadow: `0 0 12px ${T.bronzeGlow}` }}>☕</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 800, fontFamily: "'Syne', sans-serif", letterSpacing: "0.02em", lineHeight: 1 }}>CoffeeGPT</div>
              <div style={{ fontSize: 9, color: T.bronze, fontFamily: "'DM Mono', monospace", letterSpacing: "0.15em", lineHeight: 1 }}>INTELLIGENCE TERMINAL</div>
            </div>
          </div>

          <nav className="nav-buttons" style={{ display: "flex", gap: 4 }}>
            {NAV.map(n => (
              <button key={n.id} onClick={() => setActiveNav(n.id)}
                style={{ padding: "5px 14px", borderRadius: 8, border: `1px solid ${activeNav === n.id ? T.bronze + "44" : "transparent"}`, background: activeNav === n.id ? T.bronzeGlow : "transparent", color: activeNav === n.id ? T.amber : T.text2, fontSize: 12, fontFamily: "'Inter', sans-serif", fontWeight: activeNav === n.id ? 600 : 400, transition: "all 0.2s", display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10 }}>{n.icon}</span> {n.label}
              </button>
            ))}
          </nav>

          <div className="status-right" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: T.bg3, borderRadius: 8, padding: "4px 12px", border: `1px solid ${T.border}` }}>
              <LiveDot color={T.green} size={6} />
              <span style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>LIVE</span>
              <span style={{ fontSize: 11, color: T.green, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{arabica.price.toFixed(2)}</span>
              <span style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace" }}>USc/lb</span>
            </div>
            <div style={{ fontSize: 12, color: T.text2, fontFamily: "'DM Mono', monospace" }}>
              {time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })} UTC
            </div>
            <div className="glow-ring" style={{ width: 8, height: 8, borderRadius: "50%", background: T.cyan }} />
          </div>
        </header>

        {/* TICKER */}
        <LiveTicker />

        {/* MAIN CONTENT */}
        <main className="app-main" style={{ flex: 1, overflow: "hidden", display: "grid", gridTemplateColumns: activeNav === "chat" ? "1fr 380px" : "1fr", transition: "grid-template-columns 0.3s ease" }}>
          
          <div style={{ overflow: "hidden", borderRight: `1px solid ${T.border}` }}>
            {panelContent[activeNav]}
          </div>
          
          {activeNav === "chat" && (
            <div className="right-panel" style={{ background: T.bg1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 0 }}>
              <div style={{ padding: "16px 16px 12px", borderBottom: `1px solid ${T.border}` }}>
                <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.12em", marginBottom: 10 }}>LIVE FUTURES</div>
                {[
                  { name: "Arabica", price: arabica.price, dir: arabica.dir, unit: "USc/lb", chg: 1.45 },
                  { name: "Robusta", price: robusta.price, dir: robusta.dir, unit: "$/MT", chg: -0.84 },
                ].map(m => (
                  <div key={m.name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, padding: "8px 10px", background: T.bg2, borderRadius: 8 }}>
                    <span style={{ fontSize: 11, color: T.text1 }}>{m.name}</span>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 13, fontFamily: "'DM Mono', monospace", fontWeight: 600, color: T.text0 }}>{m.price.toFixed(2)}</div>
                      <div style={{ fontSize: 10, color: m.chg >= 0 ? T.green : T.red, fontFamily: "'DM Mono', monospace" }}>{m.chg >= 0 ? "▲" : "▼"} {Math.abs(m.chg).toFixed(2)}%</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </>
  );
}
