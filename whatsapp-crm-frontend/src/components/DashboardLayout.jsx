// Filename: src/components/DashboardLayout.jsx
// Main layout component for the dashboard - Enhanced and Updated Navigation

import React, { useState, useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { Button } from './ui/button'; // Assuming shadcn/ui
import { Skeleton } from './ui/skeleton'; // Assuming shadcn/ui
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from './ui/tooltip'; // Assuming shadcn/ui

import {
  FiSettings,
  FiMessageSquare, // For Conversation
  FiDatabase,     // For Saved Data (if kept)
  FiMenu,
  FiHome,         // For Dashboard
  FiLink,         // Example icon from your header
  FiClock,        // Example icon from your footer
  FiX,
  FiChevronLeft,
  FiChevronRight,
  FiShare2,       // Good for Flows (diagram/connections)
  FiUsers,        // Good for Contacts
  FiImage         // Good for Media Library
} from 'react-icons/fi';

// Updated navigation links
const links = [
  { to: '/dashboard', label: 'Dashboard', icon: <FiHome className="h-5 w-5" /> },
  { to: '/conversation', label: 'Conversations', icon: <FiMessageSquare className="h-5 w-5" /> },
  { to: '/contacts', label: 'Contacts', icon: <FiUsers className="h-5 w-5" /> },
  { to: '/flows', label: 'Flows', icon: <FiShare2 className="h-5 w-5" /> }, // Changed from Bot Builder
  { to: '/media-library', label: 'Media Library', icon: <FiImage className="h-5 w-5" /> },
  { to: '/api-settings', label: 'API Settings', icon: <FiSettings className="h-5 w-5" /> },
  // { to: '/saved-data', label: 'Saved Data', icon: <FiDatabase className="h-5 w-5" /> }, // Uncomment if you use this route
];

// Background Component (no changes needed here, it's for aesthetics)
const DashboardBackground = () => (
  <div className="absolute inset-0 bg-white dark:bg-gray-950 overflow-hidden -z-10">
    <div
      className="absolute inset-0 opacity-[0.06] dark:opacity-[0.04]"
      style={{
        backgroundImage: `repeating-linear-gradient(45deg, #a855f7 0, #a855f7 1px, transparent 0, transparent 50%)`,
        backgroundSize: '12px 12px',
      }}
    />
    <div className="absolute inset-0 bg-gradient-to-br from-white via-white/0 to-white dark:from-gray-950 dark:via-gray-950/0 dark:to-gray-950" />
  </div>
);

export default function DashboardLayout() {
  const [collapsed, setCollapsed] = useState(localStorage.getItem('sidebarCollapsed') === 'true'); // Persist collapse state
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) { // md breakpoint
        setIsMobileMenuOpen(false);
      }
    };
    window.addEventListener('resize', handleResize);
    handleResize();
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Effect to save collapsed state to localStorage
  useEffect(() => {
    localStorage.setItem('sidebarCollapsed', collapsed);
  }, [collapsed]);

  // Close mobile menu on route change
  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location.pathname]);


  return (
    <div className="flex min-h-screen bg-gray-100 dark:bg-slate-900 text-gray-800 dark:text-gray-200">
      {/* Mobile Header */}
      <header className="md:hidden fixed top-0 left-0 right-0 h-16 bg-white dark:bg-slate-800 border-b border-gray-200 dark:border-slate-700 p-4 flex items-center justify-between z-50 shadow-sm">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            className="rounded-md text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-slate-700"
            aria-label={isMobileMenuOpen ? "Close menu" : "Open menu"}
          >
            {isMobileMenuOpen ? <FiX className="h-6 w-6" /> : <FiMenu className="h-6 w-6" />}
          </Button>
          <Link to="/dashboard" className="flex items-center"> {/* Link to dashboard from logo */}
            <span className="font-bold text-xl bg-gradient-to-r from-purple-600 via-pink-500 to-red-500 dark:from-purple-400 dark:via-pink-400 dark:to-red-400 bg-clip-text text-transparent">
              AutoWhatsapp
            </span>
          </Link>
        </div>
        {/* Placeholder for other mobile header items if needed */}
        {/* <div className="flex items-center gap-2">
          <FiLink className="text-gray-400 dark:text-gray-500" />
          <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Status
          </span>
        </div> */}
      </header>

      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm md:hidden z-30"
          onClick={() => setIsMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed md:relative h-screen transition-all duration-300 ease-in-out border-r border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 z-40 shadow-lg md:shadow-none ${
          collapsed ? 'md:w-20' : 'md:w-64'
        } ${
          isMobileMenuOpen
            ? 'translate-x-0 w-64'
            : '-translate-x-full md:translate-x-0'
        }`}
      >
        <div className="p-3 h-full flex flex-col">
          <div className={`flex items-center mb-6 h-10 ${collapsed ? 'justify-center' : 'justify-between'}`}>
            {/* Logo behavior for collapsed/expanded */}
            <Link to="/dashboard" className={`flex items-center gap-2 overflow-hidden transition-opacity duration-300 ${collapsed ? 'w-auto' : 'w-full'}`}>
              {/* Always visible small logo for collapsed state */}
              <img src="https://placehold.co/36x36/A855F7/FFFFFF?text=AW&font=roboto" alt="AW Logo" className={`h-9 w-9 rounded-lg flex-shrink-0`} />
              {/* Text logo for expanded state */}
              {!collapsed && (
                <span className={`font-bold bg-gradient-to-r from-purple-600 via-pink-500 to-red-500 dark:from-purple-400 dark:via-pink-400 dark:to-red-400 bg-clip-text text-transparent text-xl whitespace-nowrap`}>
                  AutoWhatsapp
                </span>
              )}
            </Link>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCollapsed((prev) => !prev)}
              className="rounded-md hidden md:flex text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? <FiChevronRight className="h-5 w-5" /> : <FiChevronLeft className="h-5 w-5" />}
            </Button>
          </div>

          <TooltipProvider delayDuration={100}>
            <nav className="space-y-1.5 flex-1">
              {links.map((link) => {
                // Improved active link detection: exact match for dashboard, startsWith for others
                const isActive = link.to === '/dashboard' ? location.pathname === link.to : location.pathname.startsWith(link.to);
                return (
                  <Tooltip key={link.to}>
                    <TooltipTrigger asChild>
                      <Button
                        variant={isActive ? 'secondary' : 'ghost'}
                        className={`w-full justify-start text-sm font-medium h-10 group rounded-lg ${
                          collapsed ? 'px-0 justify-center' : 'px-3 gap-3'
                        } ${isActive
                            ? 'bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300'
                            : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-700/80'
                          }`}
                        asChild
                      >
                        <Link
                          to={link.to}
                          onClick={() => { if (isMobileMenuOpen) setIsMobileMenuOpen(false); }}
                        >
                          <span className={`flex-shrink-0 h-5 w-5 ${isActive ? 'text-purple-600 dark:text-purple-300' : 'text-gray-500 dark:text-gray-400 group-hover:text-gray-700 dark:group-hover:text-gray-200'}`}>{link.icon}</span>
                          {!collapsed && <span className="truncate">{link.label}</span>}
                        </Link>
                      </Button>
                    </TooltipTrigger>
                    {/* Show tooltip only when sidebar is collapsed */}
                    {collapsed && (
                      <TooltipContent side="right" className="bg-gray-800 dark:bg-slate-900 text-white text-xs rounded-md px-2 py-1 shadow-lg border border-transparent dark:border-slate-700">
                        {link.label}
                      </TooltipContent>
                    )}
                  </Tooltip>
                )
              })}
            </nav>

            <div className="mt-auto pt-4 border-t border-gray-200 dark:border-slate-700">
              <div className={`flex items-center gap-2 p-2 rounded-md ${
                collapsed ? 'justify-center' : 'px-3'
              }`}>
                <FiClock className="text-gray-400 dark:text-gray-500 shrink-0 h-5 w-5" />
                {!collapsed && (
                  <span className="text-xs text-gray-500 dark:text-gray-400 italic">
                    Slyker Tech CRM
                  </span>
                )}
              </div>
            </div>
          </TooltipProvider>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 relative overflow-y-auto mt-16 md:mt-0"> {/* Added relative for DashboardBackground */}
        <DashboardBackground /> {/* Background component */}
        <div className="relative z-10 p-4 sm:p-6 md:p-8"> {/* Content container */}
          <React.Suspense fallback={<LayoutSkeleton />}> {/* For lazy loaded routes */}
            <Outlet />
          </React.Suspense>
        </div>
      </main>
    </div>
  )
}

// Placeholder for a loading skeleton for the main content area
const LayoutSkeleton = () => (
  <div className="space-y-6 p-1">
    <Skeleton className="h-10 w-1/3 rounded-lg bg-gray-200 dark:bg-slate-700" />
    <Skeleton className="h-6 w-2/3 rounded-lg bg-gray-200 dark:bg-slate-700" />
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <Skeleton className="h-64 w-full rounded-xl bg-gray-200 dark:bg-slate-700" />
      <Skeleton className="h-64 w-full rounded-xl hidden md:block bg-gray-200 dark:bg-slate-700" />
    </div>
    <Skeleton className="h-40 w-full rounded-xl bg-gray-200 dark:bg-slate-700" />
  </div>
);