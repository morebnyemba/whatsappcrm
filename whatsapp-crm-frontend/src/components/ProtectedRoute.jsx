// Filename: src/components/ProtectedRoute.jsx
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Skeleton } from '@/components/ui/skeleton'; // For loading state

export default function ProtectedRoute({ children }) {
  const auth = useAuth();
  const location = useLocation();

  if (auth.isLoading) {
    // Show a loading indicator while checking auth status
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="w-full max-w-md p-8 space-y-4">
            <Skeleton className="h-12 w-full rounded-md" />
            <Skeleton className="h-8 w-3/4 rounded-md" />
            <Skeleton className="h-8 w-1/2 rounded-md" />
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    // Redirect them to the /login page, but save the current location they were
    // trying to go to when they were redirected. This allows us to send them
    // along to that page after they login, which is a nicer user experience
    // than dropping them off on the home page.
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
};
