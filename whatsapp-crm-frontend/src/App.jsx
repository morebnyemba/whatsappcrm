// Filename: src/App.jsx
import React from 'react';
import { RouterProvider, createBrowserRouter, Navigate, Link } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext'; // Your AuthProvider
import ProtectedRoute from './components/ProtectedRoute'; // Your ProtectedRoute

import DashboardLayout from './components/DashboardLayout';
import Dashboard from './pages/Dashboard';
import ApiSettings from './pages/ApiSettings';
import FlowsPage from './pages/FlowsPage';
import FlowEditorPage from './pages/FlowEditorPage'; // <--- IMPORT FlowEditorPage
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

const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <DashboardLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },
      { path: 'api-settings', element: <ApiSettings /> },
      
      // Flow Management
      { path: 'flows', element: <FlowsPage /> }, // Page to list all flows
      { path: 'flows/new', element: <FlowEditorPage /> }, // <--- ADDED: Route to create a new flow
      { path: 'flows/edit/:flowId', element: <FlowEditorPage /> }, // <--- ADDED: Route to edit an existing flow
      
      // Other sections
      { path: 'media-library', element: <MediaLibraryPage /> },
      { path: 'contacts', element: <ContactsPage /> },
      
      { path: 'saved-data', element: <SavedData /> },
      { path: 'conversation', element: <Conversation /> },
      { path: '*', element: <NotFoundPage /> } // Catch-all for paths under DashboardLayout
    ]
  },
  { path: '*', element: <Navigate to="/" replace /> } // General catch-all for any other path
]);

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}