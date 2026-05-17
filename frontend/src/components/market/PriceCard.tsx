import { useState, useRef, useEffect } from 'react';
import { T } from '../../styles/theme';
import { GlassCard } from '../shared/GlassCard';

export const PriceCard = ({ data, livePrice, dir }: any) => {
  const isUp = data.changePct >= 0;
  const [flash, setFlash] = useState(false);
  const prevDir = useRef(dir);
  
  useEffect(() => {
    if (dir !== prevDir.current) { 
      setFlash(true); 
      setTimeout(() => setFlash(false), 600); 
      prevDir.current = dir; 
    }
  }, [dir]);

  return (
    <GlassCard style={{ flex: 1, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, color: T.text2, letterSpacing: "0.12em", textTransform: "uppercase", fontFamily: "'DM Mono', monospace", marginBottom: 4 }}>{data.symbol} · {data.name}</div>
          <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>Vol {data.volume}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: isUp ? T.greenDim : T.redDim, borderRadius: 8, padding: "4px 10px", border: `1px solid ${isUp ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}` }}>
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
