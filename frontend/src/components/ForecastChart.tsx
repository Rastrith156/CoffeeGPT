import React from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useQuery } from '@tanstack/react-query';
import { LoadingSkeleton } from './LoadingSkeleton';

// Mock fetcher since backend forecast endpoint isn't fully implemented with data yet
const fetchForecast = async () => {
  // Simulate network delay
  await new Promise(r => setTimeout(r, 1000));
  
  // Generate dummy curve: slight upward trend with noise
  const data = [];
  let basePrice = 220;
  const now = new Date();
  
  for (let i = -14; i <= 7; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() + i);
    
    // add some randomness
    basePrice += (Math.random() - 0.4) * 3;
    
    data.push({
      date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      price: Number(basePrice.toFixed(2)),
      type: i <= 0 ? 'historical' : 'forecast',
      lower: i <= 0 ? null : Number((basePrice * 0.95).toFixed(2)),
      upper: i <= 0 ? null : Number((basePrice * 1.05).toFixed(2))
    });
  }
  
  return data;
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div style={{ backgroundColor: '#222', border: '1px solid #444', padding: '10px', borderRadius: '8px', color: '#fff' }}>
        <p style={{ margin: '0 0 5px 0', color: '#aaa', fontSize: '12px' }}>{label} ({data.type})</p>
        <p style={{ margin: '0', fontWeight: 'bold', color: data.type === 'forecast' ? '#ff9800' : '#4caf50' }}>
          {data.price} USc/lb
        </p>
        {data.lower && (
           <p style={{ margin: '5px 0 0 0', fontSize: '11px', color: '#888' }}>
             Range: {data.lower} - {data.upper}
           </p>
        )}
      </div>
    );
  }
  return null;
};

export const ForecastChart: React.FC = () => {
  const { data, isLoading } = useQuery({
    queryKey: ['forecastData'],
    queryFn: fetchForecast,
    refetchOnWindowFocus: false,
  });

  if (isLoading) return <LoadingSkeleton type="chart" count={1} />;

  return (
    <div style={{ backgroundColor: '#1a1a1a', borderRadius: '12px', border: '1px solid #333', padding: '20px', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h3 style={{ margin: '0 0 20px 0', color: '#fff', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        📈 7-Day Price Forecast (Arabica)
      </h3>
      <div style={{ flex: 1, width: '100%', minHeight: '250px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#4caf50" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#4caf50" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
            <XAxis dataKey="date" stroke="#666" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="#666" fontSize={12} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" dataKey="price" stroke="#4caf50" strokeWidth={2} fillOpacity={1} fill="url(#colorPrice)" />
            {/* Draw a dashed line for forecast part conceptually - in full implementation we separate series */}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
