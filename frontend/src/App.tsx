import { useState, useEffect, useRef, useCallback } from "react";
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, BarChart, Bar } from "recharts";

// ─── THEME ────────────────────────────────────────────────────────────────────
const T = {
  bg0: "#05080b",
  bg1: "#0a0f14",
  bg2: "#0f1720",
  bg3: "#141f2c",
  bg4: "#192535",
  border: "rgba(255,200,80,0.08)",
  borderHover: "rgba(255,200,80,0.18)",
  saffron: "#FF9933",
  saffronDim: "rgba(255,153,51,0.12)",
  saffronGlow: "rgba(255,153,51,0.22)",
  gold: "#F0C040",
  goldDim: "rgba(240,192,64,0.14)",
  green: "#138808",
  greenBright: "#22c55e",
  greenDim: "rgba(19,136,8,0.15)",
  navy: "#000080",
  cream: "#FFF8E7",
  red: "#ef4444",
  redDim: "rgba(239,68,68,0.12)",
  cyan: "#38bdf8",
  cyanDim: "rgba(56,189,248,0.10)",
  text0: "#fef9f0",
  text1: "#d4c9b0",
  text2: "#8a7d65",
  text3: "#4a4030",
  mono: "'JetBrains Mono', 'Courier New', monospace",
  sans: "'Plus Jakarta Sans', 'Segoe UI', sans-serif",
  display: "'Playfair Display', Georgia, serif",
};

// ─── INDIAN COFFEE DATA ────────────────────────────────────────────────────────
const TICKER_ITEMS = [
  { label: "ARABICA", price: "₹430.50", raw: 430.50, change: 1.82, unit: "₹/kg" },
  { label: "ROBUSTA", price: "₹310.75", raw: 310.75, change: -0.94, unit: "₹/kg" },
  { label: "INR/USD", price: "83.42", raw: 83.42, change: 0.12, unit: "" },
  { label: "COORG_TEMP", price: "18°C", raw: 18, change: -2.1, unit: "" },
  { label: "CHIKMAGALUR", price: "22°C", raw: 22, change: 1.3, unit: "" },
  { label: "BRICS_INV", price: "142k", raw: 142, change: -0.8, unit: "bags" },
  { label: "MONSOON", price: "68%", raw: 68, change: 4.2, unit: "prob." },
  { label: "PLANTATION_IDX", price: "2,841", raw: 2841, change: 0.56, unit: "pts" },
];

const INDIAN_REGIONS = [
  { name: "Coorg, Karnataka", arabica: 430.5, robusta: 315.2, area: "1.2L ha", output: "53,000 MT", temp: "18°C", rain: "2,200mm", status: "optimal" },
  { name: "Chikmagalur, Karnataka", arabica: 428.0, robusta: 312.5, area: "0.9L ha", output: "38,000 MT", temp: "22°C", rain: "1,900mm", status: "good" },
  { name: "Wayanad, Kerala", arabica: 425.5, robusta: 308.0, area: "0.7L ha", output: "31,000 MT", temp: "25°C", rain: "2,100mm", status: "good" },
  { name: "Nilgiris, Tamil Nadu", arabica: 432.0, robusta: null, area: "0.3L ha", output: "8,000 MT", temp: "16°C", rain: "1,600mm", status: "excellent" },
  { name: "Araku, Andhra Pradesh", arabica: 438.0, robusta: null, area: "0.1L ha", output: "4,200 MT", temp: "20°C", rain: "1,500mm", status: "premium" },
];

const MARKET_DATA = {
  arabica: { name: "Arabica (A-Grade)", price: 430.50, change: 7.70, changePct: 1.82, currency: "₹/kg", volume: "14,820 bags", open: 424.80, high: 433.20, low: 422.50, exchange: "NCDEX Mumbai" },
  robusta: { name: "Robusta (Parchment)", price: 310.75, change: -2.95, changePct: -0.94, currency: "₹/kg", volume: "9,340 bags", open: 313.70, high: 314.90, low: 308.50, exchange: "MCX Mumbai" },
};


// Robusta (RM) futures — ICE/Liffe USD/MT
const ROBUSTA_FUTURES_BASE = [
  { contract: 'RMK26', label: "May '26", latest: 3510, open: 0,    high: 3510, low: 3510, prev: 3595, vol: 33,     oi: 712   },
  { contract: 'RMN26', label: "Jul '26", latest: 3306, open: 3374, high: 3379, low: 3295, prev: 3365, vol: 10502,  oi: 49871 },
  { contract: 'RMU26', label: "Sep '26", latest: 3175, open: 3258, high: 3259, low: 3166, prev: 3245, vol: 5876,   oi: 20427 },
  { contract: 'RMX26', label: "Nov '26", latest: 3100, open: 3177, high: 3184, low: 3093, prev: 3169, vol: 3212,   oi: 10042 },
  { contract: 'RMF27', label: "Jan '27", latest: 3034, open: 3110, high: 3111, low: 3028, prev: 3099, vol: 879,    oi: 5711  },
  { contract: 'RMH27', label: "Mar '27", latest: 3001, open: 3066, high: 3070, low: 2995, prev: 3063, vol: 355,    oi: 1970  },
  { contract: 'RMK27', label: "May '27", latest: 2980, open: 3014, high: 3029, low: 2980, prev: 3041, vol: 52,     oi: 967   },
  { contract: 'RMN27', label: "Jul '27", latest: 2964, open: 2998, high: 3014, low: 2964, prev: 3025, vol: 24,     oi: 426   },
  { contract: 'RMU27', label: "Sep '27", latest: 2950, open: 2964, high: 2964, low: 2950, prev: 3011, vol: 12,     oi: 338   },
  { contract: 'RMX27', label: "Nov '27", latest: 2940, open: 2954, high: 2954, low: 2940, prev: 2999, vol: 12,     oi: 25    },
];

