import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchSummary } from '../api';
import { useAuth } from '../auth';
import { IconWallet, IconTicket, IconTrophy, IconBall, IconAlert, IconLogout } from '../icons';

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

  const stats = [
    { label: 'Balance', value: `$${fmt(summary?.balance)}`, Icon: IconWallet },
    { label: 'Open bets', value: summary?.tickets_open ?? 0, Icon: IconTicket },
    { label: 'Bets won', value: summary?.tickets_won ?? 0, Icon: IconTrophy },
    { label: 'Upcoming matches', value: summary?.upcoming_fixtures ?? 0, Icon: IconBall },
  ];

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Profile</h1>
          <p className="muted small">A quick summary of your account.</p>
        </div>
      </div>

      {error && <div className="top-alert"><IconAlert size={16} /> {error}</div>}

      <div className="cards stats-grid">
        {stats.map(({ label, value, Icon }) => (
          <div className="stat" key={label}>
            <div className="stat-icon"><Icon size={16} /></div>
            <span className="muted small">{label}</span>
            <b>{value}</b>
          </div>
        ))}
      </div>

      <h2>Manage on WhatsApp</h2>
      <div className="card">
        <p className="muted small" style={{ margin: 0 }}>
          Deposits, withdrawals, placing bets, limits and self-exclusion are all handled in your
          BetBlitz WhatsApp chat. Reply <b>menu</b> or <b>bet</b> to get started.
        </p>
      </div>

      <button className="btn danger" onClick={() => { logout(); navigate('/login'); }}>
        <IconLogout size={16} /> Log out
      </button>
    </div>
  );
}
