// src/main.jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
import { Toaster } from 'sonner'; // Corrected import from your file

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App /> {/* App component now solely manages RouterProvider and AuthProvider nesting */}
    <Toaster position="top-right" richColors /> {/* Corrected from your file */}
  </React.StrictMode>,
);