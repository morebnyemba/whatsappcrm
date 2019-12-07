// src/services/auth.js
import { toast } from 'sonner';

const API_AUTH_BASE_URL = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/crm-api/auth`; // Base for auth endpoints
const ACCESS_TOKEN_KEY = 'accessToken';
const REFRESH_TOKEN_KEY = 'refreshToken';
const USER_DATA_KEY = 'userData'; // Optional: to store basic user info

let isRefreshing = false;
let refreshSubscribers = []; // Callbacks to execute after token refresh

const storeTokens = (accessToken, refreshToken) => {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
};

const clearTokens = () => {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_DATA_KEY);
};

const storeUserData = (userData) => {
    if (userData) {
        localStorage.setItem(USER_DATA_KEY, JSON.stringify(userData));
    }
};

const getUserData = () => {
    const data = localStorage.getItem(USER_DATA_KEY);
    try {
        return data ? JSON.parse(data) : null;
    } catch (e) {
        return null;
    }
};


async function login(username, password) {
  try {
    const response = await fetch(`${API_AUTH_BASE_URL}/token/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }), // Or 'email' if your backend uses email
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || 'Login failed');
    }
    if (data.access && data.refresh) {
      storeTokens(data.access, data.refresh);
      // Optionally fetch user details here if login response doesn't include them
      // const userData = await fetchUserDetails(data.access); // You'd need to implement this
      // storeUserData(userData);
      toast.success('Login successful!');
      return { success: true, user: { username } /* or full user data */ };
    }
    throw new Error('Login failed: No tokens received.');
  } catch (error) {
    console.error("Login error:", error);
    toast.error(error.message || 'Login failed. Please check your credentials.');
    return { success: false, error: error.message };
  }
}

async function logout(notifyBackend = true) {
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (notifyBackend && refreshToken) {
    try {
      // Optional: Call backend to blacklist the refresh token
      await fetch(`${API_AUTH_BASE_URL}/token/blacklist/`, { // Assuming this endpoint exists and is configured
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: refreshToken }),
      });
      toast.info('Successfully logged out from server.');
    } catch (error) {
      console.warn("Failed to blacklist token on server during logout:", error);
      // Proceed with client-side logout even if blacklist fails
    }
  }
  clearTokens();
  // Important: Trigger UI update/redirect. This is usually handled by AuthContext or router.
  // For example, by dispatching an event or updating context state.
  // window.dispatchEvent(new Event('authChange'));
  console.log("User logged out, tokens cleared.");
}

async function refreshToken() {
  const currentRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!currentRefreshToken) {
    // No refresh token, user needs to log in.
    await logout(false); // Clear any partial tokens
    return Promise.reject(new Error("No refresh token available."));
  }

  try {
    const response = await fetch(`${API_AUTH_BASE_URL}/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: currentRefreshToken }),
    });
    const data = await response.json();
    if (!response.ok) {
      // If refresh fails (e.g., refresh token expired or blacklisted)
      await logout(false); // Logout the user
      throw new Error(data.detail || "Session expired. Please log in again.");
    }
    if (data.access) {
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access);
      // If your backend rotates refresh tokens, update it here:
      // if (data.refresh) { localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh); }
      toast.success("Session refreshed", { duration: 2000 });
      return data.access; // Return new access token
    }
    throw new Error("Token refresh failed: No new access token received.");
  } catch (error) {
    console.error("Token refresh error:", error);
    await logout(false); // Ensure logout on any refresh failure
    throw error; // Re-throw for apiCall to handle
  }
}

const getAccessToken = () => localStorage.getItem(ACCESS_TOKEN_KEY);

const isLoggedIn = () => {
  // Basic check, can be enhanced by decoding token to check expiry
  return !!localStorage.getItem(ACCESS_TOKEN_KEY);
};

// Function to subscribe requests to the token refresh process
const subscribeTokenRefresh = (cb) => {
  refreshSubscribers.push(cb);
};

// Function to notify subscribers after token has been refreshed
const onRefreshed = (token) => {
  refreshSubscribers.forEach(cb => cb(token));
  refreshSubscribers = []; // Clear subscribers
};

export const authService = {
  login,
  logout,
  refreshToken: async () => { // Wrapped refreshToken to handle concurrent requests
    if (!isRefreshing) {
      isRefreshing = true;
      refreshPromise = refreshTokenInternal() // Renamed original refreshToken
        .then(newAccessToken => {
          onRefreshed(newAccessToken);
          return newAccessToken;
        })
        .catch(error => {
          onRefreshed(null); // Notify subscribers of failure
          throw error;
        })
        .finally(() => {
          isRefreshing = false;
          refreshPromise = null;
        });
    }
    return refreshPromise;
  },
  getAccessToken,
  getRefreshToken: () => localStorage.getItem(REFRESH_TOKEN_KEY), // Direct getter
  isLoggedIn,
  storeTokens, // Expose if needed externally, e.g., after social login
  clearTokens,
  storeUserData,
  getUserData,
  // Internal function, wrapped for public use
  refreshTokenInternal: refreshToken 
};

// Rename original refreshToken to avoid name collision
async function refreshTokenInternal() {
  const currentRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!currentRefreshToken) {
    await authService.logout(false);
    return Promise.reject(new Error("No refresh token available."));
  }
  try {
    const response = await fetch(`${API_AUTH_BASE_URL}/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: currentRefreshToken }),
    });
    const data = await response.json();
    if (!response.ok) {
      await authService.logout(false);
      throw new Error(data.detail || "Session expired. Please log in again.");
    }
    if (data.access) {
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access);
      if (data.refresh) { // Handle rotated refresh tokens
        localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh);
      }
      return data.access;
    }
    throw new Error("Token refresh failed: No new access token.");
  } catch (error) {
    await authService.logout(false);
    throw error;
  }
}