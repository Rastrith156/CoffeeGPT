import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { T } from '../../styles/theme';

export const ForecastPanel = ({ arabicaSeries }: any) => {
  return (
    <div style={{ padding: 24, height: "100%", overflowY: "auto" }}>
      <div style={{ fontSize: 18, fontWeight: 600, color: T.text0, marginBottom: 20, fontFamily: "'Syne', sans-serif" }}>AI Price Forecasting</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 24 }}>
        <div style={{ background: T.bg2, borderRadius: 16, border: `1px solid ${T.border}`, padding: 20, height: 400 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: T.text0, marginBottom: 20 }}>Arabica 30-Day Probability Cone</div>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={arabicaSeries} margin={{ top: 10, right: 0, left: -20, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={T.borderHover} vertical={false} />
              <XAxis dataKey="date" stroke={T.text3} fontSize={10} tickMargin={10} />
              <YAxis stroke={T.text3} fontSize={10} domain={['dataMin - 10', 'dataMax + 10']} axisLine={false} tickLine={false} />
              <Tooltip
                content={({ active, payload }: any) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  if (!d.upper) return null;
                  return (
                    <div style={{ background: T.bg1, border: `1px solid ${T.border}`, borderRadius: 10, padding: "10px 14px", fontSize: 12 }}>
                      <div style={{ color: T.text2, marginBottom: 4 }}>{d.date}</div>
                      <div style={{ color: T.amber, fontWeight: 600, fontFamily: "'DM Mono', monospace" }}>Expected: {d.forecast?.toFixed(2)}</div>
                      <div style={{ color: T.text1, fontSize: 11, fontFamily: "'DM Mono', monospace" }}>{d.lower?.toFixed(2)} – {d.upper?.toFixed(2)}</div>
                    </div>
                  );
                }}
              />
              <Area type="monotone" dataKey="upper" stroke="none" fill={T.amberDim} />
              <Area type="monotone" dataKey="lower" stroke="none" fill={T.bg2} />
              <Area type="monotone" dataKey="forecast" stroke={T.amber} strokeWidth={2} fill="none" strokeDasharray="5 5" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ background: T.bg2, borderRadius: 16, border: `1px solid ${T.border}`, padding: 20 }}>
            <div style={{ fontSize: 12, color: T.text2, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12, fontFamily: "'DM Mono', monospace" }}>Forecast Drivers</div>
            {[
              { label: "Weather Risk Premium", val: "+4.2%", color: T.green },
              { label: "Macro/USD Drag", val: "-1.1%", color: T.red },
              { label: "Supply Chain Disrupt", val: "+0.8%", color: T.green },
            ].map((d, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", marginBottom: 10, fontSize: 13 }}>
                <span style={{ color: T.text1 }}>{d.label}</span>
                <span style={{ color: d.color, fontFamily: "'DM Mono', monospace", fontWeight: 600 }}>{d.val}</span>
              </div>
            ))}
          </div>
          <div style={{ background: `linear-gradient(135deg, ${T.bronze}11, ${T.amber}11)`, borderRadius: 16, border: `1px solid ${T.bronze}33`, padding: 20 }}>
            <div style={{ fontSize: 12, color: T.bronze, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8, fontFamily: "'DM Mono', monospace" }}>AI Conclusion</div>
            <div style={{ fontSize: 14, color: T.text0, lineHeight: 1.6 }}>Bullish asymmetry remains elevated. Weather risk premium has not fully priced into the KC1! contract. Re-evaluate position sizing ahead of next INMET synoptic update.</div>
          </div>
        </div>
      </div>
    </div>
  );
};
