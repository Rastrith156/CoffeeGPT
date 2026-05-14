import { useState, useRef, useEffect } from 'react';

function App() {
  const [messages, setMessages] = useState<{role: string, content: string}[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const endOfMessagesRef = useRef<HTMLDivElement>(null);
  const sessionId = useRef(Math.random().toString(36).substring(7));

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }, { role: 'assistant', content: '' }]);
    setIsLoading(true);

    try {
      // Standard EventSource does not support POST, so we use fetch to read the SSE stream
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': 'bypass_dev_key',
        },
        body: JSON.stringify({
          message: userMsg,
          session_id: sessionId.current,
          use_rag: true,
        }),
      });

      if (!response.ok || !response.body) throw new Error(`HTTP error! status: ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantResponse = '';

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
                assistantResponse += data.token;
                setMessages(prev => {
                  const newMsgs = [...prev];
                  newMsgs[newMsgs.length - 1].content = assistantResponse;
                  return newMsgs;
                });
              } else if (data.error) {
                 assistantResponse += `\n[Error: ${data.error}]`;
                 setMessages(prev => {
                  const newMsgs = [...prev];
                  newMsgs[newMsgs.length - 1].content = assistantResponse;
                  return newMsgs;
                });
              }
            } catch (err) {
              console.error("Failed to parse SSE data:", dataStr);
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1].content += '\n[Connection failed]';
        return newMsgs;
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto', padding: '20px', display: 'flex', flexDirection: 'column', height: '100vh', boxSizing: 'border-box' }}>
      <header style={{ paddingBottom: '20px', borderBottom: '1px solid #333' }}>
        <h1 style={{ margin: 0, color: '#e0e0e0' }}>CoffeeGPT Intelligence Platform</h1>
        <p style={{ margin: '5px 0 0 0', color: '#888' }}>Real-time SSE Chat Dashboard</p>
      </header>

      <main style={{ flex: 1, overflowY: 'auto', padding: '20px 0', display: 'flex', flexDirection: 'column', gap: '15px' }}>
        {messages.length === 0 && (
          <div style={{ color: '#888', textAlign: 'center', marginTop: '40px' }}>
            No messages yet. Ask me about coffee prices or weather forecasts!
          </div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '80%', padding: '12px 16px', borderRadius: '8px', backgroundColor: msg.role === 'user' ? '#2e7d32' : '#2a2a2a', whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
            {msg.content}
          </div>
        ))}
        <div ref={endOfMessagesRef} />
      </main>

      <footer style={{ paddingTop: '20px', borderTop: '1px solid #333' }}>
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
            placeholder="Ask a question..."
            style={{ flex: 1, padding: '12px', borderRadius: '4px', border: '1px solid #444', backgroundColor: '#1a1a1a', color: '#fff', fontSize: '16px' }}
          />
          <button type="submit" disabled={isLoading || !input.trim()} style={{ padding: '12px 24px', borderRadius: '4px', border: 'none', backgroundColor: isLoading || !input.trim() ? '#444' : '#2e7d32', color: '#fff', fontSize: '16px', cursor: isLoading || !input.trim() ? 'not-allowed' : 'pointer', fontWeight: 'bold' }}>
            Send
          </button>
        </form>
      </footer>
    </div>
  );
}

export default App;
