import { useState, useEffect } from 'react';
import { T } from '../../styles/theme';

export const AgentReasoning = () => {
  const [step, setStep] = useState(0);
  const steps = [
    "Connecting to CoffeeGPT Engine...",
    "Querying Qdrant Vector Store...",
    "Retrieving LIVE Market Snapshot...",
    "Parsing 14-day Weather Forecasts...",
    "Synthesizing RAG Context...",
    "Formatting Final Response..."
  ];

  useEffect(() => {
    const iv = setInterval(() => {
      setStep(s => Math.min(s + 1, steps.length - 1));
    }, 1100);
    return () => clearInterval(iv);
  }, []);

  return (
    <div style={{ padding: "12px 16px", background: T.bg3, borderRadius: "4px 16px 16px 16px", border: `1px solid ${T.border}`, width: "fit-content", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div className="spinning" style={{ width: 14, height: 14, border: `2px solid ${T.cyan}`, borderTopColor: "transparent", borderRadius: "50%" }} />
        <span style={{ fontSize: 12, color: T.cyan, fontWeight: 600, fontFamily: "'Syne', sans-serif" }}>AI is Reasoning</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginLeft: 2 }}>
        {steps.map((s, i) => (
          <div key={i} style={{ display: i <= step ? "flex" : "none", alignItems: "center", gap: 8, opacity: i === step ? 1 : 0.4 }}>
            <span style={{ color: i === step ? T.cyan : T.green, fontSize: 10 }}>{i === step ? "▶" : "✓"}</span>
            <span style={{ fontSize: 11, color: i === step ? T.text0 : T.text2, fontFamily: "'DM Mono', monospace" }}>{s}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