// Arabica (KC) futures — ICE USc/lb
const ARABICA_FUTURES_BASE = [
  { contract: 'KCY00', label: 'Cash',    latest: 319.29, open: 319.29, high: 319.29, low: 319.29, prev: 327.93, vol: null,  oi: null  },
  { contract: 'KCN26', label: "Jul '26", latest: 264.20, open: 266.90, high: 270.15, low: 263.45, prev: 266.90, vol: 15878, oi: 77981 },
  { contract: 'KCU26', label: "Sep '26", latest: 256.75, open: 260.00, high: 263.25, low: 256.05, prev: 260.10, vol: 8386,  oi: 48443 },
  { contract: 'KCZ26', label: "Dec '26", latest: 249.80, open: 253.25, high: 256.25, low: 249.15, prev: 253.45, vol: 4594,  oi: 34149 },
  { contract: 'KCH27', label: "Mar '27", latest: 247.60, open: 251.35, high: 253.85, low: 247.20, prev: 251.25, vol: 1337,  oi: 13545 },
  { contract: 'KCK27', label: "May '27", latest: 246.90, open: 250.65, high: 253.05, low: 246.50, prev: 250.55, vol: 526,   oi: 4260  },
  { contract: 'KCN27', label: "Jul '27", latest: 246.65, open: 250.65, high: 252.00, low: 246.60, prev: 250.25, vol: 270,   oi: 3211  },
  { contract: 'KCU27', label: "Sep '27", latest: 245.55, open: 249.35, high: 250.60, low: 245.55, prev: 248.95, vol: 159,   oi: 1897  },
  { contract: 'KCZ27', label: "Dec '27", latest: 244.45, open: 247.90, high: 249.30, low: 244.45, prev: 247.55, vol: 122,   oi: 2421  },
  { contract: 'KCH28', label: "Mar '28", latest: 243.65, open: 246.90, high: 246.90, low: 243.65, prev: 246.70, vol: 49,    oi: 531   },
];
const WEATHER_DATA = [
  { region: "Coorg", condition: "Partly Cloudy", temp: 18, humidity: 78, wind: 12, rain7d: 48, icon: "⛅" },
  { region: "Chikmagalur", condition: "Clear Sky", temp: 22, humidity: 65, wind: 8, rain7d: 22, icon: "☀️" },
  { region: "Wayanad", condition: "Light Rain", temp: 25, humidity: 85, wind: 15, rain7d: 82, icon: "🌧️" },
  { region: "Nilgiris", condition: "Mist", temp: 16, humidity: 92, wind: 6, rain7d: 35, icon: "🌫️" },
  { region: "Araku Valley", condition: "Sunny", temp: 20, humidity: 70, wind: 10, rain7d: 18, icon: "☀️" },
];

const ALERTS_DATA = [
  { type: "warning", title: "Monsoon Arrival — SW Kerala", body: "IMD predicts early monsoon onset in Wayanad–Coorg belt by June 2nd, ±3 days. Harvest preparation advised.", time: "2h ago", severity: "HIGH" },
  { type: "info", title: "NCDEX Arabica Futures Up 1.82%", body: "Strong export demand from EU buyers. Coffee Board India reports 12% YoY volume rise in May.", time: "4h ago", severity: "MED" },
  { type: "danger", title: "White Stem Borer Alert — Chikmagalur", body: "Pest incidence reported in 3 estates. Coffee Board advisory issued. Yield risk: 8–15%.", time: "6h ago", severity: "HIGH" },
  { type: "info", title: "Araku GI Tag Premium — Export Boost", body: "Araku Valley GI-tagged coffee commands ₹600–800/kg in European specialty markets.", time: "1d ago", severity: "LOW" },
];

const EXPORT_DATA = [
  { month: "Nov", value: 58200 }, { month: "Dec", value: 62400 }, { month: "Jan", value: 55800 },
  { month: "Feb", value: 61200 }, { month: "Mar", value: 67500 }, { month: "Apr", value: 71200 }, { month: "May", value: 68400 },
];

function genSeries(base, days, vol = 0.012) {
  const data = [];
  let price = base;
  const now = new Date();
  for (let i = -days; i <= 7; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() + i);
    price += price * (Math.random() - 0.47) * vol;
    const isForecast = i > 0;
    data.push({
      date: d.toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
      price: isForecast ? null : parseFloat(price.toFixed(2)),
      forecast: isForecast ? parseFloat(price.toFixed(2)) : null,
      upper: isForecast ? parseFloat((price * 1.04).toFixed(2)) : null,
      lower: isForecast ? parseFloat((price * 0.96).toFixed(2)) : null,
    });
  }
  return data;
}

