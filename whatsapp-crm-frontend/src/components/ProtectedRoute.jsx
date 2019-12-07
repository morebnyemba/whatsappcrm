// Filename: src/components/ProtectedRoute.jsx
import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext'; // Ensure path is correct
import { Skeleton } from '@/components/ui/skeleton'; // For loading state
import { FiLoader } from 'react-icons/fi'; // Optional: for a spinner icon

export default function ProtectedRoute({ children }) {
  const auth = useAuth();
  const location = useLocation();

  if (auth.isLoading) {
    // Display a full-page loading indicator while auth status is being checked
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-background dark:bg-slate-900 p-4">
        <FiLoader className="h-12 w-12 animate-spin text-blue-500 dark:text-blue-400 mb-6" />
        <p className="text-lg text-foreground dark:text-slate-300 mb-2">Authenticating...</p>
        <div className="w-full max-w-sm space-y-3">
            <Skeleton className="h-8 w-full rounded-md dark:bg-slate-700" />
            <Skeleton className="h-8 w-3/4 rounded-md dark:bg-slate-700" />
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    // User is not authenticated after loading, redirect to login.
    // Preserve the intended location to redirect back after successful login.
    console.log("ProtectedRoute: Not authenticated, redirecting to login. From:", location.pathname);
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // If authenticated and not loading, render the children.
  // In your App.jsx setup, `children` is typically <DashboardLayout />,
  // which then contains an <Outlet /> for its own nested routes.
  // If ProtectedRoute itself was defining child routes in App.jsx, it would render <Outlet /> here.
  return children;
};