import { useState, useEffect } from 'react';
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { T } from '../../styles/theme';
import { PriceCard } from './PriceCard';
import { SignalBar } from '../shared/SignalBar';
import { getMarketSummary } from '../../services/market';

const ARABICA_BASE = 223.40;
const ROBUSTA_BASE = 4105;

// Fallback mock data
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

const MARKET_DATA_FALLBACK = {
  arabica: { symbol: "KC1", name: "Arabica Futures", price: ARABICA_BASE, change: 3.2, changePct: 1.45, currency: "USc/lb", volume: "28,412", open: 219.90, high: 224.85, low: 218.60 },
  robusta: { symbol: "RC1", name: "Robusta Futures", price: ROBUSTA_BASE, change: -35, changePct: -0.84, currency: "$/MT", volume: "14,270", open: 4140, high: 4155, low: 4085 },
};

export const MarketsPanel = ({ arabicaPrice, arabicaDir, robustaPrice, robustaDir }: any) => {
  const [arabicaSeries, setArabicaSeries] = useState(() => genPriceSeries(ARABICA_BASE, 21));
  const [robustaSeries, setRobustaSeries] = useState(() => genPriceSeries(ROBUSTA_BASE, 21, 0.012));
  const [marketData, setMarketData] = useState<any>(null);

  useEffect(() => {
    // Attempt to load from real API (Task 4)
    getMarketSummary()
      .then(res => {
        if (res.data) setMarketData(res.data);
      })
      .catch(err => {
        console.warn("Using fallback mock data for market summary", err);
        setMarketData(MARKET_DATA_FALLBACK);
      });
  }, []);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
      <div style={{ background: T.bg1, border: `1px solid ${T.border}`, borderRadius: 10, padding: "10px 14px", fontSize: 12 }}>
        <div style={{ color: T.text2, marginBottom: 4, fontFamily: "'DM Mono', monospace" }}>{label}</div>
        <div style={{ color: d.type === "forecast" ? T.amber : T.green, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{payload[0].value?.toFixed(2)}</div>
        {d.lower && <div style={{ color: T.text2, fontSize: 11 }}>Band: {d.lower}–{d.upper}</div>}
      </div>
    );
  };

  if (!marketData) return <div style={{ padding: 40, color: T.text2 }}>Loading...</div>;

  return (
    <div style={{ padding: 24, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", gap: 20, marginBottom: 24 }}>
        <PriceCard data={marketData.arabica || MARKET_DATA_FALLBACK.arabica} livePrice={arabicaPrice} dir={arabicaDir} />
        <PriceCard data={marketData.robusta || MARKET_DATA_FALLBACK.robusta} livePrice={robustaPrice} dir={robustaDir} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
        {/* Main Chart */}
        <div style={{ background: T.bg2, borderRadius: 16, border: `1px solid ${T.border}`, padding: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: T.text0, marginBottom: 4 }}>Price Structure (Arabica)</div>
              <div style={{ fontSize: 11, color: T.text2, fontFamily: "'DM Mono', monospace" }}>Historical + 7-Day AI Forecast Overlay</div>
            </div>
          </div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={arabicaSeries} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={T.green} stopOpacity={0.2} />
                    <stop offset="95%" stopColor={T.green} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorForecast" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={T.amber} stopOpacity={0.2} />
                    <stop offset="95%" stopColor={T.amber} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={T.borderHover} vertical={false} />
                <XAxis dataKey="date" stroke={T.text3} fontSize={10} tickMargin={10} minTickGap={30} />
                <YAxis stroke={T.text3} fontSize={10} domain={['dataMin - 10', 'dataMax + 10']} axisLine={false} tickLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine x={arabicaSeries.find(d => d.type === 'forecast')?.date} stroke={T.borderHover} strokeDasharray="3 3" />
                <Area type="monotone" dataKey="price" stroke={T.green} strokeWidth={2} fillOpacity={1} fill="url(#colorPrice)" connectNulls />
                <Area type="monotone" dataKey="forecast" stroke={T.amber} strokeWidth={2} strokeDasharray="5 5" fillOpacity={1} fill="url(#colorForecast)" connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Technicals */}
        <div style={{ background: T.bg2, borderRadius: 16, border: `1px solid ${T.border}`, padding: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: T.text0, marginBottom: 20, fontFamily: "'Syne', sans-serif" }}>AI Quantitative Signals</div>
          <SignalBar label="Implied Volatility (30D)" value={24.6} color={T.amber} icon="⚡" />
          <SignalBar label="RSI (14D)" value={68} max={100} color={T.cyan} icon="📈" />
          <SignalBar label="MACD Histogram" value={1.42} max={5} color={T.green} icon="📊" />
          <SignalBar label="COT Net Spec Longs" value={34012} max={50000} color={T.bronze} icon="🏦" />
        </div>
      </div>
    </div>
  );
};
