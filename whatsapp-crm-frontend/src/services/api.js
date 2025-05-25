// src/services/api.js
import { authService } from './auth'; // Import your auth service
import { toast } from 'sonner'; // Assuming toast is configured globally

console.log("VITE_API_BASE_URL from env:", import.meta.env.VITE_API_BASE_URL);
console.log("Full import.meta.env object:", import.meta.env);
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'; // Keep this as the absolute base for your backend
console.log("API_BASE_URL being used:", API_BASE_URL);
// To handle concurrent requests during token refresh
let isRefreshingToken = false;
let failedQueue = [];

const processQueue = (error, token = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

export async function apiCall(endpoint, method = 'GET', body = null, isPaginatedFallback = false, attempt = 1) {
  const token = authService.getAccessToken(); // Use authService
  const headers = {
    ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
    ...(token && { 'Authorization': `Bearer ${token}` }),
  };

  const config = { method, headers, ...(body && !(body instanceof FormData) && { body: JSON.stringify(body) }) };

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config); // Ensure endpoint is full path from domain root

    if (!response.ok) {
      let errorData;
      try {
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
          errorData = await response.json();
        } else {
          errorData = { detail: await response.text() || `Request failed: ${response.status}` };
        }
      } catch (e) {
        errorData = { detail: `Request failed: ${response.status}, error parsing response.` };
      }
      
      // Check for 401 Unauthorized and not already retrying or refreshing
      if (response.status === 401 && attempt === 1) { // Only attempt refresh once
        if (!isRefreshingToken) {
          isRefreshingToken = true;
          try {
            const newAccessToken = await authService.refreshTokenInternal(); // Use the internal refresh directly
            processQueue(null, newAccessToken); // Resolve queued requests
            // Retry the original request with the new token
            return apiCall(endpoint, method, body, isPaginatedFallback, 2); // Mark as 2nd attempt
          } catch (refreshError) {
            processQueue(refreshError, null); // Reject queued requests
            // authService.logout() should be called by refreshTokenInternal on failure
            // which should trigger redirect via AuthContext
            toast.error(refreshError.message || "Session expired. Please log in.", {id: "session-expired"});
            throw refreshError; // Throw to indicate failure
          } finally {
            isRefreshingToken = false;
          }
        } else {
          // Token is already being refreshed, queue this request
          return new Promise((resolve, reject) => {
            failedQueue.push({ resolve, reject });
          }).then(newAccessToken => {
            // Retry with new token obtained by the first refresh call
             const newHeaders = { ...headers, Authorization: `Bearer ${newAccessToken}` };
             const newConfig = {...config, headers: newHeaders};
             return fetch(`${API_BASE_URL}${endpoint}`, newConfig).then(async res => {
                 if (!res.ok) throw new Error(await res.text() || `Retry failed: ${res.status}`);
                 if (res.status === 204 || (res.headers.get("content-length") || "0") === "0") return null;
                 return res.json();
             });
          });
        }
      }
      
      // For non-401 errors or if retry already happened
      const errorMessage = errorData.detail || 
                           (typeof errorData === 'object' && errorData !== null && !errorData.detail ? 
                             Object.entries(errorData).map(([k,v])=>`${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(', ') : v}`).join('; ') : 
                             `API Error ${response.status}`);
      const err = new Error(errorMessage); err.data = errorData; err.isApiError = true; throw err;
    }

    // Handle successful response
    if (response.status === 204 || (response.headers.get("content-length") || "0") === "0") {
      return isPaginatedFallback ? { results: [], count: 0 } : null;
    }
    const data = await response.json();
    return isPaginatedFallback ? { results: data.results || (Array.isArray(data) ? data : []), count: data.count || (Array.isArray(data) ? data.length : 0) } : data;

  } catch (error) {
    // Avoid double toasting if error already marked or is auth related handled above
    if (!error.isApiError || (!error.message.includes("(toasted)") && !error.message.includes("Session expired"))) {
        toast.error(error.message || 'An unexpected API error occurred.');
        error.message = (error.message || "") + " (toasted)";
    }
    throw error;
  }
}