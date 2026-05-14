import React from 'react';

interface LoadingSkeletonProps {
  type?: 'card' | 'list' | 'text' | 'chart';
  count?: number;
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({ type = 'text', count = 1 }) => {
  const renderSkeleton = (key: number) => {
    switch (type) {
      case 'card':
        return (
          <div key={key} style={{ padding: '20px', borderRadius: '8px', backgroundColor: '#222', marginBottom: '10px', animation: 'pulse 1.5s infinite' }}>
            <div style={{ height: '24px', width: '50%', backgroundColor: '#333', borderRadius: '4px', marginBottom: '16px' }} />
            <div style={{ height: '40px', width: '100%', backgroundColor: '#333', borderRadius: '4px' }} />
          </div>
        );
      case 'chart':
        return (
          <div key={key} style={{ height: '300px', width: '100%', backgroundColor: '#222', borderRadius: '8px', animation: 'pulse 1.5s infinite', display: 'flex', alignItems: 'flex-end', padding: '20px', gap: '10px' }}>
             {[...Array(10)].map((_, i) => (
                <div key={i} style={{ flex: 1, backgroundColor: '#333', borderRadius: '4px 4px 0 0', height: `${Math.max(20, Math.random() * 100)}%` }} />
             ))}
          </div>
        );
      case 'list':
        return (
          <div key={key} style={{ display: 'flex', gap: '15px', padding: '15px', backgroundColor: '#222', borderRadius: '8px', marginBottom: '10px', animation: 'pulse 1.5s infinite' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#333' }} />
            <div style={{ flex: 1 }}>
              <div style={{ height: '16px', width: '70%', backgroundColor: '#333', borderRadius: '4px', marginBottom: '8px' }} />
              <div style={{ height: '12px', width: '40%', backgroundColor: '#333', borderRadius: '4px' }} />
            </div>
          </div>
        );
      case 'text':
      default:
        return (
          <div key={key} style={{ height: '16px', width: '100%', backgroundColor: '#333', borderRadius: '4px', marginBottom: '10px', animation: 'pulse 1.5s infinite' }} />
        );
    }
  };

  return (
    <>
      <style>
        {`
          @keyframes pulse {
            0% { opacity: 0.6; }
            50% { opacity: 1; }
            100% { opacity: 0.6; }
          }
        `}
      </style>
      <div style={{ width: '100%' }}>
        {[...Array(count)].map((_, i) => renderSkeleton(i))}
      </div>
    </>
  );
};
