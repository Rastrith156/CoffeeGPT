import { useState, useEffect, useRef, useCallback } from "react";
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

// ─────────────────────────────────────────────
// DESIGN TOKENS
// ─────────────────────────────────────────────
const T = {
  bg0: "#080a0d",
  bg1: "#0d1117",
  bg2: "#111820",
  bg3: "#162030",
  bgGlass: "rgba(13,17,23,0.82)",
  border: "rgba(255,255,255,0.06)",
  borderHover: "rgba(255,255,255,0.12)",
  espresso: "#2c1810",
  bronze: "#c8923a",
  bronzeGlow: "rgba(200,146,58,0.18)",
  amber: "#e8a84a",
  amberDim: "rgba(232,168,74,0.12)",
  gold: "#f5c842",
  cyan: "#00d4ff",
  cyanDim: "rgba(0,212,255,0.10)",
  cyanGlow: "rgba(0,212,255,0.20)",
  green: "#22c55e",
  greenDim: "rgba(34,197,94,0.12)",
  red: "#ef4444",
  redDim: "rgba(239,68,68,0.12)",
  orange: "#f97316",
  text0: "#f8fafc",
  text1: "#cbd5e1",
  text2: "#64748b",
  text3: "#334155",
};

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
  @keyframes shimmer { 0%{background-position:-400px 0} 100%{background-position:400px 0} }
  @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
  @keyframes glow { 0%,100%{box-shadow:0 0 8px ${T.cyanGlow}} 50%{box-shadow:0 0 20px ${T.cyanGlow}, 0 0 40px ${T.cyanDim}} }
  @keyframes priceFlash { 0%{background:${T.greenDim}} 100%{background:transparent} }
  .live-dot { animation: pulse 2s ease-in-out infinite; }
  .slide-in { animation: slideIn 0.3s ease forwards; }
  .spinning { animation: spin 1s linear infinite; }
  .glow-ring { animation: glow 3s ease-in-out infinite; }
  input:focus { outline: none; }
  textarea:focus { outline: none; }
  button { cursor: pointer; border: none; background: none; font-family: inherit; }
