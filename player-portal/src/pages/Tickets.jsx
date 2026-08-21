import React, { useEffect, useState } from 'react';
import { fetchTickets } from '../api';
import { IconTicket, IconAlert } from '../icons';

const fmt = (n) => Number(n ?? 0).toFixed(2);
const STATUS = {
  PENDING: 'badge yellow', PLACED: 'badge blue', WON: 'badge green',
  LOST: 'badge red', REFUNDED: 'badge gray', PARTIAL_WIN: 'badge green',
};

function SkeletonCards() {
  return (
    <div className="cards">
      {[0, 1, 2].map((i) => <div className="skeleton skel-card" key={i} />)}
    </div>
  );
}

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
      <div className="page-head">
        <div>
          <h1>My Bets</h1>
          <p className="muted small">Every ticket you've placed, with live status.</p>
        </div>
      </div>

      {error && <div className="top-alert"><IconAlert size={16} /> {error}</div>}
      {loading && <SkeletonCards />}

      {!loading && !error && tickets.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon"><IconTicket size={26} /></div>
          <strong>You have no bets yet</strong>
          <span className="small">Reply <b>bet</b> on WhatsApp to place your first ticket.</span>
        </div>
      )}

      <div className="cards">
        {tickets.map((t) => (
          <div className="card" key={t.id}>
            <div className="row">
              <div className="card-title">Ticket #{t.id}</div>
              <span className={STATUS[t.status] || 'badge gray'}>
                <span className="badge-dot" />{t.status_display || t.status}
              </span>
            </div>
            <div className="muted small" style={{ marginTop: 2 }}>
              {new Date(t.created_at).toLocaleString()} · {t.bet_type_display || t.bet_type}
            </div>
            <hr className="divider" />
            <div className="legs">
              {(t.bets ?? []).map((b) => (
                <div className="leg" key={b.id}>
                  <span className="muted">{b.fixture} — {b.outcome}</span>
                  <b>{Number(b.odds).toFixed(2)}</b>
                </div>
              ))}
            </div>
            <div className="kv"><span>Stake</span><b>${fmt(t.total_stake)}</b></div>
            <div className="kv"><span>Combined odds</span><b>{Number(t.total_odds).toFixed(2)}</b></div>
            <div className="kv"><span>Potential payout</span><b className="green-text">${fmt(t.potential_winnings)}</b></div>
          </div>
        ))}
      </div>
    </div>
  );
}
