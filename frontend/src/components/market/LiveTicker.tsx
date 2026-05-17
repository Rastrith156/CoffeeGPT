import { useState, useRef, useEffect } from 'react';
import { T } from '../../styles/theme';

const TICKER_ITEMS = [
  { label: "KC1!", price: "223.40", change: 1.45 },
  { label: "RC1!", price: "4105", change: -0.84 },
  { label: "BRL/USD", price: "4.92", change: -0.21 },
  { label: "VND/USD", price: "24510", change: 0.05 },
  { label: "MINAS_TEMP", price: "12°C", change: -4.2 },
  { label: "ICE_INV", price: "284k", change: -1.2 },
];

export const LiveTicker = () => {
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
    <div style={{ overflow: "hidden", height: 32, background: T.bg1, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center" }} ref={containerRef}>
      <div style={{ display: "flex", transform: `translateX(${mod}px)`, whiteSpace: "nowrap", willChange: "transform" }}>
        {[...TICKER_ITEMS, ...TICKER_ITEMS, ...TICKER_ITEMS].map((t, i) => (
          <div key={i} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "0 20px", width: itemWidth, borderRight: `1px solid ${T.border}` }}>
            <span style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.06em" }}>{t.label}</span>
            <span style={{ fontSize: 11, color: T.text0, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{t.price}</span>
            <span style={{ fontSize: 10, color: t.change >= 0 ? T.green : T.red, fontFamily: "'DM Mono', monospace" }}>{t.change >= 0 ? "▲" : "▼"}{Math.abs(t.change).toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
};
