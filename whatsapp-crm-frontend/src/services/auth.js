// src/services/auth.js
import axios from 'axios';
import { toast } from 'sonner';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
// Define base URLs for clarity
const CUSTOM_AUTH_TOKEN_URL_BASE = `${API_BASE_URL}/crm-api/auth/token`; // For /token/ and /token/refresh/
const DJOSER_USERS_URL_BASE = `${API_BASE_URL}/crm-api/auth`; // For Djoser's /users/me/

const ACCESS_TOKEN_KEY = 'accessToken';
const REFRESH_TOKEN_KEY = 'refreshToken';
const USER_DATA_KEY = 'user';

export const getAuthToken = () => localStorage.getItem(ACCESS_TOKEN_KEY);
export const getRefreshToken = () => localStorage.getItem(REFRESH_TOKEN_KEY);

const storeTokenData = (access, refresh) => {
    if (access) localStorage.setItem(ACCESS_TOKEN_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
};

const storeUserData = (userData) => {
    if (userData) localStorage.setItem(USER_DATA_KEY, JSON.stringify(userData));
    else localStorage.removeItem(USER_DATA_KEY);
};

const clearAuthStorage = () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_DATA_KEY);
};

const getUserFromStorage = () => {
    try {
        const userStr = localStorage.getItem(USER_DATA_KEY);
        return userStr ? JSON.parse(userStr) : null;
    } catch (e) {
        console.warn("Could not parse user data from localStorage", e);
        localStorage.removeItem(USER_DATA_KEY);
        return null;
    }
};

// Updated to accept username and password directly
export const loginUser = async (username, password) => {
    try {
        const credentials = { username: username, password: password };

        // Log the exact data being sent
        console.log('Credentials being sent to backend:', JSON.stringify(credentials)); 

        const response = await axios.post(`${CUSTOM_AUTH_TOKEN_URL_BASE}/`, credentials);
        const { access, refresh } = response.data;

        if (access && refresh) {
            storeTokenData(access, refresh);

            // Fetch user details using Djoser's /users/me/ endpoint
            const userResponse = await axios.get(`${DJOSER_USERS_URL_BASE}/users/me/`, {
                headers: { Authorization: `Bearer ${access}` }
            });
            storeUserData(userResponse.data);
            toast.success("Login successful!");
            return { success: true, access, refresh, user: userResponse.data };
        } else {
            const errorDetail = response.data?.detail || "Login failed: No access/refresh tokens received.";
            throw new Error(errorDetail);
        }
    } catch (error) {
        const errorData = error.response?.data;
        let errorMsg = "Login failed.";

        if (errorData?.detail) {
            errorMsg = errorData.detail;
        } else if (errorData?.non_field_errors) { // Common for TokenObtainPairView errors
            errorMsg = errorData.non_field_errors.join(' ');
        } else if (errorData && typeof errorData === 'object') {
            // General DRF error formatting
            errorMsg = Object.entries(errorData)
                .map(([key, value]) => {
                    const prettyKey = key.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
                    return `${prettyKey}: ${Array.isArray(value) ? value.join(', ') : String(value)}`;
                })
                .join('; ');
            if (!errorMsg) errorMsg = "Invalid credentials or server error.";
        } else if (error.message) {
            errorMsg = error.message;
        } else {
             errorMsg = "Invalid credentials or unable to connect.";
        }
        
        toast.error(errorMsg);
        throw new Error(errorMsg);
    }
};

export const refreshToken = async () => {
    const currentRefreshToken = getRefreshToken();
    if (!currentRefreshToken) {
        throw new Error("Session ended. No refresh token available.");
    }
    try {
        console.log("auth.js: Attempting token refresh...");
        // Use the endpoint from your urls.py
        const response = await axios.post(`${CUSTOM_AUTH_TOKEN_URL_BASE}/refresh/`, {
            refresh: currentRefreshToken,
        });
        const { access, refresh: newRotatedRefreshToken } = response.data;
        
        if (!access) {
             throw new Error("Token refresh failed: No new access token received.");
        }

        localStorage.setItem(ACCESS_TOKEN_KEY, access);
        if (newRotatedRefreshToken) { 
            localStorage.setItem(REFRESH_TOKEN_KEY, newRotatedRefreshToken);
        }
        console.log("auth.js: Token refreshed successfully.");
        return access; 
    } catch (error) {
        console.error("auth.js: Token refresh error. Logging out.", error.response?.data || error.message);
        clearAuthStorage(); 
        throw new Error(error.response?.data?.detail || "Your session has fully expired. Please log in again.");
    }
};

export const logoutUser = (navigate) => {
    clearAuthStorage();
    toast.info("You have been successfully logged out.");
    if (navigate) {
        navigate('/login', { replace: true });
    }
};

export const fetchUserProfile = async (tokenToUse) => {
    const token = tokenToUse || getAuthToken();
    if (!token) {
        console.log("fetchUserProfile: No auth token available.");
        return null;
    }
    try {
        // Djoser's /users/me/ endpoint
        const response = await axios.get(`${DJOSER_USERS_URL_BASE}/users/me/`, {
             headers: { Authorization: `Bearer ${token}` }
        });
        storeUserData(response.data);
        return response.data;
    } catch (error) {
        console.error("Failed to fetch user profile:", error.response?.data || error.message);
        if (error.response?.status === 401) {
            // Let AuthContext's interceptor handle refresh or logout
        }
        throw error; 
    }
};

export const checkInitialAuth = () => {
    const accessToken = getAuthToken();
    const refreshTokenVal = getRefreshToken();
    const user = getUserFromStorage();

    if (accessToken && user) {
        return { isAuthenticated: true, user, token: accessToken, refreshToken: refreshTokenVal };
    }
    clearAuthStorage();
    return { isAuthenticated: false, user: null, token: null, refreshToken: null };
};