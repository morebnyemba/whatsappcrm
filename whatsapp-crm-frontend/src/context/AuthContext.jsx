// src/context/AuthContext.jsx
import React, { createContext, useState, useEffect, useContext, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { toast } from 'sonner';
import apiClient from '../services/api'; // Your centralized Axios instance
import * as authService from '../services/auth'; // Your authentication service functions

const AuthContext = createContext(null);

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (context === null) {
        // This error means AuthProvider is not wrapping the component calling useAuth,
        // or AuthProvider itself is not correctly within the Router context if this error
        // still points to useNavigate/useLocation calls within AuthProvider.
        throw new Error("useAuth must be used within an AuthProvider, and AuthProvider must be within a Router context.");
    }
    return context;
};

export const AuthProvider = ({ children }) => {
    const initialAuthState = authService.checkInitialAuth(); // Get initial state from localStorage

    const [user, setUser] = useState(initialAuthState.user);
    const [accessToken, setAccessToken] = useState(initialAuthState.token);
    const [refreshTokenLocal, setRefreshTokenLocal] = useState(initialAuthState.refreshToken);
    const [isLoadingAuth, setIsLoadingAuth] = useState(true); // True until initial bootstrap is done

    const navigate = useNavigate(); // These hooks need AuthProvider to be inside a Router
    const location = useLocation();

    // Centralized logout logic for use within this context
    const performLogout = useCallback((options = { navigate: true, showToast: true }) => {
        console.log("AuthContext: Performing logout action.");
        authService.logoutUser(); // Clears localStorage
        setUser(null);
        setAccessToken(null);
        setRefreshTokenLocal(null);
        setIsLoadingAuth(false); // No longer loading if we explicitly log out
        if (options.showToast) {
            toast.info("You have been successfully logged out.");
        }
        if (options.navigate && location.pathname !== '/login') {
            navigate('/login', { state: { from: location }, replace: true });
        }
    }, [navigate, location]);

    // Effect to set up Axios response interceptor for token refresh
    useEffect(() => {
        const responseInterceptor = apiClient.interceptors.response.use(
            response => response,
            async (error) => {
                const originalRequest = error.config;
                // Only attempt refresh if we have a refresh token and it's a 401 and not already a retry
                if (error.response?.status === 401 && authService.getRefreshToken() && !originalRequest._retry) {
                    originalRequest._retry = true;
                    console.log("AuthContext: 401 detected, attempting token refresh.");
                    try {
                        const newAccessToken = await authService.refreshToken(); // This handles localStorage update for accessToken
                        setAccessToken(newAccessToken); // Update context state
                        
                        // Update the header for the original retried request
                        originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`;
                        
                        console.log("AuthContext: Token refreshed successfully. Retrying original request.");
                        return apiClient(originalRequest); // Retry the original request
                    } catch (refreshError) {
                        console.error("AuthContext: Token refresh failed decisively. Logging out.", refreshError);
                        // authService.refreshToken() already toasts and calls logoutUser (which clears storage)
                        // So, here we just need to update context state and navigate.
                        setUser(null);
                        setAccessToken(null);
                        setRefreshTokenLocal(null);
                        setIsLoadingAuth(false);
                        if (location.pathname !== '/login') {
                             navigate('/login', { state: { from: location }, replace: true });
                        }
                        return Promise.reject(refreshError); // Propagate error from refresh failure
                    }
                }
                // If not a 401 that we can handle with refresh, or already retried, reject.
                // General error toasting is handled by the apiClient's own basic response interceptor.
                return Promise.reject(error);
            }
        );

        return () => {
            apiClient.interceptors.response.eject(responseInterceptor);
        };
    }, [performLogout, location, navigate]); // performLogout is stable if its deps are stable

    // Login function
    const login = useCallback(async (identifier, password) => {
        setIsLoadingAuth(true);
        try {
            const data = await authService.loginUser(identifier, password); // This calls backend & handles localStorage
            setUser(data.user);
            setAccessToken(data.access);
            setRefreshTokenLocal(data.refresh);
            // authService.loginUser already toasts success
            
            const from = location.state?.from?.pathname || '/dashboard';
            navigate(from, { replace: true });
            setIsLoadingAuth(false);
            return { success: true, user: data.user };
        } catch (error) {
            // Error is already toasted by authService.loginUser
            // Ensure state is reset if login fails catastrophically or after multiple attempts
            // For a single credential failure, we might not want to fully logout here,
            // but authService.loginUser doesn't clear tokens on its own.
            setUser(null); // Clear user/token state on login fail
            setAccessToken(null);
            setRefreshTokenLocal(null);
            setIsLoadingAuth(false);
            return { success: false, error: error.message };
        }
    }, [navigate, location.state]);

    // Initial authentication check on component mount
    useEffect(() => {
        const bootstrapAuth = async () => {
            setIsLoadingAuth(true); // Explicitly set loading true at start of bootstrap
            const authStatus = authService.checkInitialAuth(); // Checks localStorage

            if (authStatus.isAuthenticated && authStatus.token) {
                setUser(authStatus.user); // User from storage might be stale or just basic
                setAccessToken(authStatus.token);
                setRefreshTokenLocal(authStatus.refreshToken);
                // Try to fetch fresh user profile to verify token and get latest data
                try {
                    console.log("AuthContext Bootstrap: Token found, fetching user profile.");
                    const fetchedUser = await authService.fetchUserProfile(authStatus.token);
                    if (fetchedUser) {
                        setUser(fetchedUser); // Update with fresh user data
                    } else {
                        // Token might be invalid if user fetch returns null without error (depends on fetchUserProfile)
                        console.log("AuthContext Bootstrap: User profile not fetched, logging out.");
                        performLogout({ navigate: false, showToast: false }); // Logout without navigating if already on public page
                    }
                } catch (error) {
                    // fetchUserProfile will throw on 401; interceptor will try to refresh.
                    // If refresh fails, interceptor calls performLogout.
                    // If error is not 401, or if refresh succeeds but subsequent /me/ fails again (should not happen ideally)
                    console.error("AuthContext Bootstrap: Error fetching user profile. Logging out.", error);
                    performLogout({ navigate: false, showToast: false });
                }
            }
            setIsLoadingAuth(false);
        };
        bootstrapAuth();
    }, [performLogout]); // performLogout is stable due to its own useCallback

    const contextValue = {
        user,
        accessToken,
        refreshToken: refreshTokenLocal,
        isAuthenticated: !!accessToken, // Derived state
        isLoadingAuth, // Renamed from isLoading for clarity
        login,
        logout: performLogout, // Expose the memoized logout
    };

    return (
        <AuthContext.Provider value={contextValue}>
            {children}
        </AuthContext.Provider>
    );
};