import { create } from 'zustand';

interface MarketState {
  arabicaPrice: number;
  robustaPrice: number;
  arabicaDir: string | null;
  robustaDir: string | null;
  setArabica: (price: number, dir: string | null) => void;
  setRobusta: (price: number, dir: string | null) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
  arabicaPrice: 223.40,
  robustaPrice: 4105,
  arabicaDir: null,
  robustaDir: null,
  setArabica: (price, dir) => set({ arabicaPrice: price, arabicaDir: dir }),
  setRobusta: (price, dir) => set({ robustaPrice: price, robustaDir: dir }),
}));
