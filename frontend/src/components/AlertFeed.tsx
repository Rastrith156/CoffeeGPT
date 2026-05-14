import React, { useEffect, useState } from 'react';
import { useStore } from '../store/useStore';

interface Alert {
  id: string;
  commodity: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  message: string;
  change_pct?: number;
  triggered_at: string;
}

export const AlertFeed: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const incrementAlertCount = useStore((state) => state.incrementAlertCount);

  useEffect(() => {
    // In a real app, this would connect to an SSE/WebSocket endpoint specifically for alerts
    // For now, we simulate fetching recent alerts
    const mockAlerts: Alert[] = [
      {
        id: '1',
        commodity: 'arabica',
        severity: 'high',
        message: 'Spike detected: Arabica price increased by 3.2%',
        change_pct: 3.2,
        triggered_at: new Date(Date.now() - 1000 * 60 * 5).toISOString()
      },
      {
        id: '2',
        commodity: 'robusta',
        severity: 'medium',
        message: 'Volatility warning: Robusta trading volume abnormal',
        triggered_at: new Date(Date.now() - 1000 * 60 * 30).toISOString()
      }
    ];

    setAlerts(mockAlerts);
    incrementAlertCount();
    incrementAlertCount();

    // Mocking an incoming alert after 10s
    const timer = setTimeout(() => {
       const newAlert: Alert = {
         id: Date.now().toString(),
         commodity: 'arabica',
         severity: 'critical',
         message: 'FROST WARNING: Severe frost risk reported in Minas Gerais, Brazil',
         triggered_at: new Date().toISOString()
       };
       setAlerts((prev) => [newAlert, ...prev]);
       incrementAlertCount();
    }, 10000);

    return () => clearTimeout(timer);
  }, [incrementAlertCount]);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return '#f44336'; // Red
      case 'high': return '#ff9800'; // Orange
      case 'medium': return '#ffeb3b'; // Yellow
      case 'low': return '#2196f3'; // Blue
      default: return '#888';
    }
  };

  return (
    <div style={{ backgroundColor: '#1a1a1a', borderRadius: '12px', border: '1px solid #333', overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '15px 20px', borderBottom: '1px solid #333', backgroundColor: '#222', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, color: '#fff', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          🔔 Live Alerts
        </h3>
        <span style={{ backgroundColor: '#f44336', color: '#fff', padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: 'bold' }}>
          {alerts.length}
        </span>
      </div>
      <div style={{ padding: '10px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {alerts.map(alert => (
           <div key={alert.id} style={{ backgroundColor: '#222', borderRadius: '8px', padding: '12px', borderLeft: `4px solid ${getSeverityColor(alert.severity)}` }}>
             <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
               <span style={{ color: getSeverityColor(alert.severity), fontSize: '12px', textTransform: 'uppercase', fontWeight: 'bold' }}>
                 {alert.severity} • {alert.commodity}
               </span>
               <span style={{ color: '#666', fontSize: '11px' }}>
                 {new Date(alert.triggered_at).toLocaleTimeString()}
               </span>
             </div>
             <div style={{ color: '#ddd', fontSize: '14px', lineHeight: '1.4' }}>
               {alert.message}
             </div>
           </div>
        ))}
        {alerts.length === 0 && (
           <div style={{ textAlign: 'center', color: '#666', padding: '20px 0', fontSize: '14px' }}>
             No active alerts
           </div>
        )}
      </div>
    </div>
  );
};
