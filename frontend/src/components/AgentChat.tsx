import { useState, useRef, useEffect } from 'react';
import { Send, Bot, Loader2, Wrench, X, ChevronDown, ChevronRight, Terminal, Check } from 'lucide-react';
import type { AgentMessage, AgentStep } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

interface AgentChatProps {
  runId: string;
  onClose: () => void;
}

export function AgentChat({ runId, onClose }: AgentChatProps) {
  const [messages, setMessages] = useState<AgentMessage[]>([
    {
      id: 'init',
      role: 'agent',
      content: "Hi! I'm the Anchorpoint Agent. I can help you analyze demand surges, compare regions, or explain site scores. What would you like to know about this run?"
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg: AgentMessage = { id: Date.now().toString(), role: 'user', content: input };
    const agentMsg: AgentMessage = { id: (Date.now() + 1).toString(), role: 'agent', content: '', isStreaming: true, steps: [] };
    
    setMessages(prev => [...prev, userMsg, agentMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const historyPayload = messages
        .filter(m => m.id !== 'init' && m.content)
        .map(m => ({ role: m.role === 'agent' ? 'assistant' : 'user', content: m.content }));

      const response = await fetch(`${API_BASE}/runs/${runId}/agent/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg.content, history: historyPayload }),
      });

      if (!response.body) throw new Error('No body in response');
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            if (!dataStr.trim()) continue;
            
            try {
              const data = JSON.parse(dataStr) as AgentStep;
              
              setMessages(prev => {
                const newMessages = [...prev];
                const lastMsg = newMessages[newMessages.length - 1];
                
                if (data.type === 'answer_chunk') {
                  lastMsg.content += data.content || '';
                } else if (data.type === 'answer') {
                  lastMsg.content = data.content || '';
                  lastMsg.isStreaming = false;
                } else {
                  // It's a step (thinking, tool_call, tool_result)
                  if (!lastMsg.steps) lastMsg.steps = [];
                  lastMsg.steps.push(data);
                }
                
                return newMessages;
              });
            } catch (e) {
              console.error('Failed to parse SSE data', dataStr);
            }
          }
        }
      }
    } catch (e) {
      console.error('Agent chat error:', e);
      setMessages(prev => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        lastMsg.content = "Sorry, I encountered an error while processing your request.";
        lastMsg.isStreaming = false;
        return newMessages;
      });
    } finally {
      setIsLoading(false);
      setMessages(prev => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        lastMsg.isStreaming = false;
        return newMessages;
      });
    }
  };

  const starterPrompts = [
    "What are the top candidate sites?",
    "Did we detect any demand surges?",
    "Why is Region 2 ranked the way it is?",
  ];

  return (
    <div className="agent-chat-drawer fadein">
      <div className="agent-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="agent-avatar"><Bot size={18} /></div>
          <div>
            <div className="agent-title">Anchorpoint Agent</div>
            <div className="agent-sub">Powered by Mireye</div>
          </div>
        </div>
        <button className="agent-close" onClick={onClose}><X size={18} /></button>
      </div>

      <div className="agent-messages">
        {messages.map((m) => (
          <div key={m.id} className={`message-row ${m.role}`}>
            {m.role === 'agent' && (
              <div className="message-avatar"><Bot size={14} /></div>
            )}
            <div className={`message-bubble ${m.role}`}>
              {m.steps && m.steps.length > 0 && (
                <div className="reasoning-trace">
                  {m.steps.map((step, idx) => {
                    const isLastStep = idx === m.steps!.length - 1;
                    const isActiveStep = m.isStreaming && isLastStep;
                    return (
                      <div key={idx} className="trace-step">
                        {step.type === 'thinking' && (
                          <div className="trace-thinking" style={{ color: isActiveStep ? 'var(--blue-text)' : 'var(--green-text)' }}>
                            {isActiveStep ? (
                              <Loader2 size={12} className="spin" style={{ marginRight: 6 }} />
                            ) : (
                              <Check size={12} style={{ marginRight: 6 }} />
                            )}
                            {step.content}
                          </div>
                        )}
                        {step.type === 'tool_call' && (
                          <div className="trace-tool-call">
                            <Wrench size={12} style={{ marginRight: 6 }} />
                            Running <code>{step.tool_name}</code>
                          </div>
                        )}
                        {step.type === 'tool_result' && (
                          <div className="trace-tool-result">
                            <ChevronRight size={12} style={{ marginRight: 6 }} />
                            <span style={{ fontStyle: 'italic', color: 'var(--text-muted)' }}>Received data from {step.tool_name}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {m.content && <div className="message-text">{m.content}</div>}
              {m.isStreaming && !m.content && m.steps && m.steps.length > 0 && (
                <div className="typing-indicator">
                  <span className="dot"></span><span className="dot"></span><span className="dot"></span>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="agent-input-area">
        {messages.length === 1 && (
          <div className="starter-prompts">
            {starterPrompts.map((p, i) => (
              <button key={i} className="starter-btn" onClick={() => setInput(p)}>
                {p}
              </button>
            ))}
          </div>
        )}
        <form className="agent-form" onSubmit={handleSubmit}>
          <input
            type="text"
            className="agent-input"
            placeholder="Ask about this run..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
          />
          <button type="submit" className="agent-send" disabled={!input.trim() || isLoading}>
            <Send size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
