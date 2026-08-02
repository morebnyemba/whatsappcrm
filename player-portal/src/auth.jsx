import React, { createContext, useContext, useState, useCallback } from 'react';
import { getAccess, setTokens, clearTokens, requestOtp, verifyOtp } from './api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [isAuthed, setIsAuthed] = useState(!!getAccess());

  const sendCode = useCallback((phone) => requestOtp(phone), []);

  const confirmCode = useCallback(async (phone, code) => {
    const { data } = await verifyOtp(phone, code);
    setTokens(data.access, data.refresh);
    setIsAuthed(true);
    return data;
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setIsAuthed(false);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthed, sendCode, confirmCode, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
