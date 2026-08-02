import axios from 'axios';

// api.<domain> — set VITE_API_BASE_URL at build time (defaults to local dev).
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const TOKEN_KEY = 'bb_player_access';
export const REFRESH_KEY = 'bb_player_refresh';

export const getAccess = () => localStorage.getItem(TOKEN_KEY);
export const getRefresh = () => localStorage.getItem(REFRESH_KEY);
export const setTokens = (access, refresh) => {
  if (access) localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
};
export const clearTokens = () => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
};

const api = axios.create({ baseURL: BASE_URL, headers: { 'Content-Type': 'application/json' } });

api.interceptors.request.use((config) => {
  const token = getAccess();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On a 401, try a one-shot refresh with the SimpleJWT refresh endpoint.
let refreshing = null;
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry && getRefresh()) {
      original._retry = true;
      try {
        refreshing = refreshing || axios.post(`${BASE_URL}/crm-api/auth/token/refresh/`, { refresh: getRefresh() });
        const { data } = await refreshing;
        refreshing = null;
        setTokens(data.access, null);
        original.headers.Authorization = `Bearer ${data.access}`;
        return api(original);
      } catch (e) {
        refreshing = null;
        clearTokens();
        if (typeof window !== 'undefined') window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  }
);

// --- Auth (WhatsApp OTP) ---
export const requestOtp = (phone) => api.post('/crm-api/auth/player/request-otp/', { phone });
export const verifyOtp = (phone, code) => api.post('/crm-api/auth/player/verify-otp/', { phone, code });

// --- Player data ---
const list = (data) => (Array.isArray(data) ? data : (data?.results ?? []));
export const fetchFixtures = () => api.get('/crm-api/football/fixtures/').then((r) => list(r.data));
export const fetchTickets = () => api.get('/crm-api/football/tickets/').then((r) => list(r.data));
export const fetchWallet = () => api.get('/crm-api/football/wallet/me/').then((r) => r.data);
export const fetchTransactions = () => api.get('/crm-api/football/wallet/transactions/').then((r) => list(r.data));
export const fetchSummary = () => api.get('/crm-api/football/tickets/summary/').then((r) => r.data);

export default api;
