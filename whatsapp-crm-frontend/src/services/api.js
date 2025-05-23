// src/services/api.js
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
const getAuthToken = () => localStorage.getItem('accessToken'); // Replace with your actual auth context/store logic

export async function apiCall(endpoint, method = 'GET', body = null) {
  const token = getAuthToken();
  const headers = {
    ...(token && { 'Authorization': `Bearer ${token}` }),
    ...(!body || !(body instanceof FormData) && { 'Content-Type': 'application/json' }),
  };
  const config = { method, headers, ...(body && { body: (body instanceof FormData) ? body : JSON.stringify(body) }) };

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
    if (!response.ok) {
      let errorData;
      try { errorData = await response.json(); } catch (e) { errorData = { detail: response.statusText || `Request failed: ${response.status}` }; }
      const errorMessage = errorData.detail || (typeof errorData === 'object' && errorData !== null && !errorData.detail ? 
        Object.entries(errorData).map(([k, v]) => `${k}: ${Array.isArray(value) ? value.join(', ') : value}`).join('; ') : 
        `API Error ${response.status}`);
      const err = new Error(errorMessage);
      err.response = response; err.data = errorData;
      throw err;
    }
    if (response.status === 204 || response.headers.get("content-length") === "0") return null;
    return await response.json();
  } catch (error) {
    console.error(`API call to ${method} ${endpoint} failed:`, error);
    throw error; // Re-throw for the caller to handle
  }
}