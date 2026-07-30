import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { FiCalendar, FiClock, FiLoader } from 'react-icons/fi';
import apiClient from '../../services/api';

const fmt = (n) => Number(n ?? 0).toFixed(2);

// Pull the home/draw/away odds out of the Match Winner (1X2) market, if present.
const oneXTwo = (markets = []) => {
  const mw = markets.find((m) => m.category === 'Match Winner');
  if (!mw) return null;
  const by = {};
  mw.outcomes.forEach((o) => { by[o.outcome_name.toLowerCase()] = o.odds; });
  if (by.home && by.draw && by.away) return { home: by.home, draw: by.draw, away: by.away };
  return null;
};

const Matches = () => {
  const [fixtures, setFixtures] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await apiClient.get('/crm-api/football/fixtures/');
        if (!active) return;
        setFixtures(Array.isArray(res.data) ? res.data : (res.data?.results ?? []));
      } catch (e) {
        if (active) setError(e?.response?.data?.detail || 'Could not load matches.');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-2">Football Matches</h1>
      <p className="text-muted-foreground mb-6">To place a bet, reply <strong>bet</strong> in your BetBlitz WhatsApp chat.</p>

      {loading && <div className="flex items-center gap-2 text-muted-foreground"><FiLoader className="animate-spin" /> Loading matches…</div>}
      {error && <div className="text-red-600">{error}</div>}
      {!loading && !error && fixtures.length === 0 && (
        <p className="text-muted-foreground">No upcoming matches are open for betting right now.</p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {fixtures.map((fx) => {
          const odds = oneXTwo(fx.markets);
          return (
            <Card key={fx.id}>
              <CardHeader>
                <CardTitle>{fx.home_team} vs {fx.away_team}</CardTitle>
                <CardDescription className="flex items-center gap-2">
                  <FiCalendar className="h-4 w-4" />
                  <span>{fx.league}</span>
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2 mb-4 text-muted-foreground">
                  <FiClock className="h-4 w-4" />
                  <span>{fx.match_date ? new Date(fx.match_date).toLocaleString() : 'TBD'}</span>
                </div>
                {odds ? (
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="p-2 bg-muted rounded-lg">
                      <div className="text-sm font-medium">Home</div>
                      <div className="text-lg font-bold">{fmt(odds.home)}</div>
                    </div>
                    <div className="p-2 bg-muted rounded-lg">
                      <div className="text-sm font-medium">Draw</div>
                      <div className="text-lg font-bold">{fmt(odds.draw)}</div>
                    </div>
                    <div className="p-2 bg-muted rounded-lg">
                      <div className="text-sm font-medium">Away</div>
                      <div className="text-lg font-bold">{fmt(odds.away)}</div>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">Odds not available yet.</div>
                )}
                <div className="mt-3 text-xs text-muted-foreground">
                  {(fx.markets?.length ?? 0)} market{(fx.markets?.length ?? 0) === 1 ? '' : 's'} available
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
};

export default Matches;
