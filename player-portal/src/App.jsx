import React from 'react';
import { Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from './auth';
import Login from './pages/Login';
import Matches from './pages/Matches';
import Tickets from './pages/Tickets';
import Wallet from './pages/Wallet';
import Profile from './pages/Profile';
import { IconBall, IconTicket, IconWallet, IconUser, IconLogout } from './icons';

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  return isAuthed ? children : <Navigate to="/login" replace />;
}

function Shell({ children }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const tabs = [
    { to: '/matches', label: 'Matches', Icon: IconBall },
    { to: '/tickets', label: 'Bets', Icon: IconTicket },
    { to: '/wallet', label: 'Wallet', Icon: IconWallet },
    { to: '/profile', label: 'Profile', Icon: IconUser },
  ];
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand-mark">
          <div className="brand-logo" style={{ width: 30, height: 30, borderRadius: 8 }}>
            <IconBall size={16} color="#fff" />
          </div>
          <span className="brand-lg">BetBlitz</span>
        </div>
        <button className="icon-btn" onClick={() => { logout(); navigate('/login'); }}>
          <IconLogout size={15} /> Log out
        </button>
      </header>
      <main className="content">{children}</main>
      <nav className="tabbar">
        {tabs.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} className={({ isActive }) => 'tab' + (isActive ? ' active' : '')}>
            <Icon size={20} />
            <span>{label}</span>
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
