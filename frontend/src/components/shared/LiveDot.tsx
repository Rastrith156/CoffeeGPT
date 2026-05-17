import { T } from '../../styles/theme';

export const LiveDot = ({ color = T.cyan, size = 7 }: any) => (
  <div 
    className="live-dot" 
    style={{ 
      width: size, 
      height: size, 
      borderRadius: "50%", 
      background: color, 
      boxShadow: `0 0 6px ${color}` 
    }} 
  />
);
