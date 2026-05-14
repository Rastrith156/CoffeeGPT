import React, { useEffect, useState } from 'react';
import { useStore } from '../store/useStore';

export const LiveTicker: React.FC = () => {
  const [arabica, setArabica] = useState({ price: 0, change: 0 });
  const [robusta, setRobusta] = useState({ price: 0, change: 0 });
  const setConnectionStatus = useStore((state) => state.setConnectionStatus);

  useEffect(() => {
    // We poll the live endpoint to simulate a ticker if WebSocket isn't natively implemented in backend yet.
    // Assuming /api/v1/live/snapshot is available or we poll /api/v1/market/prices
    let intervalId: NodeJS.Timeout;

    const fetchPrices = async () => {
      try {
        setConnectionStatus('connecting');
        const res = await fetch('/api/v1/market/prices', { headers: { 'X-API-Key': 'bypass_dev_key' }});
        if (res.ok) {
          const data = await res.json();
          if (data.arabica) {
            setArabica({ price: parseFloat(data.arabica.price), change: parseFloat(data.arabica.change_pct) });
          }
          if (data.robusta) {
            setRobusta({ price: parseFloat(data.robusta.price), change: parseFloat(data.robusta.change_pct) });
          }
          setConnectionStatus('connected');
        } else {
          setConnectionStatus('disconnected');
        }
      } catch (err) {
        setConnectionStatus('disconnected');
      }
    };

    fetchPrices();
    intervalId = setInterval(fetchPrices, 15000); // Poll every 15s for the ticker

    return () => clearInterval(intervalId);
  }, [setConnectionStatus]);

  const renderTickerItem = (label: string, price: number, change: number, unit: string) => {
    const isUp = change >= 0;
    const color = isUp ? '#4caf50' : '#f44336';
    const arrow = isUp ? '▲' : '▼';

    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '0 15px', borderRight: '1px solid #333' }}>
        <span style={{ color: '#aaa', fontWeight: 500, fontSize: '13px' }}>{label}</span>
        <span style={{ color: '#fff', fontWeight: 'bold', fontSize: '14px' }}>
          {price > 0 ? price.toFixed(2) : '---'} {unit}
        </span>
        <span style={{ color, fontWeight: 'bold', fontSize: '13px' }}>
          {price > 0 ? `${arrow} ${Math.abs(change).toFixed(2)}%` : ''}
        </span>
      </div>
    );
  };

  return (
    <div style={{ 
      width: '100%', 
      height: '40px', 
      backgroundColor: '#111', 
      borderBottom: '1px solid #222',
      display: 'flex',
      alignItems: 'center',
      overflow: 'hidden',
      position: 'relative'
    }}>
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        height: '100%',
        padding: '0 10px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', paddingRight: '15px', borderRight: '1px solid #333' }}>
           <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: arabica.price > 0 ? '#4caf50' : '#f44336', animation: arabica.price > 0 ? 'pulse 2s infinite' : 'none' }} />
           <span style={{ color: '#888', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '1px' }}>LIVE</span>
        </div>
        {renderTickerItem('ARABICA', arabica.price, arabica.change, 'USc/lb')}
        {renderTickerItem('ROBUSTA', robusta.price, robusta.change, 'USD/t')}
      </div>
    </div>
  );
};
