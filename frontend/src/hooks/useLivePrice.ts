import { useState, useEffect } from 'react';
import { useSharedTick } from './useSharedTick';

export const useLivePrice = (base: number, volatility = 0.0008) => {
  const [price, setPrice] = useState(base);
  const [dir, setDir] = useState<string | null>(null);
  const tick = useSharedTick(2); // Updates every 2 seconds
  
  useEffect(() => {
    if (tick === 0) return;
    setPrice(p => {
      const next = parseFloat((p + p * (Math.random() - 0.5) * volatility).toFixed(2));
      setDir(next >= p ? "up" : "down");
      return next;
    });
  }, [tick, volatility]);
  
  return { price, dir };
};
