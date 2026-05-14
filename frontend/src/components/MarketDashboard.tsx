import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { LoadingSkeleton } from './LoadingSkeleton';

const fetchMarketPrices = async () => {
  const res = await fetch('/api/v1/market/prices', { headers: { 'X-API-Key': 'bypass_dev_key' }});
  if (!res.ok) throw new Error('Failed to fetch prices');
  return res.json();
};

const fetchHealth = async () => {
  const res = await fetch('/api/v1/health/deep');
  if (!res.ok && res.status !== 503) throw new Error('Failed to fetch health');
  return res.json();
};

export const MarketDashboard: React.FC = () => {
  const { data: prices, isLoading: pricesLoading, error: pricesError } = useQuery({
    queryKey: ['marketPrices'],
    queryFn: fetchMarketPrices,
    refetchInterval: 15000,
  });

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['systemHealth'],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  });

  const renderPriceCard = (title: string, data: any) => {
    if (!data) return null;
    const isUp = data.change_pct >= 0;
    const color = isUp ? '#4caf50' : '#f44336';
    const bg = isUp ? 'rgba(76, 175, 80, 0.1)' : 'rgba(244, 67, 54, 0.1)';
    const arrow = isUp ? '↑' : '↓';

    return (
      <div style={{ flex: 1, backgroundColor: '#222', padding: '20px', borderRadius: '12px', border: '1px solid #333', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ color: '#aaa', fontSize: '14px', textTransform: 'uppercase', letterSpacing: '1px' }}>{title}</div>
        <div style={{ fontSize: '32px', fontWeight: 'bold', color: '#fff' }}>
          {parseFloat(data.price).toFixed(2)} <span style={{ fontSize: '16px', color: '#888' }}>{data.currency}</span>
        </div>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', color, backgroundColor: bg, padding: '4px 8px', borderRadius: '4px', alignSelf: 'flex-start', fontSize: '14px', fontWeight: 'bold' }}>
          {arrow} {Math.abs(parseFloat(data.change_pct)).toFixed(2)}%
        </div>
      </div>
    );
  };

  const renderSystemHealth = () => {
    if (healthLoading) return <LoadingSkeleton type="text" count={1} />;
    if (!health) return null;

    const isHealthy = health.status === 'healthy';
    const color = isHealthy ? '#4caf50' : (health.status === 'degraded' ? '#ff9800' : '#f44336');

    return (
      <div style={{ marginTop: '20px', backgroundColor: '#222', padding: '15px 20px', borderRadius: '12px', border: '1px solid #333', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: color, boxShadow: `0 0 10px ${color}` }} />
          <span style={{ color: '#fff', fontSize: '14px', fontWeight: 500 }}>System Status: <span style={{ textTransform: 'capitalize', color }}>{health.status}</span></span>
        </div>
        <div style={{ display: 'flex', gap: '15px' }}>
          {health.services?.map((svc: any) => (
             <div key={svc.name} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
               <span style={{ color: '#aaa', fontSize: '11px', textTransform: 'uppercase' }}>{svc.name}</span>
               <span style={{ color: svc.status === 'ok' ? '#4caf50' : '#f44336', fontSize: '12px', fontWeight: 'bold' }}>{svc.latency_ms} ms</span>
             </div>
          ))}
        </div>
      </div>
    );
  };

  if (pricesLoading) return <div style={{ display: 'flex', gap: '20px' }}><LoadingSkeleton type="card" count={2} /></div>;
  if (pricesError) return <div style={{ color: '#f44336', padding: '20px', backgroundColor: '#331111', borderRadius: '12px' }}>Failed to load market data.</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: '20px', width: '100%' }}>
        {renderPriceCard('Arabica Futures', prices?.arabica)}
        {renderPriceCard('Robusta', prices?.robusta)}
      </div>
      {renderSystemHealth()}
    </div>
  );
};
