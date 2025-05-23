// Filename: src/context/AuthContext.jsx
import React, { createContext, useState, useContext, useEffect } from 'react';
import axios from 'axios'; // Or use fetch

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const AuthContext = createContext(null);

export const useAuth = () => {
  return useContext(AuthContext);
};

export const AuthProvider = ({ children }) => {
  const [authState, setAuthState] = useState({
    accessToken: localStorage.getItem('accessToken') || null,
    refreshToken: localStorage.getItem('refreshToken') || null,
    isAuthenticated: !!localStorage.getItem('accessToken'), // True if accessToken exists
    user: JSON.parse(localStorage.getItem('user')) || null, // Optional: store user details
    isLoading: true, // To check initial auth status
  });

  // Function to set auth data in state and localStorage
  const setAuthData = (data) => {
    const newAuthState = {
      accessToken: data.access || null,
      refreshToken: data.refresh || null,
      isAuthenticated: !!data.access,
      user: data.user || null, // Assuming backend might return user details with token
      isLoading: false,
    };
    setAuthState(newAuthState);
    if (data.access) localStorage.setItem('accessToken', data.access);
    else localStorage.removeItem('accessToken');

    if (data.refresh) localStorage.setItem('refreshToken', data.refresh);
    else localStorage.removeItem('refreshToken');
    
    if (data.user) localStorage.setItem('user', JSON.stringify(data.user));
    else localStorage.removeItem('user');
  };

  // Check initial auth status (e.g., if token is still valid)
  useEffect(() => {
    const verifyToken = async () => {
      if (authState.accessToken) {
        try {
          // Optional: Verify token with backend on app load
          // This is good practice but adds an API call on startup.
          // await axios.post(`${API_BASE_URL}/crm-api/auth/token/verify/`, { token: authState.accessToken });
          // If verification is successful, keep current state (already set from localStorage)
          setAuthState(prev => ({ ...prev, isLoading: false }));
        } catch (error) {
          console.warn("Token verification failed or token expired, logging out.");
          // If token is invalid/expired, try to refresh or logout
          // For simplicity, just logout here. Implement refresh logic if needed.
          logout(); // This will clear tokens and set isLoading to false
        }
      } else {
        setAuthState(prev => ({ ...prev, isLoading: false }));
      }
    };
    verifyToken();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run only once on mount


  const login = async (username, password) => {
    try {
      const response = await axios.post(`${API_BASE_URL}/crm-api/auth/token/`, {
        username,
        password,
      });
      // Assuming your backend returns { access: '...', refresh: '...', user: {...} }
      // Adjust if your backend returns user details on a separate endpoint after login
      setAuthData({ ...response.data, user: { username } /* Or fetch user details */ });
      return true; // Indicate login success
    } catch (error) {
      console.error("Login failed:", error.response ? error.response.data : error.message);
      setAuthData({ access: null, refresh: null, user: null }); // Clear any partial auth state
      throw error; // Re-throw for the login page to handle
    }
  };

  const logout = () => {
    // TODO: Optionally call a backend endpoint to blacklist the refresh token if your backend supports it
    // await axios.post(`${API_BASE_URL}/crm-api/auth/logout/`, { refresh: authState.refreshToken });
    setAuthData({ access: null, refresh: null, user: null });
    // Navigate to login page (handled by ProtectedRoute or App.jsx)
  };

  // TODO: Implement refreshToken function
  // const refreshToken = async () => { ... };

  const value = {
    ...authState,
    login,
    logout,
    // refreshToken, // Add if implemented
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