`;

// ─────────────────────────────────────────────
// MOCK DATA ENGINE
// ─────────────────────────────────────────────
const genPriceSeries = (base: number, days: number, volatility = 0.015) => {
  const data = [];
  let price = base;
  const now = new Date();
  for (let i = -days; i <= 7; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() + i);
    price += price * (Math.random() - 0.48) * volatility;
    const isForecast = i > 0;
    data.push({
      date: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      price: parseFloat(price.toFixed(2)),
      forecast: isForecast ? parseFloat(price.toFixed(2)) : null,
      upper: isForecast ? parseFloat((price * 1.035).toFixed(2)) : null,
      lower: isForecast ? parseFloat((price * 0.965).toFixed(2)) : null,
      type: isForecast ? "forecast" : "historical",
    });
  }
  return data;
};

const ARABICA_BASE = 223.40;
const ROBUSTA_BASE = 4105;

const MOCK_ALERTS = [
  { id: "a1", severity: "critical", region: "Brazil", title: "Frost Risk — Minas Gerais", body: "Severe frost event forecast within 72h. Estimated 180k bags at risk.", time: "2m ago", icon: "❄" },
  { id: "a2", severity: "high", region: "Vietnam", title: "Typhoon Track Update", body: "Typhoon Son-Tinh shifted westward. Central Highlands exposure elevated.", time: "18m ago", icon: "🌀" },
  { id: "a3", severity: "high", region: "Market", title: "Arabica Volatility Spike", body: "30-day IV jumped 4.2 pts. Options market pricing tail risk premium.", time: "34m ago", icon: "⚡" },
  { id: "a4", severity: "medium", region: "Colombia", title: "La Niña Confirmation", body: "ENSO outlook confirms La Niña pattern. Potential yield impact in Huila.", time: "1h ago", icon: "🌧" },
  { id: "a5", severity: "low", region: "Ethiopia", title: "Export Volume Strong", body: "Yirgacheffe exports up 12% YoY. Supply-side pressure moderating.", time: "3h ago", icon: "📦" },
];

const MOCK_SIGNALS = [
  { label: "AI Confidence", value: 87, unit: "%", color: T.cyan, icon: "◈" },
  { label: "Volatility Index", value: 24.6, unit: "pts", color: T.amber, icon: "◉" },
  { label: "Supply Stress", value: 61, unit: "/100", color: T.orange, icon: "▲" },
  { label: "Weather Risk", value: 73, unit: "/100", color: T.red, icon: "◆" },
];

const MARKET_DATA = {
  arabica: { symbol: "KC1", name: "Arabica Futures", price: ARABICA_BASE, change: 3.2, changePct: 1.45, currency: "USc/lb", volume: "28,412", open: 219.90, high: 224.85, low: 218.60 },
  robusta: { symbol: "RC1", name: "Robusta Futures", price: ROBUSTA_BASE, change: -35, changePct: -0.84, currency: "$/MT", volume: "14,270", open: 4140, high: 4155, low: 4085 },
};

const WEATHER_DATA = [
  { region: "Minas Gerais, BR", temp: "8°C", risk: "CRITICAL", riskColor: T.red, rainfall: "12mm", humidity: "72%", icon: "❄" },
  { region: "Central Highlands, VN", temp: "26°C", risk: "HIGH", riskColor: T.orange, rainfall: "88mm", humidity: "91%", icon: "🌀" },
  { region: "Huila, CO", temp: "18°C", risk: "MEDIUM", riskColor: T.amber, rainfall: "54mm", humidity: "83%", icon: "🌧" },
  { region: "Yirgacheffe, ET", temp: "21°C", risk: "LOW", riskColor: T.green, rainfall: "31mm", humidity: "68%", icon: "☀" },
];

const AI_RESPONSES: Record<string, string> = {
  default: `**Market Intelligence Summary**\n\nArabica futures are trading at **223.40 USc/lb**, up **+1.45%** on the session, driven by frost risk escalation in Brazil's Minas Gerais producing region. The AI risk engine assigns a **73/100** weather risk score to current South American conditions.\n\n**Key Intelligence Points:**\n\n→ Robusta showing relative weakness (-0.84%) as Vietnamese supply pipeline remains intact despite typhoon concerns\n\n→ Options market pricing elevated tail risk — 30-day implied volatility at 24.6 pts signals institutional hedging activity\n\n→ La Niña confirmation adds medium-term upside bias to Arabica; Colombian Huila yields may be impacted Q2\n\n**AI Forecast:** 7-day price target range **218–232 USc/lb** with bullish asymmetry given weather risk premium. Confidence: 87%.`,
  frost: `**Frost Risk Intelligence — Minas Gerais**\n\nSatellite thermal data and synoptic modeling indicate a high-confidence frost event is forecast within **72 hours** across key Arabica growing elevations (900–1400m) in Minas Gerais.\n\n**Impact Assessment:**\n\n→ Estimated **180,000–240,000 bags** at production risk depending on temperature trough depth\n\n→ ICE exchange stocks currently at **15-year lows**, amplifying price sensitivity to any supply shock\n\n→ Historical precedent: 2021 frost event drove Arabica +28% in 30 days from comparable setup\n\n**Trading Implications:** Near-term bullish catalyst. Options skew favoring upside calls. Physical premiums likely to firm in Brazil differentials.\n\n*AI Confidence: 91% | Sources: INMET, NOAA, proprietary satellite thermal feed*`,
  forecast: `**7-Day Price Forecast — Arabica (KC)**\n\nProprietary AI ensemble model incorporating:\n• ENSO/La Niña probability weighting\n• Satellite soil moisture indices  \n• Options market implied distributions\n• Macroeconomic demand proxies (USD, EM FX)\n\n**Forecast Output:**\n\n| Day | Price Target | Confidence |\n|-----|-------------|------------|\n| D+1 | 224–227 | 89% |\n| D+3 | 221–230 | 83% |\n| D+7 | 218–235 | 74% |\n\nBullish scenario probability: **62%** — driven by frost catalyst\nBase case: **31%** — weather normalizes, modest correction\nBearish tail: **7%** — USD strengthening offsets supply concerns\n\n*Model updated: real-time | Next refresh: 15min*`,
  risk: `**Supply Chain Risk Report**\n\n**Overall Risk Score: 61/100 — ELEVATED**\n\n**Brazil (Weight: 38% of global Arabica supply)**\n• Production Risk: 73/100 — Frost imminent\n• Logistics Risk: 22/100 — Santos port normal\n• Currency Risk: 45/100 — BRL weakness moderate\n\n**Vietnam (Weight: 41% of Robusta)**\n• Weather Risk: 58/100 — Typhoon track uncertain\n• Export Pipeline: 31/100 — Strong pre-season shipments\n• Quality Risk: 27/100 — Dry processing conditions adequate\n\n**Colombia (Weight: 9% global)**\n• Production Risk: 44/100 — La Niña watch\n• Certifications: 12/100 — FT/Organic supply stable\n\n**AI Recommendation:** Overweight near-month long exposure. Hedge with synthetic puts on 10% of book. Review in 48h post-frost event confirmation.`,
};

const QUICK_PROMPTS = [
  { label: "Frost risk impact", key: "frost" },
  { label: "7-day forecast", key: "forecast" },
  { label: "Supply chain risk", key: "risk" },
  { label: "Market overview", key: "default" },
];

const NAV = [
  { id: "chat", icon: "◈", label: "AI Chat" },
  { id: "markets", icon: "◉", label: "Live Markets" },
  { id: "weather", icon: "◆", label: "Weather Intel" },
  { id: "alerts", icon: "▲", label: "Alerts" },
  { id: "forecast", icon: "⬡", label: "Forecasting" },
];

// ─────────────────────────────────────────────
// PRICE TICKER HOOK
// ─────────────────────────────────────────────
const useLivePrice = (base: number, volatility = 0.0008) => {
  const [price, setPrice] = useState(base);
  const [dir, setDir] = useState<string | null>(null);
  useEffect(() => {
    const iv = setInterval(() => {
      setPrice(p => {
        const next = parseFloat((p + p * (Math.random() - 0.5) * volatility).toFixed(2));
        setDir(next >= p ? "up" : "down");
        return next;
      });
    }, 2200);
    return () => clearInterval(iv);
  }, [base, volatility]);
  return { price, dir };
};

// ─────────────────────────────────────────────
// STREAMING TEXT HOOK
// ─────────────────────────────────────────────
const useStreamText = () => {
  const [streaming, setStreaming] = useState(false);
  const [text, setText] = useState("");
  const abortRef = useRef(false);

  const stream = useCallback(async (fullText: string, onDone?: () => void) => {
    setStreaming(true);
    setText("");
    abortRef.current = false;
    let i = 0;
    const step = () => {
      if (abortRef.current) { setStreaming(false); return; }
      if (i < fullText.length) {
        const chunk = Math.floor(Math.random() * 3) + 1;
        setText(fullText.slice(0, i + chunk));
        i += chunk;
        setTimeout(step, 12 + Math.random() * 18);
      } else {
        setStreaming(false);
        onDone && onDone();
      }
    };
    step();
  }, []);

  const abort = () => { abortRef.current = true; };
  return { streaming, text, stream, abort };
};

