import { useState } from 'react';
import { T } from '../../styles/theme';

export const GlassCard = ({ children, style = {}, hover = false }: any) => {
  const [hov, setHov] = useState(false);
  return (
    <div
      onMouseEnter={() => hover && setHov(true)}
      onMouseLeave={() => hover && setHov(false)}
      style={{
        background: T.bg2,
        border: `1px solid ${hov ? T.borderHover : T.border}`,
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
