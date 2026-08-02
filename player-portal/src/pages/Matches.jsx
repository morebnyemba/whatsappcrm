import React, { useEffect, useState } from 'react';
import { fetchFixtures } from '../api';

const odds = (markets = []) => {
  const mw = markets.find((m) => m.category === 'Match Winner');
  if (!mw) return null;
  const by = {};
  mw.outcomes.forEach((o) => { by[o.outcome_name.toLowerCase()] = o.odds; });
  return (by.home && by.draw && by.away) ? by : null;
};

export default function Matches() {
  const [fixtures, setFixtures] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    fetchFixtures()
      .then((f) => active && setFixtures(f))
      .catch(() => active && setError('Could not load matches.'))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  return (
    <div>
      <h1>Upcoming Matches</h1>
      <p className="muted small">Tap <b>bet</b> in your BetBlitz WhatsApp chat to place a bet.</p>
      {loading && <p className="muted">Loading…</p>}
      {error && <p className="err">{error}</p>}
      {!loading && !error && fixtures.length === 0 && <p className="muted">No upcoming matches right now.</p>}
      <div className="cards">
        {fixtures.map((fx) => {
          const o = odds(fx.markets);
          return (
            <div className="card" key={fx.id}>
              <div className="card-title">{fx.home_team} vs {fx.away_team}</div>
              <div className="muted small">{fx.league} · {fx.match_date ? new Date(fx.match_date).toLocaleString() : 'TBD'}</div>
              {o ? (
                <div className="odds">
                  <div><span>Home</span><b>{Number(o.home).toFixed(2)}</b></div>
                  <div><span>Draw</span><b>{Number(o.draw).toFixed(2)}</b></div>
                  <div><span>Away</span><b>{Number(o.away).toFixed(2)}</b></div>
                </div>
              ) : <div className="muted small">Odds not available yet.</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
