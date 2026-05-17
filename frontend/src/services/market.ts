import { fetchApi } from './api';

export const getPrices = (variety = 'arabica', period = '7d') => 
  fetchApi(`/market/prices?variety=${variety}&period=${period}`);

export const getFutures = () => 
  fetchApi('/market/futures');

export const getExports = (country?: string) => 
  fetchApi(`/market/exports${country ? `?country=${country}` : ''}`);

export const getMarketSummary = () => 
  fetchApi('/market/summary');
