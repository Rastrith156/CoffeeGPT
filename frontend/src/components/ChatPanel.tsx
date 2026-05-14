import React, { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import { LoadingSkeleton } from './LoadingSkeleton';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  intent?: string[];
}

export const ChatPanel: React.FC = () => {
  const sessionId = useStore((state) => state.sessionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const endOfMessagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }]);
    setIsLoading(true);
    
    // Add empty assistant message that will be filled by SSE
    setMessages((prev) => [...prev, { role: 'assistant', content: '', intent: [] }]);

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': 'bypass_dev_key',
        },
        body: JSON.stringify({
          message: userMsg,
          session_id: sessionId,
          use_rag: true,
        }),
      });

      if (!response.ok || !response.body) throw new Error(`HTTP error! status: ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantContent = '';
      let detectedIntents: string[] = [];

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') {
              setIsLoading(false);
              return;
            }
            try {
              const data = JSON.parse(dataStr);
              if (data.token) {
                assistantContent += data.token;
                if (data.intent && data.intent.length > 0 && detectedIntents.length === 0) {
                  detectedIntents = data.intent;
                }
                
                setMessages((prev) => {
                  const newMsgs = [...prev];
                  const lastMsg = newMsgs[newMsgs.length - 1];
                  lastMsg.content = assistantContent;
                  lastMsg.intent = detectedIntents;
                  return newMsgs;
                });
              } else if (data.error) {
                 assistantContent += `\n[Error: ${data.error}]`;
                 setMessages((prev) => {
                  const newMsgs = [...prev];
                  newMsgs[newMsgs.length - 1].content = assistantContent;
                  return newMsgs;
                });
              }
            } catch (err) {
              // Ignore partial JSON chunks that might occur if chunks are split awkwardly
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      setMessages((prev) => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1].content += '\n[Connection failed]';
        return newMsgs;
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: '#1a1a1a', borderRadius: '12px', border: '1px solid #333', overflow: 'hidden' }}>
      <div style={{ padding: '15px 20px', borderBottom: '1px solid #333', backgroundColor: '#222' }}>
        <h2 style={{ margin: 0, fontSize: '16px', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '20px' }}>☕</span> CoffeeGPT Assistant
        </h2>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {messages.length === 0 && (
          <div style={{ margin: 'auto', textAlign: 'center', color: '#666', maxWidth: '300px' }}>
            <p style={{ fontSize: '40px', margin: '0 0 15px 0' }}>👋</p>
            <p>Ask me about current prices, market risks, or weather forecasts in key coffee regions.</p>
          </div>
        )}
        
        {messages.map((msg, idx) => (
          <div key={idx} style={{ 
            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', 
            maxWidth: '85%', 
            display: 'flex',
            flexDirection: 'column',
            gap: '5px'
          }}>
            {msg.role === 'assistant' && msg.intent && msg.intent.length > 0 && msg.intent[0] !== 'general' && (
               <div style={{ fontSize: '11px', color: '#888', textTransform: 'uppercase', display: 'flex', gap: '5px' }}>
                 <span style={{ color: '#4caf50' }}>[ROUTED]</span> {msg.intent.join(', ')}
               </div>
            )}
            <div style={{ 
              padding: '12px 16px', 
              borderRadius: msg.role === 'user' ? '12px 12px 0 12px' : '12px 12px 12px 0', 
              backgroundColor: msg.role === 'user' ? '#2e7d32' : '#2a2a2a', 
              color: '#fff',
              lineHeight: '1.5',
              fontSize: '14px',
              border: msg.role === 'assistant' ? '1px solid #333' : 'none',
              boxShadow: '0 2px 5px rgba(0,0,0,0.2)'
            }}>
              {msg.content || (msg.role === 'assistant' && isLoading ? <LoadingSkeleton type="text" count={2} /> : null)}
            </div>
          </div>
        ))}
        <div ref={endOfMessagesRef} />
      </div>

      <div style={{ padding: '15px', borderTop: '1px solid #333', backgroundColor: '#222' }}>
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
            placeholder="Ask a question..."
            style={{ 
              flex: 1, padding: '12px 15px', borderRadius: '8px', border: '1px solid #444', 
              backgroundColor: '#111', color: '#fff', fontSize: '14px', outline: 'none',
              transition: 'border-color 0.2s'
            }}
            onFocus={(e) => e.target.style.borderColor = '#4caf50'}
            onBlur={(e) => e.target.style.borderColor = '#444'}
          />
          <button 
            type="submit" 
            disabled={isLoading || !input.trim()} 
            style={{ 
              padding: '0 20px', borderRadius: '8px', border: 'none', 
              backgroundColor: isLoading || !input.trim() ? '#333' : '#2e7d32', 
              color: isLoading || !input.trim() ? '#888' : '#fff', 
              fontSize: '14px', cursor: isLoading || !input.trim() ? 'not-allowed' : 'pointer', 
              fontWeight: 'bold', transition: 'background-color 0.2s'
            }}
          >
            {isLoading ? '...' : 'Send'}
          </button>
        </form>
      </div>
    </div>
  );
};
