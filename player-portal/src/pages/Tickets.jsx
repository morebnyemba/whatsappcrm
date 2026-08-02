import React, { useEffect, useState } from 'react';
import { fetchTickets } from '../api';

const fmt = (n) => Number(n ?? 0).toFixed(2);
const STATUS = {
  PENDING: 'badge yellow', PLACED: 'badge blue', WON: 'badge green',
  LOST: 'badge red', REFUNDED: 'badge gray', PARTIAL_WIN: 'badge green',
};

export default function Tickets() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    fetchTickets()
      .then((t) => active && setTickets(t))
      .catch(() => active && setError('Could not load your bets.'))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  return (
    <div>
      <h1>My Bets</h1>
      {loading && <p className="muted">Loading…</p>}
      {error && <p className="err">{error}</p>}
      {!loading && !error && tickets.length === 0 && <p className="muted">You have no bets yet.</p>}
      <div className="cards">
        {tickets.map((t) => (
          <div className="card" key={t.id}>
            <div className="row">
              <div className="card-title">Ticket #{t.id}</div>
              <span className={STATUS[t.status] || 'badge gray'}>{t.status_display || t.status}</span>
            </div>
            <div className="muted small">{new Date(t.created_at).toLocaleString()} · {t.bet_type_display || t.bet_type}</div>
            <div className="legs">
              {(t.bets ?? []).map((b) => (
                <div className="leg" key={b.id}>
                  <span className="muted">{b.fixture} — {b.outcome}</span>
                  <b>{Number(b.odds).toFixed(2)}</b>
                </div>
              ))}
            </div>
            <div className="kv"><span>Stake</span><b>${fmt(t.total_stake)}</b></div>
            <div className="kv"><span>Potential</span><b className="green-text">${fmt(t.potential_winnings)}</b></div>
            <div className="kv"><span>Odds</span><b>{Number(t.total_odds).toFixed(2)}</b></div>
          </div>
        ))}
      </div>
    </div>
  );
}
