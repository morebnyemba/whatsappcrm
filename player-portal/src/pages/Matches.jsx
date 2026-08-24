import React, { useEffect, useMemo, useState } from 'react';
import { fetchFixtures } from '../api';
import { IconBall, IconClock, IconAlert, IconInbox } from '../icons';

const odds = (markets = []) => {
  const mw = markets.find((m) => m.category === 'Match Winner');
  if (!mw) return null;
  const by = {};
  mw.outcomes.forEach((o) => { by[o.outcome_name.toLowerCase()] = o.odds; });
  return (by.home && by.draw && by.away) ? by : null;
};

const initials = (name = '') =>
  name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';

const dayLabel = (dateStr) => {
  if (!dateStr) return 'Date TBD';
  const d = new Date(dateStr);
  const now = new Date();
  const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
  const diffDays = Math.round((startOfDay(d) - startOfDay(now)) / 86400000);
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Tomorrow';
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
};

const timeLabel = (dateStr) => {
  if (!dateStr) return 'TBD';
  return new Date(dateStr).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
};

function SkeletonCards() {
  return (
    <div className="cards">
      {[0, 1, 2, 3].map((i) => (
        <div className="skeleton skel-card" key={i} />
      ))}
    </div>
  );
}

function FixtureCard({ fx }) {
  const o = odds(fx.markets);
  const isLive = fx.status === 'LIVE';
  return (
    <div className="card fixture-card">
      <div className="fixture-meta">
        <span className="league-chip">{fx.league}</span>
        {isLive ? (
          <span className="live-chip">
            <span className="live-dot" />
            LIVE{fx.elapsed_minutes != null ? ` · ${fx.elapsed_minutes}'` : ''}
          </span>
        ) : (
          <span className="kickoff-chip"><IconClock size={13} /> {timeLabel(fx.match_date)}</span>
        )}
      </div>
      <div className="matchup">
        <div className="team">
          <div className="team-badge">{initials(fx.home_team)}</div>
          <div className="team-name">{fx.home_team}</div>
          {isLive && fx.home_team_score != null && <div className="team-score">{fx.home_team_score}</div>}
        </div>
        <div className="vs-mark">{isLive ? '' : 'VS'}</div>
        <div className="team" style={{ justifyContent: 'flex-end', textAlign: 'right' }}>
          {isLive && fx.away_team_score != null && <div className="team-score">{fx.away_team_score}</div>}
          <div className="team-name">{fx.away_team}</div>
          <div className="team-badge">{initials(fx.away_team)}</div>
        </div>
      </div>
      {o ? (
        <div className="odds">
          <div className="odds-pill"><span>Home</span><b>{Number(o.home).toFixed(2)}</b></div>
          <div className="odds-pill"><span>Draw</span><b>{Number(o.draw).toFixed(2)}</b></div>
          <div className="odds-pill"><span>Away</span><b>{Number(o.away).toFixed(2)}</b></div>
        </div>
      ) : (
        <div className="muted small" style={{ marginTop: 10 }}>Odds not available yet.</div>
      )}
    </div>
  );
}

export default function Matches() {
  const [fixtures, setFixtures] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    fetchFixtures()
      .then((f) => active && setFixtures(f))
      .catch(() => active && setError('Could not load matches. Pull to refresh or try again shortly.'))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  const groups = useMemo(() => {
    const live = [];
    const byDay = new Map();
    for (const fx of fixtures) {
      if (fx.status === 'LIVE') { live.push(fx); continue; }
      const key = dayLabel(fx.match_date);
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key).push(fx);
    }
    const dayGroups = Array.from(byDay.entries());
    return live.length ? [['🔴 Live Now', live], ...dayGroups] : dayGroups;
  }, [fixtures]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Matches</h1>
          <p className="muted small">Live and upcoming odds from BetBlitz. Reply <b>bet</b> on WhatsApp to place a bet.</p>
        </div>
      </div>

      {error && <div className="top-alert"><IconAlert size={16} /> {error}</div>}

      {loading && <SkeletonCards />}

      {!loading && !error && fixtures.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon"><IconBall size={26} /></div>
          <strong>No upcoming matches right now</strong>
          <span className="small">Check back soon — new fixtures and odds are added regularly.</span>
        </div>
      )}

      {!loading && !error && groups.map(([label, list]) => (
        <div key={label}>
          <h2>{label}</h2>
          <div className="cards">
            {list.map((fx) => <FixtureCard fx={fx} key={fx.id} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
