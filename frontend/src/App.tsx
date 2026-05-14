import React from 'react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LiveTicker } from './components/LiveTicker';
import { MarketDashboard } from './components/MarketDashboard';
import { ChatPanel } from './components/ChatPanel';
import { AlertFeed } from './components/AlertFeed';
import { ForecastChart } from './components/ForecastChart';
import { useStore } from './store/useStore';

function App() {
  const connectionStatus = useStore(state => state.connectionStatus);

  return (
    <div style={{ 
      minHeight: '100vh', 
      backgroundColor: '#0a0a0a', 
      color: '#ffffff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      display: 'flex',
      flexDirection: 'column'
    }}>
      {/* Top Navigation & Ticker */}
      <header style={{ 
        backgroundColor: '#111', 
        borderBottom: '1px solid #333',
        position: 'sticky',
        top: 0,
        zIndex: 100
      }}>
        <div style={{ 
          padding: '15px 20px', 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
            <div style={{ 
              width: '40px', height: '40px', borderRadius: '8px', 
              background: 'linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '24px', boxShadow: '0 4px 12px rgba(76, 175, 80, 0.3)'
            }}>
              ☕
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 'bold', letterSpacing: '-0.5px' }}>CoffeeGPT</h1>
              <div style={{ fontSize: '12px', color: '#888' }}>Production Intelligence Platform</div>
            </div>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '13px', color: '#888' }}>
              {connectionStatus === 'connecting' ? 'Connecting...' : 
               connectionStatus === 'connected' ? 'Live Data Active' : 'Offline Mode'}
            </span>
            <div style={{ 
              width: '10px', height: '10px', borderRadius: '50%', 
              backgroundColor: connectionStatus === 'connected' ? '#4caf50' : 
                             connectionStatus === 'connecting' ? '#ff9800' : '#f44336',
              boxShadow: connectionStatus === 'connected' ? '0 0 8px #4caf50' : 'none'
            }} />
          </div>
        </div>
        
        <ErrorBoundary>
          <LiveTicker />
        </ErrorBoundary>
      </header>

      {/* Main Dashboard Layout */}
      <main style={{ 
        flex: 1, 
        padding: '20px', 
        display: 'grid',
        gridTemplateColumns: '1fr 400px',
        gridTemplateRows: 'auto 1fr',
        gap: '20px',
        maxWidth: '1600px',
        margin: '0 auto',
        width: '100%',
        boxSizing: 'border-box'
      }}>
        
        {/* Left Column: Market Data & Chart */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', gridColumn: '1 / 2', gridRow: '1 / 3' }}>
          <ErrorBoundary>
            <MarketDashboard />
          </ErrorBoundary>
          
          <div style={{ flex: 1, minHeight: '400px' }}>
            <ErrorBoundary>
              <ForecastChart />
            </ErrorBoundary>
          </div>
        </div>

        {/* Right Column Top: Alerts */}
        <div style={{ gridColumn: '2 / 3', gridRow: '1 / 2', height: '350px' }}>
          <ErrorBoundary>
             <AlertFeed />
          </ErrorBoundary>
        </div>

        {/* Right Column Bottom: Chat Assistant */}
        <div style={{ gridColumn: '2 / 3', gridRow: '2 / 3' }}>
          <ErrorBoundary>
             <ChatPanel />
          </ErrorBoundary>
        </div>

      </main>
    </div>
  );
}

export default App;
