// src/services/api.js
import axios from 'axios';
import { toast } from 'sonner';

// Function to get the auth token directly from localStorage.
// This avoids circular dependency issues if auth.js also needs to import apiClient.
const getAuthToken = () => localStorage.getItem('accessToken');

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const apiClient = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request Interceptor: To add the Auth Token to every outgoing request
apiClient.interceptors.request.use(
    (config) => {
        const token = getAuthToken();
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }
        return config;
    },
    (error) => {
        // This will likely be a network error or an error before the request is sent
        toast.error(error.message || 'Error setting up API request.');
        return Promise.reject(error);
    }
);

// Basic Response Interceptor for general error logging.
// AuthContext.jsx will add a more specific response interceptor for 401/token refresh.
// This one can handle other types of errors or act as a fallback.
apiClient.interceptors.response.use(
  (response) => response, // Simply return successful responses
  (error) => {
    // Check if AuthContext's interceptor has already handled and marked this error
    if (error.config && error.config._isRetryAttempt) {
        // If AuthContext's interceptor marked it as a retry, it's being handled there.
        // Or if the refresh attempt itself failed, AuthContext would have shown a toast.
        return Promise.reject(error);
    }
    
    let errorMessage = 'An unexpected API error occurred.';
    if (error.response) {
        // The request was made and the server responded with a status code
        // that falls out of the range of 2xx
        const errorData = error.response.data;
        const status = error.response.status;
        
        if (status === 401) {
            // This case should ideally be handled by AuthContext's interceptor for token refresh.
            // If it reaches here, it might be that the refresh mechanism isn't active or also failed.
            errorMessage = errorData?.detail || "Authentication failed or session expired. Please try logging in again.";
        } else if (typeof errorData === 'string') {
            errorMessage = errorData;
        } else if (errorData && errorData.detail) {
            errorMessage = errorData.detail;
        } else if (errorData && typeof errorData === 'object') {
            const messages = Object.entries(errorData)
              .map(([key, value]) => {
                const prettyKey = key.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
                if (Array.isArray(value)) {
                  return `${prettyKey}: ${value.join(', ')}`;
                }
                return `${prettyKey}: ${String(value)}`;
              })
              .join('; ');
            if (messages) errorMessage = messages;
            else errorMessage = `API Error (${status})`;
        } else {
            errorMessage = error.message || `API Error (${status})`;
        }
    } else if (error.request) {
        // The request was made but no response was received
        errorMessage = 'Network error or no response from server. Please check your connection.';
    } else {
        // Something happened in setting up the request that triggered an Error
        errorMessage = error.message || 'Error in request setup.';
    }

    // Avoid duplicate toasts if another part of the system (like AuthContext) already toasted
    // We use a simple check on the error message string.
    if (!error.message || (!error.message.includes("(toasted)") && !error.message.includes("(toasted_auth)"))) {
        toast.error(errorMessage);
        // Augment error message to signify it has been toasted by this general interceptor
        error.message = `${errorMessage} (toasted_api)`;
    }

    return Promise.reject(error);
  }
);

export default apiClient;