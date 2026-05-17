const API_BASE_URL = 'http://localhost:8000/api/v1';

export const fetchWithAuth = async (endpoint: string, options: RequestInit = {}) => {
  // In a real app, you'd get the token from a Zustand store or localStorage
  const token = localStorage.getItem('access_token');
  
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401) {
      // Handle unauthorized (e.g., clear token, redirect to login)
      localStorage.removeItem('access_token');
      window.dispatchEvent(new Event('auth:unauthorized'));
    }
    throw new Error(`API error: ${response.statusText}`);
  }

  return response.json();
};

// Market Service
export const getMarketPrices = async () => {
  return fetchWithAuth('/live/market');
};

export const getForecast = async (symbol: string) => {
  return fetchWithAuth(`/live/forecast/${symbol}`);
};

// Weather Service
export const getWeather = async (region: string) => {
  return fetchWithAuth(`/live/weather?region=${encodeURIComponent(region)}`);
};

// Auth Service
export const login = async (apiKey: string) => {
  const response = await fetch(`${API_BASE_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
  
  if (!response.ok) {
    throw new Error('Authentication failed');
  }
  
  const data = await response.json();
  localStorage.setItem('access_token', data.access_token);
  return data;
};
