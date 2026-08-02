import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchSummary } from '../api';
import { useAuth } from '../auth';

const fmt = (n) => Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function Profile() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    fetchSummary()
      .then((s) => active && setSummary(s))
      .catch(() => active && setError('Could not load your summary.'))
      .finally(() => {});
    return () => { active = false; };
  }, []);

  return (
    <div>
      <h1>Profile</h1>
      {error && <p className="err">{error}</p>}
      <div className="cards">
        <div className="stat"><span className="muted small">Balance</span><b>${fmt(summary?.balance)}</b></div>
        <div className="stat"><span className="muted small">Open bets</span><b>{summary?.tickets_open ?? 0}</b></div>
        <div className="stat"><span className="muted small">Bets won</span><b>{summary?.tickets_won ?? 0}</b></div>
        <div className="stat"><span className="muted small">Upcoming matches</span><b>{summary?.upcoming_fixtures ?? 0}</b></div>
      </div>

      <div className="card">
        <div className="card-title">Manage on WhatsApp</div>
        <p className="muted small">
          Deposits, withdrawals, placing bets, limits and self-exclusion are all handled in your
          BetBlitz WhatsApp chat. Reply <b>menu</b> or <b>bet</b> to get started.
        </p>
      </div>

      <button className="btn danger" onClick={() => { logout(); navigate('/login'); }}>Log out</button>
    </div>
  );
}
