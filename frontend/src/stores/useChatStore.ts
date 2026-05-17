import { create } from 'zustand';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  done: boolean;
}

interface ChatState {
  messages: Message[];
  isStreaming: boolean;
  isThinking: boolean;
  addMessage: (msg: Message) => void;
  updateLastMessage: (content: string, done: boolean) => void;
  setStreaming: (status: boolean) => void;
  setThinking: (status: boolean) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  isThinking: false,
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  updateLastMessage: (content, done) =>
    set((state) => {
      const newMsgs = [...state.messages];
      if (newMsgs.length > 0) {
        newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content, done };
      }
      return { messages: newMsgs };
    }),
  setStreaming: (status) => set({ isStreaming: status }),
  setThinking: (status) => set({ isThinking: status }),
}));
