// src/App.jsx
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link } from "react-router-dom";
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';

// Layout and Page Imports
import DashboardLayout from './components/DashboardLayout';
import Dashboard from './pages/Dashboard';
import ApiSettings from './pages/ApiSettings';
import FlowsPage from './pages/FlowsPage';
import FlowEditorPage from './pages/FlowEditorPage';
import MediaLibraryPage from './pages/MediaLibraryPage';
import ContactsPage from './pages/ContactsPage';
import SavedData from './pages/SavedData';
import Conversation from './pages/Conversation';
import LoginPage from './pages/LoginPage';

const NotFoundPage = () => (
  <div className="p-10 text-center">
    <h1 className="text-3xl font-bold text-red-600 dark:text-red-400">404 - Page Not Found</h1>
    <p className="mt-4 text-gray-700 dark:text-gray-300">The page you are looking for does not exist.</p>
    <Link
      to="/dashboard"
      className="mt-6 inline-block px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
    >
      Go to Dashboard
    </Link>
  </div>
);

// This App component now mirrors the structure of your successful "other project"
export default function App() {
  return (
    <BrowserRouter> {/* Top-level BrowserRouter establishes routing context */}
      <AuthProvider> {/* AuthProvider is a child, its hooks (useNavigate, useLocation) will work */}
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          
          {/* Protected Routes */}
          <Route 
            path="/" 
            element={
              <ProtectedRoute>
                <DashboardLayout /> {/* DashboardLayout contains <Outlet /> for nested routes */}
              </ProtectedRoute>
            }
          >
            {/* Children of DashboardLayout (rendered via its <Outlet />) */}
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="api-settings" element={<ApiSettings />} />
            <Route path="flows" element={<FlowsPage />} />
            <Route path="flows/new" element={<FlowEditorPage />} />
            <Route path="flows/edit/:flowId" element={<FlowEditorPage />} />
            <Route path="media-library" element={<MediaLibraryPage />} />
            <Route path="contacts" element={<ContactsPage />} />
            <Route path="saved-data" element={<SavedData />} />
            <Route path="conversation" element={<Conversation />} />
            <Route path="*" element={<NotFoundPage />} /> {/* Catches unhandled routes under "/" */}
          </Route>
          
          {/* A more general catch-all for any other top-level path not defined */}
          <Route path="*" element={<Navigate to="/" replace />} /> 
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}