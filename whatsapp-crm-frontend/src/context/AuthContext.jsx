// Filename: src/context/AuthContext.jsx
import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import axios from 'axios'; // Or use your apiCall helper if it's set up for non-authed requests too
import { toast } from 'sonner';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const AUTH_API_URL = `${API_BASE_URL}/crm-api/auth`;

const ACCESS_TOKEN_KEY = 'accessToken';
const REFRESH_TOKEN_KEY = 'refreshToken';
const USER_DATA_KEY = 'user';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

// For handling concurrent token refresh requests
let isCurrentlyRefreshingToken = false;
let tokenRefreshSubscribers = [];

const addTokenRefreshSubscriber = (callback) => {
  tokenRefreshSubscribers.push(callback);
};

const onTokenRefreshed = (newAccessToken) => {
  tokenRefreshSubscribers.forEach(callback => callback(newAccessToken));
  tokenRefreshSubscribers = [];
};

export const AuthProvider = ({ children }) => {
  const [authState, setAuthState] = useState(() => {
    const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    let user = null;
    try {
        user = JSON.parse(localStorage.getItem(USER_DATA_KEY));
    } catch (e) {
        console.warn("Could not parse user data from localStorage");
    }
    return {
      accessToken: accessToken || null,
      refreshToken: refreshToken || null,
      isAuthenticated: !!accessToken,
      user: user || null,
      isLoading: true,
    };
  });

  // REMOVED: const navigate = useNavigate(); // This was the cause of the error

  const setAuthData = useCallback((data) => {
    const newAccessToken = data?.access || null;
    const newRefreshToken = data?.refresh || null;
    // Preserve existing user data if new data doesn't explicitly provide it
    const newUser = data?.user !== undefined ? data.user : authState.user;

    setAuthState({
      accessToken: newAccessToken,
      refreshToken: newRefreshToken,
      isAuthenticated: !!newAccessToken,
      user: newUser,
      isLoading: false,
    });

    if (newAccessToken) localStorage.setItem(ACCESS_TOKEN_KEY, newAccessToken);
    else localStorage.removeItem(ACCESS_TOKEN_KEY);

    if (newRefreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, newRefreshToken);
    else localStorage.removeItem(REFRESH_TOKEN_KEY);
    
    if (newUser) localStorage.setItem(USER_DATA_KEY, JSON.stringify(newUser));
    else localStorage.removeItem(USER_DATA_KEY);
  }, [authState.user]); // Include authState.user to correctly use its value in closure

  const logoutUser = useCallback(async (informBackend = true) => {
    console.log("AuthProvider: logoutUser called");
    const currentRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    
    setAuthData({ access: null, refresh: null, user: null }); // Clears tokens & sets isAuthenticated: false, isLoading: false

    if (informBackend && currentRefreshToken) {
      try {
        await axios.post(`${AUTH_API_URL}/token/blacklist/`, {
          refresh: currentRefreshToken,
        });
        toast.info("Session ended on server.");
      } catch (error) {
        console.warn("Failed to blacklist token on server:", error.response?.data || error.message);
      }
    }
    // Navigation will be handled by ProtectedRoute or the calling component.
  }, [setAuthData]);

  const refreshTokenInternal = useCallback(async () => {
    const currentRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!currentRefreshToken) {
      console.log("AuthProvider: No refresh token, calling logoutUser.");
      await logoutUser(false);
      throw new Error("No refresh token available."); // Propagate error
    }

    try {
      console.log("AuthProvider: Attempting token refresh...");
      const response = await axios.post(`${AUTH_API_URL}/token/refresh/`, {
        refresh: currentRefreshToken,
      });
      const { access, refresh: newRotatedRefreshToken } = response.data;

      if (access) {
        const newAuthData = { 
          access, 
          refresh: newRotatedRefreshToken || currentRefreshToken,
          user: authState.user // Preserve current user data during refresh
        };
        setAuthData(newAuthData);
        console.log("AuthProvider: Token refreshed successfully.");
        return access;
      }
      throw new Error("Token refresh failed: No new access token received.");
    } catch (error) {
      console.error("AuthProvider: Token refresh error, logging out:", error.response?.data || error.message);
      await logoutUser(true); // Logout on critical refresh failure
      throw new Error(error.response?.data?.detail || "Session fully expired. Please log in again.");
    }
  }, [logoutUser, setAuthData, authState.user]);

  const getRefreshedAccessToken = useCallback(async () => {
    if (!isCurrentlyRefreshingToken) {
      isCurrentlyRefreshingToken = true;
      try {
        const newAccessToken = await refreshTokenInternal();
        onTokenRefreshed(newAccessToken);
        return newAccessToken;
      } catch (error) {
        onTokenRefreshed(null);
        throw error;
      } finally {
        isCurrentlyRefreshingToken = false;
      }
    } else {
      return new Promise((resolve, reject) => {
        addTokenRefreshSubscriber((newAccessToken) => {
          if (newAccessToken) resolve(newAccessToken);
          else reject(new Error("Token refresh failed during queued request."));
        });
      });
    }
  }, [refreshTokenInternal]);

  useEffect(() => {
    const initializeAuth = async () => {
      console.log("AuthProvider: Initializing authentication...");
      const token = localStorage.getItem(ACCESS_TOKEN_KEY);
      if (token) {
        // For more robustness, you could attempt to verify the token here:
        // try {
        //   await axios.post(`${AUTH_API_URL}/token/verify/`, { token });
        //   setAuthState(prev => ({ ...prev, isAuthenticated: true, isLoading: false }));
        //   console.log("AuthProvider: Initial token verified.");
        // } catch (error) {
        //   console.warn("AuthProvider: Initial token verification failed. Attempting refresh or logging out.");
        //   try {
        //      await getRefreshedAccessToken(); // This will update state via setAuthData
        //      // isLoading will be set to false within setAuthData called by getRefreshedAccessToken
        //   } catch (refreshError) {
        //      // getRefreshedAccessToken calls logout, which calls setAuthData (isLoading: false)
        //      console.error("AuthProvider: Initial refresh failed during init.", refreshError)
        //   }
        // }
        // Simplified version: Assume token is valid if present, apiCall will handle refresh if needed.
        setAuthState(prev => ({ ...prev, isAuthenticated: true, isLoading: false }));
      } else {
        setAuthState(prev => ({ ...prev, isAuthenticated: false, isLoading: false }));
        console.log("AuthProvider: No initial token found.");
      }
    };
    initializeAuth();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run only once

  const loginUser = async (username, password) => {
    setAuthState(prev => ({ ...prev, isLoading: true }));
    try {
      const response = await axios.post(`${AUTH_API_URL}/token/`, { username, password });
      // Assuming backend might return basic user info like { username, email, id } with tokens
      const userData = response.data.user || { username }; // Adjust based on actual response
      setAuthData({ ...response.data, user: userData }); // Sets isLoading: false
      toast.success("Login successful!");
      return { success: true, user: userData }; // Return success for LoginPage to handle navigation
    } catch (error) {
      console.error("Login failed:", error.response ? error.response.data : error.message);
      setAuthData({ access: null, refresh: null, user: null }); // Sets isLoading: false
      const errorMsg = error.response?.data?.detail || "Login failed. Please check credentials.";
      toast.error(errorMsg);
      return { success: false, error: errorMsg };
    }
    // No finally here, setAuthData in both try/catch handles isLoading:false
  };

  const value = {
    accessToken: authState.accessToken,
    user: authState.user,
    isAuthenticated: authState.isAuthenticated,
    isLoadingAuth: authState.isLoading, // Use this in ProtectedRoute
    login: loginUser,
    logout: logoutUser,
    getRefreshedAccessToken, // For apiCall to use
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};