// ─── AI CHAT SERVICE ──────────────────────────────────────────────────────────
async function callCoffeeAI(messages, onChunk, onDone, onError) {
  const systemPrompt = \`You are CoffeeGPT India, an AI intelligence terminal for the Indian coffee market. You are an expert in:
- Indian coffee varieties: Arabica (Karnataka, Kerala, TN, AP), Robusta, Monsooned Malabar, Araku GI
- Key growing regions: Coorg (Kodagu), Chikmagalur, Wayanad, Nilgiris, Araku Valley, Bababudangiri
- Indian exchanges: NCDEX, MCX. Coffee Board of India. Commodity prices in INR/kg
- Indian monsoon patterns, SW & NE monsoon impact on Karnataka/Kerala coffee belt
- Indian coffee export markets: EU, Italy, Germany, USA; GI tags, specialty coffee movement
- Indian supply chain: APMC markets, FPOs, Coffee Board, exporters like Tata Coffee, CCL
- Agronomic issues: white stem borer, leaf rust, shade-grown practices, organic certification
- Indian government schemes: PM-KISAN, Coffee Board subsidies, APEDA export promotion

Always respond with specific Indian data, use INR pricing, reference Indian states/districts, and provide actionable insights for Indian coffee farmers, traders, and exporters. Be concise but data-rich. Use bullet points for lists. Reference current season (2025-26 crop year).\`;

  try {
    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: 1000,
        stream: true,
        system: systemPrompt,
        messages,
      }),
    });

    if (!response.ok) throw new Error(\`API error: \${response.status}\`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6).trim();
          if (data === "[DONE]") { onDone(); return; }
          try {
            const json = JSON.parse(data);
            if (json.type === "content_block_delta" && json.delta?.text) {
              onChunk(json.delta.text);
            }
          } catch {}
        }
      }
    }
    onDone();
  } catch (err) {
    onError(err);
  }
}

// ─── COMPONENTS ───────────────────────────────────────────────────────────────

function LiveDot({ color, size = 7 }) {
  return (
    <span style={{
      display: "inline-block", width: size, height: size, borderRadius: "50%",
      background: color, animation: "pulse 2s ease-in-out infinite", flexShrink: 0
    }} />
  );
}

function Badge({ text, color, bg }) {
  return (
    <span style={{ fontSize: 9, fontFamily: T.mono, padding: "2px 7px", borderRadius: 4, background: bg, color, letterSpacing: "0.08em", fontWeight: 600 }}>
      {text}
    </span>
  );
}

function Ticker() {
  const [offset, setOffset] = useState(0);
  const [liveItems, setLiveItems] = useState(TICKER_ITEMS);
  useEffect(() => {
    const iv = setInterval(() => {
      setOffset(o => o - 1);
      setLiveItems(items => items.map(item => ({
        ...item,
        raw: item.raw * (1 + (Math.random() - 0.5) * 0.0003),
        change: item.change + (Math.random() - 0.5) * 0.02,
      })));
    }, 30);
    return () => clearInterval(iv);
  }, []);
  const W = 210;
  const total = liveItems.length * W;
  const mod = ((offset % total) - total) % total;
  return (
    <div style={{ overflow: "hidden", height: 30, background: T.bg0, borderBottom: \`1px solid \${T.border}\`, display: "flex", alignItems: "center" }}>
      <div style={{ display: "flex", transform: \`translateX(\${mod}px)\`, whiteSpace: "nowrap", willChange: "transform" }}>
        {[...liveItems, ...liveItems, ...liveItems].map((t, i) => (
          <div key={i} style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "0 18px", width: W, borderRight: \`1px solid \${T.border}\` }}>
            <span style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, letterSpacing: "0.07em" }}>{t.label}</span>
            <span style={{ fontSize: 10, color: T.text0, fontFamily: T.mono, fontWeight: 500 }}>{typeof t.raw === "number" && t.label !== "COORG_TEMP" && t.label !== "CHIKMAGALUR" && t.label !== "MONSOON" ? (t.label.includes("ARABICA") || t.label.includes("ROBUSTA") ? \`₹\${t.raw.toFixed(2)}\` : t.label === "PLANTATION_IDX" ? t.raw.toFixed(0) : t.raw.toFixed(2)) : t.price}</span>
            <span style={{ fontSize: 9, color: t.change >= 0 ? T.greenBright : T.red, fontFamily: T.mono }}>{t.change >= 0 ? "▲" : "▼"}{Math.abs(t.change).toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PriceCard({ data, live }) {
  const isUp = data.changePct >= 0;
  return (
    <div style={{ flex: 1, background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: "18px 20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: T.text2, fontFamily: T.mono, letterSpacing: "0.08em", marginBottom: 4 }}>{data.exchange}</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: T.text0, fontFamily: T.sans }}>{data.name}</div>
        </div>
        <Badge text={isUp ? "▲ BUY" : "▼ SELL"} color={isUp ? T.greenBright : T.red} bg={isUp ? T.greenDim : T.redDim} />
      </div>
      <div style={{ fontSize: 30, fontWeight: 800, fontFamily: T.mono, color: T.saffron, letterSpacing: "-0.02em", marginBottom: 4 }}>
        {live ? \`₹\${live.toFixed(2)}\` : data.currency === "₹/kg" ? \`₹\${data.price.toFixed(2)}\` : data.price.toFixed(2)}
      </div>
      <div style={{ fontSize: 12, color: isUp ? T.greenBright : T.red, fontFamily: T.mono, marginBottom: 14 }}>
        {isUp ? "▲" : "▼"} ₹{Math.abs(data.change).toFixed(2)} ({Math.abs(data.changePct).toFixed(2)}%) today
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        {[["Open", \`₹\${data.open}\`], ["High", \`₹\${data.high}\`], ["Low", \`₹\${data.low}\`]].map(([l, v]) => (
          <div key={l} style={{ background: T.bg3, borderRadius: 8, padding: "6px 10px" }}>
            <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, marginBottom: 2 }}>{l}</div>
            <div style={{ fontSize: 11, color: T.text1, fontFamily: T.mono }}>{v}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, fontSize: 10, color: T.text2, fontFamily: T.mono }}>Vol: {data.volume} · {data.currency}</div>
    </div>
  );
}

function renderMarkdown(text) {
  const lines = text.split(/\\n/);
  return lines.map((line, i) => {
    if (!line) return <div key={i} style={{ height: 5 }} />;
    if (line.startsWith("### ")) return <div key={i} style={{ fontWeight: 700, color: T.saffron, fontSize: 12, marginTop: 10, marginBottom: 4, fontFamily: T.sans }}>{line.slice(4)}</div>;
    if (line.startsWith("## ")) return <div key={i} style={{ fontWeight: 700, color: T.gold, fontSize: 13, marginTop: 12, marginBottom: 5, fontFamily: T.sans }}>{line.slice(3)}</div>;
    if (line.startsWith("# ")) return <div key={i} style={{ fontWeight: 800, color: T.text0, fontSize: 14, marginTop: 14, marginBottom: 6, fontFamily: T.sans }}>{line.slice(2)}</div>;
    if (line.match(/^[-•*] /)) {
      const content = line.slice(2);
      return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4, fontSize: 12, lineHeight: 1.65, color: T.text1 }}>
        <span style={{ color: T.saffron, flexShrink: 0, marginTop: 1 }}>▸</span>
        <span dangerouslySetInnerHTML={{ __html: content.replace(/\\*\\*(.*?)\\*\\*/g, \`<strong style="color:\${T.text0}">$1</strong>\`) }} />
      </div>;
    }
    const html = line.replace(/\\*\\*(.*?)\\*\\*/g, \`<strong style="color:\${T.text0}">$1</strong>\`);
    return <div key={i} style={{ fontSize: 12, lineHeight: 1.7, color: T.text1, marginBottom: 2 }} dangerouslySetInnerHTML={{ __html: html }} />;
  });
}

function ChatPanel() {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "**ನಮಸ್ಕಾರ! Welcome to CoffeeGPT India.**\\n\\nI am your AI intelligence terminal for the Indian coffee market — connected to NCDEX/MCX data, IMD weather feeds, Coffee Board India updates, and regional crop intelligence from Coorg, Chikmagalur, Wayanad, Nilgiris & Araku Valley.\\n\\nAsk me about prices in ₹/kg, monsoon impact, export markets, or crop conditions.", done: true }
  ]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const streamRef = useRef("");
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, streamText]);

  const QUICK = [
    "Arabica price forecast — Coorg 2025",
    "Monsoon impact on Karnataka harvest",
    "How to export coffee from India?",
    "Araku GI tag premium prices",
    "White stem borer — what to do?",
    "NCDEX vs MCX coffee trading",
  ];

  const send = useCallback((text) => {
    const val = text || input;
    if (!val.trim() || isStreaming) return;
    setInput("");
    const userMsg = { role: "user", content: val, done: true };
    const assistantMsg = { role: "assistant", content: "", done: false };
    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);
    streamRef.current = "";
    setStreamText("");
    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }));
    callCoffeeAI(
      history,
      (chunk) => { streamRef.current += chunk; setStreamText(streamRef.current); },
      () => {
        setIsStreaming(false);
        const final = streamRef.current;
        setMessages(prev => { const n = [...prev]; n[n.length - 1] = { role: "assistant", content: final, done: true }; return n; });
        setStreamText("");
        streamRef.current = "";
      },
      (err) => {
        setIsStreaming(false);
        setMessages(prev => { const n = [...prev]; n[n.length - 1] = { role: "assistant", content: \`**Connection Error.** Unable to reach CoffeeGPT intelligence engine.\\n\\n_\${err.message}_\\n\\nPlease ensure your Anthropic API key is configured.\`, done: true }; return n; });
        setStreamText(""); streamRef.current = "";
      }
    );
  }, [input, isStreaming, messages]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: T.bg1 }}>
      <div style={{ padding: "14px 20px", borderBottom: \`1px solid \${T.border}\`, display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: \`linear-gradient(135deg, \${T.saffron}, #8B1A1A)\`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17 }}>☕</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, fontFamily: T.sans, color: T.text0 }}>CoffeeGPT India Intelligence</div>
          <div style={{ fontSize: 10, color: T.text2, display: "flex", alignItems: "center", gap: 5 }}>
            <LiveDot color={isStreaming ? T.saffron : T.greenBright} size={5} />
            {isStreaming ? "AI Streaming..." : "Connected · NCDEX · IMD · Coffee Board India"}
          </div>
        </div>
      </div>

      <div style={{ padding: "10px 16px", borderBottom: \`1px solid \${T.border}\`, display: "flex", gap: 6, flexWrap: "wrap", flexShrink: 0 }}>
        {QUICK.map((q, i) => (
          <button key={i} onClick={() => send(q)} disabled={isStreaming}
            style={{ fontSize: 10, padding: "4px 10px", borderRadius: 16, border: \`1px solid \${T.border}\`, background: T.bg3, color: T.text2, cursor: "pointer", fontFamily: T.sans, opacity: isStreaming ? 0.4 : 1, transition: "all 0.2s", whiteSpace: "nowrap" }}>
            {q}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
        {messages.map((msg, idx) => {
          const isLast = idx === messages.length - 1;
          const displayText = isLast && !msg.done && isStreaming ? streamText : msg.content;
          return (
            <div key={idx} style={{ display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 5, animation: "slideIn 0.25s ease forwards" }}>
              {msg.role === "assistant" && (
                <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, letterSpacing: "0.1em", display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 14, height: 14, borderRadius: 4, background: \`linear-gradient(135deg, \${T.saffron}, #8B1A1A)\`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 7 }}>☕</div>
                  COFFEEGPT · INDIA INTELLIGENCE
                </div>
              )}
              <div style={{
                maxWidth: "88%", padding: "12px 16px", borderRadius: msg.role === "user" ? "14px 14px 4px 14px" : "4px 14px 14px 14px",
                background: msg.role === "user" ? \`linear-gradient(135deg, \${T.saffron}25, \${T.goldDim})\` : T.bg3,
                border: \`1px solid \${msg.role === "user" ? T.saffron + "30" : T.border}\`,
              }}>
                {msg.role === "assistant"
                  ? (displayText ? renderMarkdown(displayText) : <div style={{ width: 20, height: 20, border: \`2px solid \${T.saffron}\`, borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />)
                  : <span style={{ fontSize: 12, color: T.text0, lineHeight: 1.6 }}>{msg.content}</span>
                }
                {isLast && isStreaming && msg.role === "assistant" && displayText && (
                  <span style={{ display: "inline-block", width: 2, height: 12, background: T.saffron, marginLeft: 2, animation: "blink 1s step-end infinite", verticalAlign: "text-bottom" }} />
                )}
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>

      <div style={{ padding: "12px 16px", borderTop: \`1px solid \${T.border}\`, flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", background: T.bg3, borderRadius: 12, border: \`1px solid \${T.border}\`, padding: "4px 4px 4px 14px" }}>
          <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && send()}
            placeholder="Ask about Indian coffee prices, weather, exports, agronomics..."
            disabled={isStreaming}
            style={{ flex: 1, background: "none", border: "none", color: T.text0, fontSize: 12, fontFamily: T.sans, padding: "8px 0", caretColor: T.saffron, outline: "none" }}
          />
          <button onClick={() => send()} disabled={!input.trim() || isStreaming}
            style={{ padding: "8px 16px", borderRadius: 9, background: input.trim() && !isStreaming ? \`linear-gradient(135deg, \${T.saffron}, \${T.gold})\` : T.bg4, color: input.trim() && !isStreaming ? "#000" : T.text2, fontSize: 12, fontWeight: 700, fontFamily: T.sans, cursor: input.trim() && !isStreaming ? "pointer" : "not-allowed", border: "none", transition: "all 0.2s", whiteSpace: "nowrap" }}>
            ಕಳುಹಿಸಿ ↑
          </button>
        </div>
        <div style={{ textAlign: "center", fontSize: 9, color: T.text3, fontFamily: T.mono, marginTop: 6 }}>
          Powered by Anthropic Claude · Karnataka Coffee Market Intelligence · NCDEX · IMD
        </div>
      </div>
    </div>
  );
}


function FuturesTable({ title, contracts, unit, color }) {
  const [rows, setRows] = useState(() =>
    contracts.map(c => ({ ...c, _latest: c.latest }))
  );

  useEffect(() => {
    const iv = setInterval(() => {
      setRows(prev => prev.map(r => {
        const drift = r._latest * (Math.random() - 0.502) * 0.0008;
        const newLatest = parseFloat((r._latest + drift).toFixed(2));
        return { ...r, _latest: newLatest };
      }));
    }, 1800);
    return () => clearInterval(iv);
  }, []);

  const now = '05/18/26';
  const isDecimal = unit === 'USc/lb';
  const fmt = v => v == null ? 'N/A' : isDecimal ? v.toFixed(2) : v.toLocaleString('en-IN');

  return (
    <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, marginBottom: 16, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', borderBottom: \`1px solid \${T.border}\`, display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, animation: 'pulse 2s ease-in-out infinite' }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: T.text0, fontFamily: T.sans }}>{title}</span>
        <span style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, marginLeft: 4 }}>· {unit} · ICE FUTURES</span>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: T.greenBright, fontFamily: T.mono, background: T.greenDim, padding: '2px 8px', borderRadius: 4 }}>LIVE</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead>
            <tr style={{ background: T.bg3 }}>
              {['Contract', 'Latest', 'Change', 'Open', 'High', 'Low', 'Previous', 'Volume', 'Open Int', 'Time'].map(h => (
                <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Contract' ? 'left' : 'right', color: T.text2, fontFamily: T.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.06em', whiteSpace: 'nowrap', borderBottom: \`1px solid \${T.border}\` }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const chg = parseFloat((r._latest - r.prev).toFixed(2));
              const isUp = chg >= 0;
              return (
                <tr key={r.contract}
                  style={{ borderBottom: \`1px solid \${T.border}\`, transition: 'background 0.3s', background: 'transparent' }}
                  onMouseEnter={e => e.currentTarget.style.background = T.bg3}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ color: color, fontSize: 9 }}>+</span>
                      <span style={{ color: color, fontFamily: T.mono, fontWeight: 600, fontSize: 10 }}>{r.contract}</span>
                      <span style={{ color: T.text2, fontFamily: T.mono, fontSize: 9 }}>({r.label})</span>
                    </div>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, fontWeight: 700, color: T.text0, fontSize: 10 }}>{fmt(r._latest)}s</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, fontWeight: 700, color: isUp ? T.greenBright : T.red, fontSize: 10 }}>{isUp ? '+' : ''}{fmt(chg)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text1, fontSize: 10 }}>{r.open === 0 ? '0' : fmt(r.open)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text1, fontSize: 10 }}>{fmt(r.high)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text1, fontSize: 10 }}>{fmt(r.low)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text2, fontSize: 10 }}>{fmt(r.prev)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text2, fontSize: 10 }}>{r.vol == null ? 'N/A' : r.vol.toLocaleString('en-IN')}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text2, fontSize: 10 }}>{r.oi == null ? 'N/A' : r.oi.toLocaleString('en-IN')}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: T.mono, color: T.text3, fontSize: 9 }}>{now}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MarketsPanel() {
  const [arabicaSeries] = useState(() => genSeries(430.5, 21));
  const [robustaSeries] = useState(() => genSeries(310.75, 21, 0.01));
  const [liveArabica, setLiveArabica] = useState(430.5);
  const [liveRobusta, setLiveRobusta] = useState(310.75);
  useEffect(() => {
    const iv = setInterval(() => {
      setLiveArabica(p => p + (Math.random() - 0.5) * 0.4);
      setLiveRobusta(p => p + (Math.random() - 0.5) * 0.3);
    }, 2000);
    return () => clearInterval(iv);
  }, []);

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
      <div style={{ background: T.bg1, border: \`1px solid \${T.border}\`, borderRadius: 10, padding: "10px 14px", fontSize: 11 }}>
        <div style={{ color: T.text2, marginBottom: 4, fontFamily: T.mono }}>{label}</div>
        <div style={{ color: d.forecast !== null ? T.gold : T.greenBright, fontFamily: T.mono, fontWeight: 600 }}>₹{(payload[0].value || 0).toFixed(2)}/kg</div>
        {d.lower && <div style={{ color: T.text2, fontSize: 10 }}>Band: ₹{d.lower}–₹{d.upper}</div>}
      </div>
    );
  };

  return (
    <div style={{ padding: 20, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, letterSpacing: "0.1em", marginBottom: 16 }}>NCDEX · MCX · LIVE INDIAN COFFEE FUTURES</div>
      <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
        <PriceCard data={MARKET_DATA.arabica} live={liveArabica} />
        <PriceCard data={MARKET_DATA.robusta} live={liveRobusta} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 16, marginBottom: 16 }}>
        <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 4, fontFamily: T.sans }}>Arabica Price Chart — INR/kg</div>
          <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, marginBottom: 14 }}>Historical + 7-Day AI Forecast · Coorg/Chikmagalur Benchmark</div>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={arabicaSeries} margin={{ top: 5, right: 0, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="gA" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={T.greenBright} stopOpacity={0.18} />
                    <stop offset="95%" stopColor={T.greenBright} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gF" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={T.gold} stopOpacity={0.18} />
                    <stop offset="95%" stopColor={T.gold} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="2 4" stroke={T.border} vertical={false} />
                <XAxis dataKey="date" stroke={T.text3} fontSize={9} tickMargin={8} minTickGap={28} />
                <YAxis stroke={T.text3} fontSize={9} domain={["dataMin - 5", "dataMax + 5"]} axisLine={false} tickLine={false} tickFormatter={v => \`₹\${v}\`} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="price" stroke={T.greenBright} strokeWidth={2} fillOpacity={1} fill="url(#gA)" connectNulls />
                <Area type="monotone" dataKey="forecast" stroke={T.gold} strokeWidth={2} strokeDasharray="5 4" fillOpacity={1} fill="url(#gF)" connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 14, fontFamily: T.sans }}>India Coffee Export Volume</div>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={EXPORT_DATA} margin={{ top: 5, right: 0, left: -15, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" stroke={T.border} vertical={false} />
                <XAxis dataKey="month" stroke={T.text3} fontSize={9} />
                <YAxis stroke={T.text3} fontSize={9} axisLine={false} tickLine={false} tickFormatter={v => \`\${(v / 1000).toFixed(0)}k\`} />
                <Tooltip formatter={v => [\`\${v.toLocaleString("en-IN")} bags\`, "Bags"]} contentStyle={{ background: T.bg1, border: \`1px solid \${T.border}\`, borderRadius: 8, fontSize: 11 }} />
                <Bar dataKey="value" fill={T.saffron} radius={[4, 4, 0, 0]} fillOpacity={0.85} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, textAlign: "center", marginTop: 6 }}>Source: Coffee Board of India · FY 2024-25</div>
        </div>
      </div>

      {/* ── FUTURES CHAIN TABLES ── */}
      <div style={{ marginBottom: 4 }}>
        <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, letterSpacing: '0.1em', marginBottom: 12 }}>ICE FUTURES CHAIN · LIVE CONTRACT PRICES</div>
        <FuturesTable
          title="Robusta Coffee (RM) — ICE/Liffe London"
          contracts={ROBUSTA_FUTURES_BASE}
          unit="USD/MT"
          color={T.saffron}
        />
        <FuturesTable
          title="Arabica Coffee (KC) — ICE New York"
          contracts={ARABICA_FUTURES_BASE}
          unit="USc/lb"
          color={T.gold}
        />
      </div>

      <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 14, fontFamily: T.sans }}>Indian Coffee Growing Regions — Live Prices</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: \`1px solid \${T.border}\` }}>
                {["Region", "Status", "Arabica ₹/kg", "Robusta ₹/kg", "Area", "Output", "Temp", "Rainfall"].map(h => (
                  <th key={h} style={{ padding: "6px 10px", textAlign: "left", color: T.text2, fontFamily: T.mono, fontSize: 9, fontWeight: 500, letterSpacing: "0.06em" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {INDIAN_REGIONS.map((r, i) => (
                <tr key={i} style={{ borderBottom: \`1px solid \${T.border}\`, transition: "background 0.2s" }}>
                  <td style={{ padding: "9px 10px", color: T.text0, fontFamily: T.sans, fontWeight: 600, fontSize: 11 }}>{r.name}</td>
                  <td style={{ padding: "9px 10px" }}>
                    <Badge text={r.status.toUpperCase()} color={r.status === "premium" || r.status === "excellent" ? T.gold : r.status === "optimal" ? T.greenBright : T.saffron} bg={r.status === "premium" ? T.goldDim : r.status === "optimal" ? T.greenDim : T.saffronDim} />
                  </td>
                  <td style={{ padding: "9px 10px", color: T.greenBright, fontFamily: T.mono, fontWeight: 600 }}>₹{r.arabica.toFixed(2)}</td>
                  <td style={{ padding: "9px 10px", color: r.robusta ? T.text1 : T.text3, fontFamily: T.mono }}>{r.robusta ? \`₹\${r.robusta.toFixed(2)}\` : "—"}</td>
                  <td style={{ padding: "9px 10px", color: T.text2, fontFamily: T.mono, fontSize: 10 }}>{r.area}</td>
                  <td style={{ padding: "9px 10px", color: T.text2, fontFamily: T.mono, fontSize: 10 }}>{r.output}</td>
                  <td style={{ padding: "9px 10px", color: T.cyan, fontFamily: T.mono, fontSize: 10 }}>{r.temp}</td>
                  <td style={{ padding: "9px 10px", color: T.text2, fontFamily: T.mono, fontSize: 10 }}>{r.rain}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function WeatherPanel() {
  return (
    <div style={{ padding: 20, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, letterSpacing: "0.1em", marginBottom: 16 }}>IMD · INDIA METEOROLOGICAL DEPARTMENT · COFFEE BELT WEATHER</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 20 }}>
        {WEATHER_DATA.map((w, i) => (
          <div key={i} style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, fontFamily: T.sans }}>{w.region}</div>
                <div style={{ fontSize: 10, color: T.text2, marginTop: 2 }}>{w.condition}</div>
              </div>
              <span style={{ fontSize: 24 }}>{w.icon}</span>
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: T.saffron, fontFamily: T.mono, marginBottom: 8 }}>{w.temp}°C</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {[["Humidity", \`\${w.humidity}%\`], ["Wind", \`\${w.wind} km/h\`], ["7d Rain", \`\${w.rain7d}mm\`]].map(([l, v]) => (
                <div key={l} style={{ background: T.bg3, borderRadius: 6, padding: "5px 8px" }}>
                  <div style={{ fontSize: 8, color: T.text3, fontFamily: T.mono, marginBottom: 2 }}>{l}</div>
                  <div style={{ fontSize: 10, color: T.text1, fontFamily: T.mono }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18, marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 4, fontFamily: T.sans }}>☁️ Monsoon Forecast 2025 — South India</div>
        <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, marginBottom: 14 }}>IMD EXTENDED RANGE PREDICTION · SW MONSOON 2025</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          {[
            { label: "Onset Date (Kerala)", value: "June 2±3d", color: T.cyan, icon: "📅" },
            { label: "Rainfall Anomaly", value: "+8% Normal", color: T.greenBright, icon: "🌧️" },
            { label: "Coffee Belt Impact", value: "Positive", color: T.gold, icon: "☕" },
          ].map((m, i) => (
            <div key={i} style={{ background: T.bg3, borderRadius: 10, padding: "14px 16px", textAlign: "center" }}>
              <div style={{ fontSize: 18, marginBottom: 6 }}>{m.icon}</div>
              <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, marginBottom: 6, letterSpacing: "0.06em" }}>{m.label}</div>
              <div style={{ fontSize: 14, color: m.color, fontFamily: T.mono, fontWeight: 700 }}>{m.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 14, fontFamily: T.sans }}>🌡️ Historical Rainfall — Coorg (mm/month)</div>
        <div style={{ height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={[
              { m: "Jan", v: 8 }, { m: "Feb", v: 12 }, { m: "Mar", v: 28 }, { m: "Apr", v: 85 },
              { m: "May", v: 165 }, { m: "Jun", v: 380 }, { m: "Jul", v: 510 }, { m: "Aug", v: 440 },
              { m: "Sep", v: 280 }, { m: "Oct", v: 145 }, { m: "Nov", v: 55 }, { m: "Dec", v: 22 }
            ]}>
              <CartesianGrid strokeDasharray="2 4" stroke={T.border} vertical={false} />
              <XAxis dataKey="m" stroke={T.text3} fontSize={9} />
              <YAxis stroke={T.text3} fontSize={9} axisLine={false} tickLine={false} tickFormatter={v => \`\${v}mm\`} />
              <Tooltip formatter={v => [\`\${v}mm\`, "Rainfall"]} contentStyle={{ background: T.bg1, border: \`1px solid \${T.border}\`, borderRadius: 8, fontSize: 11 }} />
              <Bar dataKey="v" fill={T.cyan} fillOpacity={0.75} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function AlertsPanel() {
  const colors = {
    warning: { bg: T.goldDim, border: T.gold + "40", text: T.gold, dot: T.gold },
    info: { bg: T.cyanDim, border: T.cyan + "40", text: T.cyan, dot: T.cyan },
    danger: { bg: T.redDim, border: T.red + "40", text: T.red, dot: T.red },
  };
  return (
    <div style={{ padding: 20, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, letterSpacing: "0.1em", marginBottom: 16 }}>COFFEE BOARD INDIA · IMD · NCDEX ALERTS</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {ALERTS_DATA.map((a, i) => {
          const c = colors[a.type];
          return (
            <div key={i} style={{ background: c.bg, borderRadius: 12, border: \`1px solid \${c.border}\`, padding: "14px 18px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <LiveDot color={c.dot} size={7} />
                  <span style={{ fontSize: 12, fontWeight: 700, color: c.text, fontFamily: T.sans }}>{a.title}</span>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
                  <Badge text={a.severity} color={c.text} bg={c.bg} />
                  <span style={{ fontSize: 9, color: T.text2, fontFamily: T.mono }}>{a.time}</span>
                </div>
              </div>
              <div style={{ fontSize: 12, color: T.text1, lineHeight: 1.65 }}>{a.body}</div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 20, background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 14, fontFamily: T.sans }}>🏛️ Coffee Board India — Active Schemes 2025</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            { name: "Integrated Coffee Development Project", benefit: "₹10,000–40,000/ha subsidy", status: "Active" },
            { name: "Coffee Quality Upgradation Scheme", benefit: "Equipment grant up to ₹5L", status: "Active" },
            { name: "Organic Certification Support", benefit: "₹25,000/ha for 3 years", status: "Active" },
            { name: "GI Tag Promotion — Araku / Coorg", benefit: "Export premium + branding support", status: "Active" },
            { name: "PM-KISAN for Coffee Growers", benefit: "₹6,000/year direct benefit", status: "Ongoing" },
          ].map((s, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: T.bg3, borderRadius: 8 }}>
              <div>
                <div style={{ fontSize: 11, color: T.text1, fontFamily: T.sans, fontWeight: 600 }}>{s.name}</div>
                <div style={{ fontSize: 10, color: T.saffron, fontFamily: T.mono, marginTop: 2 }}>{s.benefit}</div>
              </div>
              <Badge text={s.status} color={T.greenBright} bg={T.greenDim} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ForecastPanel() {
  const [arabicaSeries] = useState(() => genSeries(430.5, 30, 0.01));
  const [robustaSeries] = useState(() => genSeries(310.75, 30, 0.008));
  return (
    <div style={{ padding: 20, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono, letterSpacing: "0.1em", marginBottom: 16 }}>AI PRICE FORECASTING · INDIAN COFFEE MARKET · 2025-26</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
        {[
          { title: "Arabica 30-Day Target", value: "₹445–460/kg", dir: "▲ +3.4%", color: T.greenBright },
          { title: "Robusta 30-Day Target", value: "₹295–315/kg", dir: "▼ -1.2%", color: T.red },
          { title: "Monsoon Probability", value: "68% Avg+", dir: "▲ Positive", color: T.cyan },
          { title: "Crop Yield Outlook", value: "3.68L MT est.", dir: "▲ +4.2% YoY", color: T.gold },
        ].map((m, i) => (
          <div key={i} style={{ background: T.bg2, borderRadius: 12, border: \`1px solid \${T.border}\`, padding: "16px 18px" }}>
            <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, letterSpacing: "0.08em", marginBottom: 6 }}>{m.title}</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: m.color, fontFamily: T.mono, marginBottom: 4 }}>{m.value}</div>
            <div style={{ fontSize: 10, color: T.text2, fontFamily: T.mono }}>{m.dir}</div>
          </div>
        ))}
      </div>

      <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18, marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 4, fontFamily: T.sans }}>Arabica AI Forecast — 30 Day Outlook (₹/kg)</div>
        <div style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={arabicaSeries} margin={{ top: 5, right: 0, left: -10, bottom: 0 }}>
              <defs>
                <linearGradient id="gFA" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.greenBright} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={T.greenBright} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gFF" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={T.gold} stopOpacity={0.15} />
                  <stop offset="95%" stopColor={T.gold} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke={T.border} vertical={false} />
              <XAxis dataKey="date" stroke={T.text3} fontSize={9} tickMargin={8} minTickGap={30} />
              <YAxis stroke={T.text3} fontSize={9} axisLine={false} tickLine={false} domain={["dataMin - 8", "dataMax + 8"]} tickFormatter={v => \`₹\${v}\`} />
              <Tooltip contentStyle={{ background: T.bg1, border: \`1px solid \${T.border}\`, borderRadius: 8, fontSize: 11 }} formatter={v => [\`₹\${v?.toFixed(2) || "—"}/kg\`, ""]} />
              <Area type="monotone" dataKey="price" stroke={T.greenBright} strokeWidth={2} fillOpacity={1} fill="url(#gFA)" connectNulls />
              <Area type="monotone" dataKey="forecast" stroke={T.gold} strokeWidth={2} strokeDasharray="5 4" fillOpacity={1} fill="url(#gFF)" connectNulls />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}><div style={{ width: 16, height: 2, background: T.greenBright }} /><span style={{ fontSize: 9, color: T.text2, fontFamily: T.mono }}>Historical</span></div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}><div style={{ width: 16, height: 2, background: T.gold, borderTop: "1px dashed" }} /><span style={{ fontSize: 9, color: T.text2, fontFamily: T.mono }}>AI Forecast</span></div>
        </div>
      </div>

      <div style={{ background: T.bg2, borderRadius: 14, border: \`1px solid \${T.border}\`, padding: 18 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: T.text0, marginBottom: 14, fontFamily: T.sans }}>📊 AI Risk Matrix — India Coffee Season 2025-26</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            { factor: "SW Monsoon Timing Risk", score: 28, max: 100, color: T.greenBright, level: "LOW" },
            { factor: "White Stem Borer Incidence", score: 62, max: 100, color: T.gold, level: "MED" },
            { factor: "INR/USD Currency Volatility", score: 44, max: 100, color: T.saffron, level: "MED" },
            { factor: "Global Arabica Supply Surplus", score: 71, max: 100, color: T.red, level: "HIGH" },
            { factor: "Domestic Demand Growth", score: 18, max: 100, color: T.greenBright, level: "LOW" },
          ].map((s, i) => (
            <div key={i} style={{ marginBottom: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                <span style={{ fontSize: 11, color: T.text1, fontFamily: T.sans }}>{s.factor}</span>
                <Badge text={s.level} color={s.color} bg={s.color + "22"} />
              </div>
              <div style={{ height: 5, background: T.bg3, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ height: "100%", width: \`\${s.score}%\`, background: s.color, borderRadius: 3, transition: "width 1s ease" }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── APP ROOT ─────────────────────────────────────────────────────────────────
const CSS = \`
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Playfair+Display:wght@400;700&family=JetBrains+Mono:wght@300;400;500;600&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: \${T.bg0}; color: \${T.text0}; font-family: \${T.sans}; overflow: hidden; }
  ::-webkit-scrollbar { width: 3px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: \${T.border}; border-radius: 2px; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  @keyframes slideIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
  @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
  button { cursor: pointer; border: none; background: none; font-family: inherit; }
  input { font-family: inherit; }
  @media (max-width: 800px) {
    .right-panel { display: none !important; }
    .nav-scroll { overflow-x: auto; }
  }
\`;

const NAV = [
  { id: "chat", label: "AI Chat", icon: "◈" },
  { id: "markets", label: "Live Markets", icon: "◉" },
  { id: "weather", label: "Weather Intel", icon: "◆" },
  { id: "alerts", label: "Alerts", icon: "▲" },
  { id: "forecast", label: "Forecasting", icon: "⬡" },
];

export default function App() {
  const [active, setActive] = useState("chat");
  const [time, setTime] = useState(new Date());
  const [livePrice, setLivePrice] = useState(430.50);

  useEffect(() => {
    const iv = setInterval(() => {
      setTime(new Date());
      setLivePrice(p => p + (Math.random() - 0.5) * 0.3);
    }, 1000);
    return () => clearInterval(iv);
  }, []);

  const panels = {
    chat: <ChatPanel />,
    markets: <MarketsPanel />,
    weather: <WeatherPanel />,
    alerts: <AlertsPanel />,
    forecast: <ForecastPanel />,
  };

  return (
    <>
      <style>{CSS}</style>
      <div style={{ height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* HEADER */}
        <header style={{ height: 50, background: T.bg1, borderBottom: \`1px solid \${T.border}\`, display: "flex", alignItems: "center", padding: "0 18px", gap: 14, flexShrink: 0, zIndex: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
            <div style={{ width: 32, height: 32, borderRadius: 9, background: \`linear-gradient(135deg, \${T.saffron} 0%, #138808 50%, #000080 100%)\`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>☕</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 800, fontFamily: T.display, letterSpacing: "0.01em", lineHeight: 1, color: T.text0 }}>CoffeeGPT <span style={{ color: T.saffron }}>India</span></div>
              <div style={{ fontSize: 8, color: T.text2, fontFamily: T.mono, letterSpacing: "0.14em", lineHeight: 1 }}>INTELLIGENCE TERMINAL · ಕರ್ನಾಟಕ ಕಾಫಿ ಮಾರುಕಟ್ಟೆ</div>
            </div>
          </div>

          <nav className="nav-scroll" style={{ display: "flex", gap: 3 }}>
            {NAV.map(n => (
              <button key={n.id} onClick={() => setActive(n.id)}
                style={{ padding: "5px 13px", borderRadius: 7, border: \`1px solid \${active === n.id ? T.saffron + "50" : "transparent"}\`, background: active === n.id ? T.saffronDim : "transparent", color: active === n.id ? T.saffron : T.text2, fontSize: 11, fontFamily: T.sans, fontWeight: active === n.id ? 700 : 400, transition: "all 0.2s", display: "flex", alignItems: "center", gap: 5, whiteSpace: "nowrap" }}>
                <span style={{ fontSize: 9 }}>{n.icon}</span>{n.label}
              </button>
            ))}
          </nav>

          <div className="right-panel" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: T.bg3, borderRadius: 8, padding: "4px 12px", border: \`1px solid \${T.border}\` }}>
              <LiveDot color={T.greenBright} size={5} />
              <span style={{ fontSize: 10, color: T.text2, fontFamily: T.mono }}>LIVE</span>
              <span style={{ fontSize: 11, color: T.saffron, fontFamily: T.mono, fontWeight: 700 }}>₹{livePrice.toFixed(2)}</span>
              <span style={{ fontSize: 9, color: T.text3, fontFamily: T.mono }}>Arabica/kg</span>
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              {[T.saffron, T.text0, T.green].map((c, i) => (
                <div key={i} style={{ width: 5, height: 20, background: c, borderRadius: 1, opacity: 0.8 }} />
              ))}
            </div>
            <div style={{ fontSize: 11, color: T.text2, fontFamily: T.mono }}>
              {time.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })} IST
            </div>
          </div>
        </header>

        {/* TICKER */}
        <Ticker />

        {/* MAIN */}
        <main style={{ flex: 1, overflow: "hidden", display: "grid", gridTemplateColumns: active === "chat" ? "1fr 340px" : "1fr" }}>
          <div style={{ overflow: "hidden", borderRight: \`1px solid \${T.border}\` }}>
            {panels[active]}
          </div>

          {active === "chat" && (
            <div className="right-panel" style={{ background: T.bg1, overflowY: "auto", display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "14px 16px 10px", borderBottom: \`1px solid \${T.border}\` }}>
                <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, letterSpacing: "0.12em", marginBottom: 10 }}>LIVE FUTURES · NCDEX · MCX</div>
                {[
                  { name: "Arabica (Coorg)", price: livePrice, chg: 1.82, unit: "₹/kg" },
                  { name: "Robusta (Chikmagalur)", price: 310.75, chg: -0.94, unit: "₹/kg" },
                  { name: "Monsooned Malabar", price: 485.0, chg: 0.42, unit: "₹/kg" },
                ].map(m => (
                  <div key={m.name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 7, padding: "8px 10px", background: T.bg2, borderRadius: 8, border: \`1px solid \${T.border}\` }}>
                    <span style={{ fontSize: 10, color: T.text1 }}>{m.name}</span>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 12, fontFamily: T.mono, fontWeight: 700, color: T.saffron }}>₹{m.price.toFixed(2)}</div>
                      <div style={{ fontSize: 9, color: m.chg >= 0 ? T.greenBright : T.red, fontFamily: T.mono }}>{m.chg >= 0 ? "▲" : "▼"} {Math.abs(m.chg).toFixed(2)}%</div>
                    </div>
                  </div>
                ))}
              </div>

              <div style={{ padding: "12px 16px", borderBottom: \`1px solid \${T.border}\` }}>
                <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, letterSpacing: "0.12em", marginBottom: 8 }}>CROP CALENDAR 2025-26</div>
                {[
                  { event: "SW Monsoon Onset", date: "Jun 2", status: "upcoming", color: T.cyan },
                  { event: "Robusta Blossom", date: "Feb–Mar", status: "done", color: T.greenBright },
                  { event: "Arabica Harvest Begin", date: "Oct 15", status: "upcoming", color: T.saffron },
                  { event: "Robusta Harvest", date: "Dec–Feb", status: "upcoming", color: T.gold },
                  { event: "Coffee Board Auction", date: "Jul 10", status: "upcoming", color: T.saffron },
                ].map((e, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0", borderBottom: i < 4 ? \`1px solid \${T.border}\` : "none" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ width: 5, height: 5, borderRadius: "50%", background: e.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 10, color: T.text1 }}>{e.event}</span>
                    </div>
                    <span style={{ fontSize: 9, color: T.text2, fontFamily: T.mono }}>{e.date}</span>
                  </div>
                ))}
              </div>

              <div style={{ padding: "12px 16px" }}>
                <div style={{ fontSize: 9, color: T.text2, fontFamily: T.mono, letterSpacing: "0.12em", marginBottom: 8 }}>QUICK INSIGHTS</div>
                {[
                  { label: "India Rank (Global)", value: "6th", color: T.gold },
                  { label: "Annual Production", value: "3.65L MT", color: T.greenBright },
                  { label: "Export Revenue FY25", value: "₹5,200 Cr", color: T.saffron },
                  { label: "Domestic Consumption", value: "1.85L MT", color: T.cyan },
                ].map((s, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: i < 3 ? \`1px solid \${T.border}\` : "none" }}>
                    <span style={{ fontSize: 10, color: T.text2 }}>{s.label}</span>
                    <span style={{ fontSize: 10, fontFamily: T.mono, fontWeight: 700, color: s.color }}>{s.value}</span>
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
