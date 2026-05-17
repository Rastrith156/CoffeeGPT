import { useState, useEffect } from 'react';

let sharedTick = 0;
const tickSubscribers = new Set<(tick: number) => void>();

setInterval(() => {
  sharedTick++;
  tickSubscribers.forEach(cb => cb(sharedTick));
}, 1000);

export const useSharedTick = (intervalSeconds = 1) => {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const cb = (t: number) => {
      if (t % intervalSeconds === 0) setTick(t);
    };
    tickSubscribers.add(cb);
    return () => { tickSubscribers.delete(cb); };
  }, [intervalSeconds]);
  return tick;
};
