import { T } from '../../styles/theme';

export const AlertBadge = ({ severity }: { severity: string }) => {
  const map: Record<string, string[]> = { 
    critical: [T.red, T.redDim], 
    high: [T.orange, T.amberDim], 
    medium: [T.amber, T.amberDim], 
    low: [T.text2, T.bg3] 
  };
  const [c, bg] = map[severity.toLowerCase()] || [T.text2, T.bg3];
  
  return (
    <span 
      style={{ 
        fontSize: 10, 
        fontFamily: "'DM Mono', monospace", 
        fontWeight: 600, 
        letterSpacing: "0.1em", 
        color: c, 
        background: bg, 
        padding: "2px 7px", 
        borderRadius: 4, 
        border: `1px solid ${c}33`, 
        textTransform: "uppercase" 
      }}
    >
      {severity}
    </span>
  );
};
