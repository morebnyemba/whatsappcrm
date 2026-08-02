import React from 'react';
import { Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from './auth';
import Login from './pages/Login';
import Matches from './pages/Matches';
import Tickets from './pages/Tickets';
import Wallet from './pages/Wallet';
import Profile from './pages/Profile';

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  return isAuthed ? children : <Navigate to="/login" replace />;
}

function Shell({ children }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const tabs = [
    { to: '/matches', label: 'Matches', icon: '⚽' },
    { to: '/tickets', label: 'Bets', icon: '🎫' },
    { to: '/wallet', label: 'Wallet', icon: '💰' },
    { to: '/profile', label: 'Profile', icon: '👤' },
  ];
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">BetBlitz</span>
        <button className="link" onClick={() => { logout(); navigate('/login'); }}>Log out</button>
      </header>
      <main className="content">{children}</main>
      <nav className="tabbar">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => 'tab' + (isActive ? ' active' : '')}>
            <span className="tab-icon">{t.icon}</span>
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/matches" element={<RequireAuth><Shell><Matches /></Shell></RequireAuth>} />
      <Route path="/tickets" element={<RequireAuth><Shell><Tickets /></Shell></RequireAuth>} />
      <Route path="/wallet" element={<RequireAuth><Shell><Wallet /></Shell></RequireAuth>} />
      <Route path="/profile" element={<RequireAuth><Shell><Profile /></Shell></RequireAuth>} />
      <Route path="*" element={<Navigate to="/matches" replace />} />
    </Routes>
  );
}
