import { create } from 'zustand';

interface AppState {
  sessionId: string;
  connectionStatus: 'connected' | 'disconnected' | 'connecting';
  alertCount: number;
  setConnectionStatus: (status: 'connected' | 'disconnected' | 'connecting') => void;
  incrementAlertCount: () => void;
  resetAlertCount: () => void;
}

export const useStore = create<AppState>((set) => ({
  sessionId: Math.random().toString(36).substring(7),
  connectionStatus: 'disconnected',
  alertCount: 0,
  setConnectionStatus: (status) => set({ connectionStatus: status }),
  incrementAlertCount: () => set((state) => ({ alertCount: state.alertCount + 1 })),
  resetAlertCount: () => set({ alertCount: 0 }),
}));