// ─────────────────────────────────────────────
// MARKDOWN RENDERER (simple)
// ─────────────────────────────────────────────
const renderMD = (text: string) => {
  const lines = text.split("\\n");
  return lines.map((line, i) => {
    if (line.startsWith("**") && line.endsWith("**") && line.length > 4) {
      return <div key={i} style={{ fontWeight: 600, color: T.text0, marginBottom: 6, marginTop: i > 0 ? 10 : 0, fontFamily: "'Syne', sans-serif", fontSize: 13, letterSpacing: "0.02em" }}>{line.slice(2, -2)}</div>;
    }
    if (line.startsWith("→ ") || line.startsWith("• ")) {
      const content = line.slice(2);
      // bold inline
      const parts = content.split(/\\*\\*(.*?)\\*\\*/g);
      return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 5, color: T.text1, fontSize: 13, lineHeight: 1.6 }}>
        <span style={{ color: T.bronze, flexShrink: 0 }}>{line[0] === "→" ? "→" : "•"}</span>
        <span>{parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: T.amber }}>{p}</strong> : p)}</span>
      </div>;
    }
    if (line.startsWith("| ")) {
      const cells = line.split("|").filter(c => c.trim());
      if (cells[0].trim() === "---" || cells[0].trim().startsWith("---")) return null;
      const isHeader = lines[i + 1] && lines[i + 1].startsWith("|---");
      return <div key={i} style={{ display: "grid", gridTemplateColumns: \`repeat(\${cells.length}, 1fr)\`, gap: 1, marginBottom: 1 }}>
        {cells.map((c, j) => <div key={j} style={{ padding: "5px 8px", background: isHeader ? T.bg3 : T.bg2, fontSize: 12, color: isHeader ? T.bronze : T.text1, fontFamily: isHeader ? "'Syne', sans-serif" : "inherit", fontWeight: isHeader ? 600 : 400 }}>{c.trim()}</div>)}
      </div>;
    }
    if (line === "") return <div key={i} style={{ height: 6 }} />;
    const parts = line.split(/\\*\\*(.*?)\\*\\*/g);
    return <div key={i} style={{ color: T.text1, fontSize: 13, lineHeight: 1.7, marginBottom: 2 }}>
      {parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: T.text0 }}>{p}</strong> : p)}
    </div>;
  }).filter(Boolean);
};

// ─────────────────────────────────────────────
// SUBCOMPONENTS
// ─────────────────────────────────────────────

const GlassCard = ({ children, style = {}, hover = false }: any) => {
  const [hov, setHov] = useState(false);
  return (
    <div
      onMouseEnter={() => hover && setHov(true)}
      onMouseLeave={() => hover && setHov(false)}
      style={{
        background: T.bg2,
        border: \`1px solid \${hov ? T.borderHover : T.border}\`,
        borderRadius: 16,
        backdropFilter: "blur(20px)",
        transition: "border-color 0.2s, transform 0.2s",
        transform: hov && hover ? "translateY(-1px)" : "none",
        ...style,
      }}
    >
      {children}
    </div>
  );
};

const PriceCard = ({ data, livePrice, dir }: any) => {
  const isUp = data.changePct >= 0;
  const [flash, setFlash] = useState(false);
  const prevDir = useRef(dir);
  useEffect(() => {
    if (dir !== prevDir.current) { setFlash(true); setTimeout(() => setFlash(false), 600); prevDir.current = dir; }
  }, [dir]);

  return (
    <GlassCard style={{ flex: 1, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, color: T.text2, letterSpacing: "0.12em", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>{data.symbol} · {data.name}</div>
          <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>Vol {data.volume}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: isUp ? T.greenDim : T.redDim, borderRadius: 8, padding: "4px 10px", border: \`1px solid \${isUp ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}\` }}>
          <span style={{ fontSize: 13, color: isUp ? T.green : T.red, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{isUp ? "▲" : "▼"} {Math.abs(data.changePct).toFixed(2)}%</span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 16, background: flash ? (dir === "up" ? "rgba(34,197,94,0.06)" : "rgba(239,68,68,0.06)") : "transparent", borderRadius: 8, padding: "4px 0", transition: "background 0.4s" }}>
        <span style={{ fontSize: 34, fontWeight: 700, fontFamily: "'DM Mono', monospace", color: T.text0, letterSpacing: "-1px" }}>{livePrice?.toFixed(2)}</span>
        <span style={{ fontSize: 13, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{data.currency}</span>
        <span style={{ fontSize: 13, color: dir === "up" ? T.green : T.red, marginLeft: "auto", fontFamily: "'DM Mono', monospace" }}>{dir === "up" ? "▲" : "▼"}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        {[["Open", data.open], ["High", data.high], ["Low", data.low]].map(([l, v]) => (
          <div key={l as string} style={{ background: T.bg3, borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ fontSize: 10, color: T.text2, marginBottom: 3, fontFamily: "'DM Mono', monospace", letterSpacing: "0.08em" }}>{(l as string).toUpperCase()}</div>
            <div style={{ fontSize: 13, color: T.text1, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{v as number}</div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
};

const SignalBar = ({ label, value, max = 100, color, icon }: any) => (
  <div style={{ marginBottom: 14 }}>
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
      <span style={{ fontSize: 11, color: T.text2, letterSpacing: "0.08em" }}>{icon} {label.toUpperCase()}</span>
      <span style={{ fontSize: 13, color, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{value}</span>
    </div>
    <div style={{ height: 3, background: T.bg3, borderRadius: 4, overflow: "hidden" }}>
      <div style={{ width: \`\${(value / max) * 100}%\`, height: "100%", background: \`linear-gradient(90deg, \${color}88, \${color})\`, borderRadius: 4, transition: "width 1s ease" }} />
    </div>
  </div>
);

const AlertBadge = ({ severity }: { severity: string }) => {
  const map: Record<string, string[]> = { critical: [T.red, T.redDim], high: [T.orange, T.amberDim], medium: [T.amber, T.amberDim], low: [T.text2, T.bg3] };
  const [c, bg] = map[severity] || [T.text2, T.bg3];
  return <span style={{ fontSize: 10, fontFamily: "'DM Mono', monospace", fontWeight: 600, letterSpacing: "0.1em", color: c, background: bg, padding: "2px 7px", borderRadius: 4, border: \`1px solid \${c}33\`, textTransform: "uppercase" }}>{severity}</span>;
};

const LiveDot = ({ color = T.cyan, size = 7 }) => (
  <div className="live-dot" style={{ width: size, height: size, borderRadius: "50%", background: color, boxShadow: \`0 0 6px \${color}\` }} />
);

// ─────────────────────────────────────────────
// PANELS
// ─────────────────────────────────────────────

const ChatPanel = () => {
  const [messages, setMessages] = useState([
    { role: "assistant", content: AI_RESPONSES.default, done: true }
  ]);
  const [input, setInput] = useState("");
  const { streaming, text, stream } = useStreamText();
  const endRef = useRef<HTMLDivElement>(null);
  const [thinking, setThinking] = useState(false);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, text, thinking]);

  const sendMessage = useCallback((userText: string, responseKey = "default") => {
    if (streaming || thinking) return;
    const userMsg = userText.trim();
    if (!userMsg) return;
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: userMsg, done: true }]);
    setThinking(true);
    setTimeout(() => {
      setThinking(false);
      const responseText = AI_RESPONSES[responseKey] || AI_RESPONSES.default;
      setMessages(prev => [...prev, { role: "assistant", content: "", done: false }]);
      stream(responseText, () => {
        setMessages(prev => {
          const msgs = [...prev];
          msgs[msgs.length - 1] = { role: "assistant", content: responseText, done: true };
          return msgs;
        });
      });
    }, 900 + Math.random() * 600);
  }, [streaming, thinking, stream]);

  const handleSubmit = () => {
    if (!input.trim()) return;
    const key = input.toLowerCase().includes("frost") ? "frost" : input.toLowerCase().includes("forecast") ? "forecast" : input.toLowerCase().includes("risk") ? "risk" : "default";
    sendMessage(input, key);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header */}
      <div style={{ padding: "16px 20px", borderBottom: \`1px solid \${T.border}\`, display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <div style={{ width: 32, height: 32, borderRadius: 10, background: \`linear-gradient(135deg, \${T.bronze}, \${T.espresso})\`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>☕</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif", letterSpacing: "0.02em" }}>CoffeeGPT Intelligence</div>
          <div style={{ fontSize: 11, color: T.text2, display: "flex", alignItems: "center", gap: 5 }}><LiveDot size={6} /> <span>AI Active · Streaming</span></div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {thinking && <div style={{ fontSize: 11, color: T.cyan, fontFamily: "'DM Mono', monospace", display: "flex", alignItems: "center", gap: 5 }}>
            <div className="spinning" style={{ width: 12, height: 12, border: \`1.5px solid \${T.cyan}\`, borderTopColor: "transparent", borderRadius: "50%" }} />
            Reasoning...
          </div>}
          {streaming && !thinking && <div style={{ fontSize: 11, color: T.amber, fontFamily: "'DM Mono', monospace", display: "flex", alignItems: "center", gap: 5 }}>
            <div className="live-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: T.amber }} />
            Streaming
          </div>}
        </div>
      </div>

      {/* Quick prompts */}
      <div style={{ padding: "12px 20px", borderBottom: \`1px solid \${T.border}\`, display: "flex", gap: 8, flexWrap: "wrap", flexShrink: 0 }}>
        {QUICK_PROMPTS.map(q => (
          <button key={q.key} onClick={() => sendMessage(q.label, q.key)} disabled={streaming || thinking}
            style={{ fontSize: 11, padding: "5px 12px", borderRadius: 20, border: \`1px solid \${T.border}\`, background: T.bg3, color: T.text1, cursor: "pointer", transition: "all 0.2s", fontFamily: "'Inter', sans-serif", opacity: streaming || thinking ? 0.5 : 1 }}>
            {q.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 16 }}>
        {messages.map((msg, idx) => {
          const isLast = idx === messages.length - 1;
          const displayText = (isLast && !msg.done && streaming) ? text : msg.content;
          return (
            <div key={idx} className="slide-in" style={{ display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 6 }}>
              {msg.role === "assistant" && (
                <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.1em", display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 16, height: 16, borderRadius: 5, background: \`linear-gradient(135deg, \${T.bronze}, \${T.espresso})\`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8 }}>☕</div>
                  COFFEEGPT · AI INTELLIGENCE
                </div>
              )}
              <div style={{
                maxWidth: "90%", padding: "14px 18px", borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "4px 16px 16px 16px",
                background: msg.role === "user" ? \`linear-gradient(135deg, \${T.bronze}22, \${T.amberDim})\` : T.bg3,
                border: \`1px solid \${msg.role === "user" ? T.bronze + "33" : T.border}\`,
                position: "relative"
              }}>
                {msg.role === "assistant" ? renderMD(displayText) : <span style={{ fontSize: 13, color: T.text0, lineHeight: 1.6 }}>{msg.content}</span>}
                {isLast && streaming && msg.role === "assistant" && (
                  <span className="blink" style={{ display: "inline-block", width: 2, height: 14, background: T.cyan, marginLeft: 2, verticalAlign: "text-bottom", animation: "blink 1s step-end infinite" }} />
                )}
              </div>
            </div>
          );
        })}
        {thinking && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", background: T.bg3, borderRadius: "4px 16px 16px 16px", border: \`1px solid \${T.border}\`, width: "fit-content" }}>
            <div className="live-dot" style={{ width: 6, height: 6, background: T.cyan, borderRadius: "50%", animationDelay: "0s" }} />
            <div className="live-dot" style={{ width: 6, height: 6, background: T.cyan, borderRadius: "50%", animationDelay: "0.3s" }} />
            <div className="live-dot" style={{ width: 6, height: 6, background: T.cyan, borderRadius: "50%", animationDelay: "0.6s" }} />
            <span style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace", marginLeft: 4 }}>Analyzing market intelligence...</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "14px 16px", borderTop: \`1px solid \${T.border}\`, flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", background: T.bg3, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: "4px 4px 4px 16px", transition: "border-color 0.2s" }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSubmit()}
            placeholder="Ask about prices, forecasts, weather, supply chain..."
            disabled={streaming || thinking}
            style={{ flex: 1, background: "none", border: "none", color: T.text0, fontSize: 13, fontFamily: "'Inter', sans-serif", padding: "8px 0", caretColor: T.cyan }}
          />
          <button onClick={handleSubmit} disabled={!input.trim() || streaming || thinking}
            style={{ padding: "8px 16px", borderRadius: 10, background: input.trim() && !streaming && !thinking ? \`linear-gradient(135deg, \${T.bronze}, \${T.amber})\` : T.bg2, color: input.trim() && !streaming && !thinking ? "#000" : T.text2, fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif", transition: "all 0.2s", cursor: input.trim() && !streaming && !thinking ? "pointer" : "not-allowed", whiteSpace: "nowrap" }}>
            Send ↑
          </button>
        </div>
      </div>
    </div>
  );
};

const MarketsPanel = ({ arabicaPrice, arabicaDir, robustaPrice, robustaDir }: any) => {
  const [arabicaSeries] = useState(() => genPriceSeries(ARABICA_BASE, 21));
  const [robustaSeries] = useState(() => genPriceSeries(ROBUSTA_BASE, 21, 0.012));

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
      <div style={{ background: T.bg1, border: \`1px solid \${T.border}\`, borderRadius: 10, padding: "10px 14px", fontSize: 12 }}>
        <div style={{ color: T.text2, marginBottom: 4, fontFamily: "'DM Mono', monospace" }}>{label}</div>
        <div style={{ color: d.type === "forecast" ? T.amber : T.green, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{payload[0].value?.toFixed(2)}</div>
        {d.lower && <div style={{ color: T.text2, fontSize: 11 }}>Band: {d.lower}–{d.upper}</div>}
      </div>
    );
  };

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Price cards */}
      <div style={{ display: "flex", gap: 16 }}>
        <PriceCard data={MARKET_DATA.arabica} livePrice={arabicaPrice} dir={arabicaDir} />
        <PriceCard data={MARKET_DATA.robusta} livePrice={robustaPrice} dir={robustaDir} />
      </div>

      {/* Arabica chart */}
      <GlassCard style={{ padding: "20px 24px 10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif", marginBottom: 3 }}>Arabica — Historical & AI Forecast</div>
            <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>KC1 · USc/lb · 21D + 7D Forecast</div>
          </div>
          <div style={{ display: "flex", gap: 16, fontSize: 11 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 5, color: T.green }}><div style={{ width: 20, height: 2, background: T.green }} /> Historical</span>
            <span style={{ display: "flex", alignItems: "center", gap: 5, color: T.amber }}><div style={{ width: 20, height: 2, background: T.amber, borderTop: "2px dashed" }} /> Forecast</span>
          </div>
        </div>
        <div style={{ height: 200 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={arabicaSeries} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
              <defs>
                <linearGradient id="arabicaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.green} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={T.green} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.amber} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={T.amber} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={T.border} vertical={false} />
              <XAxis dataKey="date" stroke={T.text3} fontSize={10} tickLine={false} axisLine={false} interval={3} tick={{ fontFamily: "'DM Mono', monospace" }} />
              <YAxis stroke={T.text3} fontSize={10} tickLine={false} axisLine={false} domain={["auto", "auto"]} tick={{ fontFamily: "'DM Mono', monospace" }} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine x={arabicaSeries[21]?.date} stroke={T.border} strokeDasharray="4 4" />
              <Area type="monotone" dataKey="price" stroke={T.green} strokeWidth={2} fill="url(#arabicaGrad)" dot={false} />
              <Area type="monotone" dataKey="forecast" stroke={T.amber} strokeWidth={2} strokeDasharray="6 3" fill="url(#forecastGrad)" dot={false} connectNulls={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>

      {/* Signals */}
      <GlassCard style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 12, fontWeight: 600, fontFamily: "'Syne', sans-serif", letterSpacing: "0.05em", color: T.text2, marginBottom: 16, textTransform: "uppercase" }}>AI Intelligence Signals</div>
        {MOCK_SIGNALS.map(s => <SignalBar key={s.label} {...s} />)}
      </GlassCard>
    </div>
  );
};

const WeatherPanel = () => (
  <div style={{ height: "100%", overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 16 }}>
    <GlassCard style={{ padding: "18px 22px" }}>
      <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif", marginBottom: 4 }}>Global Coffee Region Intelligence</div>
      <div style={{ fontSize: 11, color: T.text2 }}>Satellite-enhanced agricultural weather monitoring</div>
    </GlassCard>
    {WEATHER_DATA.map((w, i) => (
      <GlassCard key={i} hover style={{ padding: "18px 22px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{w.region}</div>
            <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{w.temp} · {w.rainfall} rainfall</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            <span style={{ fontSize: 20 }}>{w.icon}</span>
            <span style={{ fontSize: 10, fontFamily: "'DM Mono', monospace", fontWeight: 700, color: w.riskColor, letterSpacing: "0.1em" }}>{w.risk}</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {[["Temp", w.temp], ["Rainfall", w.rainfall], ["Humidity", w.humidity]].map(([l, v]) => (
            <div key={l as string} style={{ flex: 1, background: T.bg3, borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 10, color: T.text2, marginBottom: 3, fontFamily: "'DM Mono', monospace" }}>{l as string}</div>
              <div style={{ fontSize: 13, color: T.text1, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{v as string}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, height: 3, background: T.bg3, borderRadius: 4, overflow: "hidden" }}>
          <div style={{ width: w.risk === "CRITICAL" ? "95%" : w.risk === "HIGH" ? "72%" : w.risk === "MEDIUM" ? "48%" : "22%", height: "100%", background: w.riskColor, borderRadius: 4, transition: "width 1s" }} />
        </div>
      </GlassCard>
    ))}
  </div>
);

const AlertsPanel = () => {
  const [alerts, setAlerts] = useState(MOCK_ALERTS);
  const [newAlert, setNewAlert] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => {
      setAlerts(prev => [{ id: "live_" + Date.now(), severity: "critical", region: "Brazil", title: "LIVE: Frost Confirmed — Temperatura Negativa", body: "Ground-truth stations reporting -2°C. Market impact imminent. Review exposure.", time: "just now", icon: "🚨" }, ...prev]);
      setNewAlert(true);
      setTimeout(() => setNewAlert(false), 3000);
    }, 8000);
    return () => clearTimeout(t);
  }, []);

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif" }}>Autonomous Alert Center</div>
          <div style={{ fontSize: 11, color: T.text2 }}>AI-prioritized intelligence signals</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {newAlert && <div style={{ fontSize: 11, color: T.red, fontFamily: "'DM Mono', monospace", animation: "pulse 1s infinite" }}>● NEW</div>}
          <div style={{ background: T.redDim, border: \`1px solid \${T.red}44\`, borderRadius: 20, padding: "3px 12px", fontSize: 12, color: T.red, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{alerts.length}</div>
        </div>
      </div>
      {alerts.map((a, i) => (
        <GlassCard key={a.id} hover style={{ padding: "16px 18px", borderLeft: \`3px solid \${a.severity === "critical" ? T.red : a.severity === "high" ? T.orange : a.severity === "medium" ? T.amber : T.text2}\`, animation: i === 0 && newAlert ? "slideIn 0.4s ease" : "none" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 16 }}>{a.icon}</span>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 2 }}>{a.title}</div>
                <div style={{ display: "flex", gap: 8 }}><AlertBadge severity={a.severity} /><span style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{a.region}</span></div>
              </div>
            </div>
            <span style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", whiteSpace: "nowrap", marginLeft: 10 }}>{a.time}</span>
          </div>
          <div style={{ fontSize: 12, color: T.text1, lineHeight: 1.6 }}>{a.body}</div>
        </GlassCard>
      ))}
    </div>
  );
};

const ForecastPanel = ({ arabicaSeries }: any) => {
  const series = arabicaSeries || genPriceSeries(ARABICA_BASE, 14);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
      <div style={{ background: T.bg1, border: \`1px solid \${T.border}\`, borderRadius: 10, padding: "10px 14px", fontSize: 12 }}>
        <div style={{ color: T.text2, marginBottom: 4, fontFamily: "'DM Mono', monospace" }}>{label}</div>
        <div style={{ color: d.type === "forecast" ? T.amber : T.green, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{payload[0].value?.toFixed(2)} USc/lb</div>
        {d.lower && <div style={{ color: T.text2, fontSize: 11, marginTop: 3 }}>Range: {d.lower} – {d.upper}</div>}
        <div style={{ fontSize: 10, color: T.text2, marginTop: 3 }}>{d.type === "forecast" ? "AI Projection" : "Historical"}</div>
      </div>
    );
  };

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 20 }}>
      <GlassCard style={{ padding: "20px 24px 14px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "'Syne', sans-serif", marginBottom: 4 }}>Arabica · 7-Day AI Forecast</div>
            <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>Ensemble model · CI 95%</div>
          </div>
          <div style={{ background: T.cyanDim, border: \`1px solid \${T.cyan}33\`, borderRadius: 8, padding: "6px 12px", textAlign: "center" }}>
            <div style={{ fontSize: 10, color: T.cyan, fontFamily: "'DM Mono', monospace", marginBottom: 2 }}>AI CONFIDENCE</div>
            <div style={{ fontSize: 22, fontWeight: 700, fontFamily: "'DM Mono', monospace", color: T.cyan }}>87%</div>
          </div>
        </div>
        <div style={{ height: 240 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
              <defs>
                <linearGradient id="histGrad2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.green} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={T.green} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="foreGrad2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.amber} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={T.amber} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={T.border} vertical={false} />
              <XAxis dataKey="date" stroke={T.text3} fontSize={10} tickLine={false} axisLine={false} interval={2} tick={{ fontFamily: "'DM Mono', monospace" }} />
              <YAxis stroke={T.text3} fontSize={10} tickLine={false} axisLine={false} domain={["auto", "auto"]} tick={{ fontFamily: "'DM Mono', monospace" }} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine x={series[14]?.date} stroke={T.amber + "66"} strokeDasharray="5 5" label={{ value: "FORECAST", fill: T.amber, fontSize: 9, fontFamily: "'DM Mono', monospace" }} />
              <Area type="monotone" dataKey="price" stroke={T.green} strokeWidth={2.5} fill="url(#histGrad2)" dot={false} />
              <Area type="monotone" dataKey="forecast" stroke={T.amber} strokeWidth={2} strokeDasharray="6 3" fill="url(#foreGrad2)" dot={false} connectNulls={false} />
              <Area type="monotone" dataKey="upper" stroke="transparent" fill={T.amber} fillOpacity={0.06} dot={false} connectNulls={false} />
              <Area type="monotone" dataKey="lower" stroke="transparent" fill={T.bg0} fillOpacity={1} dot={false} connectNulls={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </GlassCard>

      {/* Scenario breakdown */}
      <GlassCard style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 12, fontWeight: 600, fontFamily: "'Syne', sans-serif", letterSpacing: "0.05em", color: T.text2, marginBottom: 16, textTransform: "uppercase" }}>Scenario Probability Distribution</div>
        {[
          { label: "Bullish · Frost Catalyst", pct: 62, color: T.green, range: "228–242 USc/lb" },
          { label: "Base · Weather Normalizes", pct: 31, color: T.amber, range: "215–228 USc/lb" },
          { label: "Bearish · USD Strength", pct: 7, color: T.red, range: "205–215 USc/lb" },
        ].map(s => (
          <div key={s.label} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontSize: 12, color: T.text1 }}>{s.label}</span>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{s.range}</span>
                <span style={{ fontSize: 13, color: s.color, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{s.pct}%</span>
              </div>
            </div>
            <div style={{ height: 4, background: T.bg3, borderRadius: 4 }}>
              <div style={{ width: \`\${s.pct}%\`, height: "100%", background: \`linear-gradient(90deg, \${s.color}66, \${s.color})\`, borderRadius: 4 }} />
            </div>
          </div>
        ))}
      </GlassCard>

      {/* Key factors */}
      <GlassCard style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 12, fontWeight: 600, fontFamily: "'Syne', sans-serif", letterSpacing: "0.05em", color: T.text2, marginBottom: 14, textTransform: "uppercase" }}>Model Inputs · Weight</div>
        {[
          { label: "Weather / Frost Risk", weight: 0.34, color: T.red },
          { label: "ENSO / La Niña", weight: 0.22, color: T.orange },
          { label: "Options IV Surface", weight: 0.18, color: T.amber },
          { label: "USD / EM FX", weight: 0.14, color: T.cyan },
          { label: "Demand Proxies", weight: 0.12, color: T.green },
        ].map(f => (
          <div key={f.label} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: f.color, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: T.text1, flex: 1 }}>{f.label}</span>
            <div style={{ width: 80, height: 3, background: T.bg3, borderRadius: 4 }}>
              <div style={{ width: \`\${f.weight * 100}%\`, height: "100%", background: f.color, borderRadius: 4 }} />
            </div>
            <span style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace", minWidth: 34, textAlign: "right" }}>{(f.weight * 100).toFixed(0)}%</span>
          </div>
        ))}
      </GlassCard>
    </div>
  );
};

// ─────────────────────────────────────────────
// LIVE TICKER
// ─────────────────────────────────────────────
const TICKER_ITEMS = [
  { label: "KC1 ARABICA", price: 223.40, unit: "USc/lb", change: +1.45 },
  { label: "RC1 ROBUSTA", price: 4105, unit: "$/MT", change: -0.84 },
  { label: "BRL/USD", price: 0.1892, unit: "", change: -0.31 },
  { label: "USD INDEX", price: 104.72, unit: "", change: +0.12 },
  { label: "COCOA", price: 9841, unit: "$/MT", change: +2.10 },
  { label: "SUGAR #11", price: 22.14, unit: "USc/lb", change: -0.56 },
  { label: "WTI CRUDE", price: 76.88, unit: "$/bbl", change: +0.73 },
  { label: "VIX", price: 14.22, unit: "", change: -3.10 },
];

const LiveTicker = () => {
  const [offset, setOffset] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const iv = setInterval(() => setOffset(o => o - 1), 30);
    return () => clearInterval(iv);
  }, []);
  const itemWidth = 200;
  const total = TICKER_ITEMS.length * itemWidth;
  const mod = ((offset % total) - total) % total;

  return (
    <div style={{ overflow: "hidden", height: 32, background: T.bg1, borderBottom: \`1px solid \${T.border}\`, display: "flex", alignItems: "center" }} ref={containerRef}>
      <div style={{ display: "flex", transform: \`translateX(\${mod}px)\`, whiteSpace: "nowrap", willChange: "transform" }}>
        {[...TICKER_ITEMS, ...TICKER_ITEMS, ...TICKER_ITEMS].map((t, i) => (
          <div key={i} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "0 20px", width: itemWidth, borderRight: \`1px solid \${T.border}\` }}>
            <span style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.06em" }}>{t.label}</span>
            <span style={{ fontSize: 11, color: T.text0, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{t.price}</span>
            <span style={{ fontSize: 10, color: t.change >= 0 ? T.green : T.red, fontFamily: "'DM Mono', monospace" }}>{t.change >= 0 ? "▲" : "▼"}{Math.abs(t.change).toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────
// MAIN APP
// ─────────────────────────────────────────────
export default function App() {
  const [activeNav, setActiveNav] = useState("chat");
  const [time, setTime] = useState(new Date());
  const arabica = useLivePrice(ARABICA_BASE, 0.0006);
  const robusta = useLivePrice(ROBUSTA_BASE, 0.0005);
  const [arabicaSeries] = useState(() => genPriceSeries(ARABICA_BASE, 14));

  useEffect(() => {
    const iv = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(iv);
  }, []);

  const panelContent: Record<string, React.ReactNode> = {
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
        <header style={{ height: 52, background: T.bg1, borderBottom: \`1px solid \${T.border}\`, display: "flex", alignItems: "center", padding: "0 20px", gap: 16, flexShrink: 0, zIndex: 20 }}>
          {/* Logo */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginRight: 8 }}>
            <div style={{ width: 32, height: 32, borderRadius: 10, background: \`linear-gradient(135deg, \${T.bronze}, #8b4513)\`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, boxShadow: \`0 0 12px \${T.bronzeGlow}\` }}>☕</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 800, fontFamily: "'Syne', sans-serif", letterSpacing: "0.02em", lineHeight: 1 }}>CoffeeGPT</div>
              <div style={{ fontSize: 9, color: T.bronze, fontFamily: "'DM Mono', monospace", letterSpacing: "0.15em", lineHeight: 1 }}>INTELLIGENCE TERMINAL</div>
            </div>
          </div>

          {/* Nav */}
          <nav style={{ display: "flex", gap: 4 }}>
            {NAV.map(n => (
              <button key={n.id} onClick={() => setActiveNav(n.id)}
                style={{ padding: "5px 14px", borderRadius: 8, border: \`1px solid \${activeNav === n.id ? T.bronze + "44" : "transparent"}\`, background: activeNav === n.id ? T.bronzeGlow : "transparent", color: activeNav === n.id ? T.amber : T.text2, fontSize: 12, fontFamily: "'Inter', sans-serif", fontWeight: activeNav === n.id ? 600 : 400, transition: "all 0.2s", display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10 }}>{n.icon}</span> {n.label}
              </button>
            ))}
          </nav>

          {/* Right status */}
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: T.bg3, borderRadius: 8, padding: "4px 12px", border: \`1px solid \${T.border}\` }}>
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

        {/* MAIN CONTENT — three-column layout for chat, two-column for others */}
        <main style={{ flex: 1, overflow: "hidden", display: "grid", gridTemplateColumns: activeNav === "chat" ? "1fr 380px" : "1fr 300px", transition: "grid-template-columns 0.3s ease" }}>

          {/* CENTER PANEL */}
          <div style={{ overflow: "hidden", borderRight: \`1px solid \${T.border}\` }}>
            {panelContent[activeNav]}
          </div>

          {/* RIGHT SIDE PANEL — always visible intelligence sidebar */}
          <div style={{ background: T.bg1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 0 }}>
            {/* Market mini-ticker */}
            <div style={{ padding: "16px 16px 12px", borderBottom: \`1px solid \${T.border}\` }}>
              <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.12em", marginBottom: 10 }}>LIVE FUTURES</div>
              {[
                { name: "Arabica", price: arabica.price, dir: arabica.dir, unit: "USc/lb", chg: MARKET_DATA.arabica.changePct },
                { name: "Robusta", price: robusta.price, dir: robusta.dir, unit: "$/MT", chg: MARKET_DATA.robusta.changePct },
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

            {/* AI Signals */}
            <div style={{ padding: "14px 16px", borderBottom: \`1px solid \${T.border}\` }}>
              <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.12em", marginBottom: 10 }}>AI SIGNALS</div>
              {MOCK_SIGNALS.map(s => (
                <div key={s.label} style={{ marginBottom: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontSize: 11, color: T.text1 }}>{s.label}</span>
                    <span style={{ fontSize: 12, color: s.color, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{s.value}{s.unit}</span>
                  </div>
                  <div style={{ height: 2, background: T.bg3, borderRadius: 2 }}>
                    <div style={{ width: \`\${(s.value / 100) * 100}%\`, height: "100%", background: s.color, borderRadius: 2 }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Mini alerts */}
            <div style={{ padding: "14px 16px", borderBottom: \`1px solid \${T.border}\` }}>
              <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.12em", marginBottom: 10 }}>RECENT ALERTS</div>
              {MOCK_ALERTS.slice(0, 3).map(a => (
                <div key={a.id} style={{ marginBottom: 8, padding: "8px 10px", background: T.bg2, borderRadius: 8, borderLeft: \`2px solid \${a.severity === "critical" ? T.red : a.severity === "high" ? T.orange : T.amber}\` }}>
                  <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 2, color: T.text0 }}>{a.title}</div>
                  <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{a.region} · {a.time}</div>
                </div>
              ))}
            </div>

            {/* Weather snapshot */}
            <div style={{ padding: "14px 16px" }}>
              <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.12em", marginBottom: 10 }}>WEATHER REGIONS</div>
              {WEATHER_DATA.map((w, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 7, padding: "6px 10px", background: T.bg2, borderRadius: 8 }}>
                  <div>
                    <div style={{ fontSize: 11, color: T.text1, marginBottom: 1 }}>{w.region.split(",")[0]}</div>
                    <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace" }}>{w.temp}</div>
                  </div>
                  <span style={{ fontSize: 10, fontFamily: "'DM Mono', monospace", fontWeight: 700, color: w.riskColor, letterSpacing: "0.08em" }}>{w.risk}</span>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
