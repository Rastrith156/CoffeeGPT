import { T } from '../../styles/theme';

export const SignalBar = ({ label, value, max = 100, color, icon }: any) => (
  <div style={{ marginBottom: 14 }}>
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
      <span style={{ fontSize: 11, color: T.text2, letterSpacing: "0.08em" }}>{icon} {label.toUpperCase()}</span>
      <span style={{ fontSize: 13, color, fontFamily: "'DM Mono', monospace", fontWeight: 500 }}>{value}</span>
    </div>
    <div style={{ height: 3, background: T.bg3, borderRadius: 4, overflow: "hidden" }}>
      <div style={{ width: `${(value / max) * 100}%`, height: "100%", background: `linear-gradient(90deg, ${color}88, ${color})`, borderRadius: 4, transition: "width 1s ease" }} />
    </div>
  </div>
);
