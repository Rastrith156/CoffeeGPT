import { useState, useRef, useEffect } from 'react';
import { T } from '../../styles/theme';
import { AgentReasoning } from './AgentReasoning';
import { LiveDot } from '../shared/LiveDot';
import { streamChat } from '../../services/chat';

const QUICK_PROMPTS = [
  { label: "Frost risk impact", key: "frost" },
  { label: "7-day forecast", key: "forecast" },
  { label: "Supply chain risk", key: "risk" },
  { label: "Market overview", key: "default" },
];

export const ChatPanel = () => {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "**Welcome to CoffeeGPT.**\\n\\nI am connected to live ICE futures data, global weather models, and real-time news feeds. How can I assist you today?", done: true }
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  
  const endRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText, thinking]);

  const handleSubmit = (textStr?: string, key?: string) => {
    const val = textStr || input;
    if (!val.trim() || streaming || thinking) return;
    
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: val, done: true }]);
    setThinking(true);
    setStreaming(false);
    
    // Setup temporary assistant message placeholder
    setMessages(prev => [...prev, { role: "assistant", content: "", done: false }]);
    
    // Connect to real SSE Stream (Task 5)
    streamChat(
      val,
      (chunk: string) => {
        if (thinking) {
          setThinking(false);
          setStreaming(true);
        }
        setStreamText(prev => prev + chunk);
      },
      () => {
        setStreaming(false);
        setThinking(false);
        setMessages(prev => {
          const newM = [...prev];
          newM[newM.length - 1].content = streamText;
          newM[newM.length - 1].done = true;
          return newM;
        });
        setStreamText("");
      },
      (err: any) => {
        setStreaming(false);
        setThinking(false);
        console.error("Chat Stream Error", err);
        setMessages(prev => {
          const newM = [...prev];
          newM[newM.length - 1].content = "*Connection to CoffeeGPT intelligence engine failed.*";
          newM[newM.length - 1].done = true;
          return newM;
        });
        setStreamText("");
      }
    );
  };

  const renderMD = (text: string) => {
    const lines = text.split("\\n");
    return lines.map((line, i) => {
      if (line.startsWith("**") && line.endsWith("**") && line.length > 4) {
        return <div key={i} style={{ fontWeight: 600, color: T.text0, marginBottom: 6, marginTop: i > 0 ? 10 : 0, fontFamily: "'Syne', sans-serif", fontSize: 13, letterSpacing: "0.02em" }}>{line.slice(2, -2)}</div>;
      }
      if (line.startsWith("→ ") || line.startsWith("• ")) {
        const content = line.slice(2);
        const parts = content.split(/\\*\\*(.*?)\\*\\*/g);
        return <div key={i} style={{ display: "flex", gap: 8, marginBottom: 5, color: T.text1, fontSize: 13, lineHeight: 1.6 }}>
          <span style={{ color: T.bronze, flexShrink: 0 }}>{line[0] === "→" ? "→" : "•"}</span>
          <span>{parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: T.amber }}>{p}</strong> : p)}</span>
        </div>;
      }
      if (line === "") return <div key={i} style={{ height: 6 }} />;
      const parts = line.split(/\\*\\*(.*?)\\*\\*/g);
      return <div key={i} style={{ color: T.text1, fontSize: 13, lineHeight: 1.7, marginBottom: 2 }}>
        {parts.map((p, j) => j % 2 === 1 ? <strong key={j} style={{ color: T.text0 }}>{p}</strong> : p)}
      </div>;
    }).filter(Boolean);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: T.bg1 }}>
      {/* Header */}
      <div style={{ padding: "16px 20px", borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <div style={{ width: 32, height: 32, borderRadius: 10, background: `linear-gradient(135deg, ${T.bronze}, ${T.espresso})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>☕</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif", letterSpacing: "0.02em" }}>CoffeeGPT Intelligence</div>
          <div style={{ fontSize: 11, color: T.text2, display: "flex", alignItems: "center", gap: 5 }}><LiveDot size={6} /> <span>AI Active · Streaming</span></div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {thinking && <div style={{ fontSize: 11, color: T.cyan, fontFamily: "'DM Mono', monospace", display: "flex", alignItems: "center", gap: 5 }}>
            <div className="spinning" style={{ width: 12, height: 12, border: `1.5px solid ${T.cyan}`, borderTopColor: "transparent", borderRadius: "50%" }} />
            Reasoning...
          </div>}
          {streaming && !thinking && <div style={{ fontSize: 11, color: T.amber, fontFamily: "'DM Mono', monospace", display: "flex", alignItems: "center", gap: 5 }}>
            <div className="live-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: T.amber }} />
            Streaming
          </div>}
        </div>
      </div>

      {/* Quick prompts */}
      <div style={{ padding: "12px 20px", borderBottom: `1px solid ${T.border}`, display: "flex", gap: 8, flexWrap: "wrap", flexShrink: 0 }}>
        {QUICK_PROMPTS.map(q => (
          <button key={q.key} onClick={() => handleSubmit(q.label, q.key)} disabled={streaming || thinking}
            style={{ fontSize: 11, padding: "5px 12px", borderRadius: 20, border: `1px solid ${T.border}`, background: T.bg3, color: T.text1, cursor: "pointer", transition: "all 0.2s", fontFamily: "'Inter', sans-serif", opacity: streaming || thinking ? 0.5 : 1 }}>
            {q.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 16 }}>
        {messages.map((msg, idx) => {
          const isLast = idx === messages.length - 1;
          const displayText = (isLast && !msg.done && streaming) ? streamText : msg.content;
          return (
            <div key={idx} className="slide-in" style={{ display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start", gap: 6 }}>
              {msg.role === "assistant" && (
                <div style={{ fontSize: 10, color: T.text2, fontFamily: "'DM Mono', monospace", letterSpacing: "0.1em", display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 16, height: 16, borderRadius: 5, background: `linear-gradient(135deg, ${T.bronze}, ${T.espresso})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8 }}>☕</div>
                  COFFEEGPT · AI INTELLIGENCE
                </div>
              )}
              <div style={{
                maxWidth: "90%", padding: "14px 18px", borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "4px 16px 16px 16px",
                background: msg.role === "user" ? `linear-gradient(135deg, ${T.bronze}22, ${T.amberDim})` : T.bg3,
                border: `1px solid ${msg.role === "user" ? T.bronze + "33" : T.border}`,
                position: "relative"
              }}>
                {msg.role === "assistant" ? renderMD(displayText) : <span style={{ fontSize: 13, color: T.text0, lineHeight: 1.6 }}>{msg.content}</span>}
                {isLast && streaming && msg.role === "assistant" && (
                  <span className="blink" style={{ display: "inline-block", width: 2, height: 14, background: T.cyan, marginLeft: 2, verticalAlign: "text-bottom", animation: "blink 1s step-end infinite" }} />
                )}
              </div>
            </div>
          );
        })}
        {thinking && <AgentReasoning />}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "14px 16px", borderTop: `1px solid ${T.border}`, flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", background: T.bg3, borderRadius: 14, border: `1px solid ${T.border}`, padding: "4px 4px 4px 16px", transition: "border-color 0.2s" }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSubmit()}
            placeholder="Ask about prices, forecasts, weather, supply chain..."
            disabled={streaming || thinking}
            style={{ flex: 1, background: "none", border: "none", color: T.text0, fontSize: 13, fontFamily: "'Inter', sans-serif", padding: "8px 0", caretColor: T.cyan }}
          />
          <button onClick={() => handleSubmit()} disabled={!input.trim() || streaming || thinking}
            style={{ padding: "8px 16px", borderRadius: 10, background: input.trim() && !streaming && !thinking ? `linear-gradient(135deg, ${T.bronze}, ${T.amber})` : T.bg2, color: input.trim() && !streaming && !thinking ? "#000" : T.text2, fontSize: 13, fontWeight: 600, fontFamily: "'Syne', sans-serif", transition: "all 0.2s", cursor: input.trim() && !streaming && !thinking ? "pointer" : "not-allowed", whiteSpace: "nowrap" }}>
            Send ↑
          </button>
        </div>
      </div>
    </div>
  );
};
