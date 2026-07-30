import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { FiAward, FiLoader } from 'react-icons/fi';
import apiClient from '../../services/api';

const fmt = (n) => Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const STATUS_STYLES = {
  PENDING: 'bg-yellow-100 text-yellow-800',
  PLACED: 'bg-blue-100 text-blue-800',
  WON: 'bg-green-100 text-green-800',
  LOST: 'bg-red-100 text-red-800',
  REFUNDED: 'bg-gray-100 text-gray-800',
  PARTIAL_WIN: 'bg-green-100 text-green-800',
};

const Tickets = () => {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await apiClient.get('/crm-api/football/tickets/');
        if (!active) return;
        setTickets(Array.isArray(res.data) ? res.data : (res.data?.results ?? []));
      } catch (e) {
        if (active) setError(e?.response?.data?.detail || 'Could not load your tickets.');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  return (
    <div className="container mx-auto p-6">
      <div className="flex justify-between items-center mb-2">
        <h1 className="text-3xl font-bold">My Betting Tickets</h1>
      </div>
      <p className="text-muted-foreground mb-6">Place new bets on WhatsApp — reply <strong>bet</strong> in your BetBlitz chat.</p>

      {loading && <div className="flex items-center gap-2 text-muted-foreground"><FiLoader className="animate-spin" /> Loading tickets…</div>}
      {error && <div className="text-red-600">{error}</div>}
      {!loading && !error && tickets.length === 0 && (
        <p className="text-muted-foreground">You have no bets yet.</p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {tickets.map((t) => (
          <Card key={t.id}>
            <CardHeader>
              <div className="flex justify-between items-start">
                <div>
                  <CardTitle>Ticket #{t.id}</CardTitle>
                  <CardDescription>{new Date(t.created_at).toLocaleString()}</CardDescription>
                </div>
                <span className={`px-2 py-1 rounded-full text-sm font-medium ${STATUS_STYLES[t.status] || 'bg-gray-100 text-gray-800'}`}>
                  {t.status_display || t.status}
                </span>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FiAward className="h-4 w-4 text-muted-foreground" />
                    <span>{t.bet_type_display || t.bet_type}</span>
                  </div>
                  <span className="font-medium">{t.bets?.length ?? 0} selection{(t.bets?.length ?? 0) === 1 ? '' : 's'}</span>
                </div>

                <div className="space-y-1 text-sm border-t pt-2">
                  {(t.bets ?? []).map((b) => (
                    <div key={b.id} className="flex justify-between">
                      <span className="text-muted-foreground truncate mr-2">{b.fixture} — {b.outcome}</span>
                      <span className="font-medium whitespace-nowrap">{Number(b.odds).toFixed(2)}</span>
                    </div>
                  ))}
                </div>

                <div className="space-y-2 border-t pt-2">
                  <div className="flex justify-between text-sm">
                    <span>Total Stake:</span>
                    <span className="font-medium">${fmt(t.total_stake)}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span>Potential Winnings:</span>
                    <span className="font-medium text-green-600">${fmt(t.potential_winnings)}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span>Total Odds:</span>
                    <span className="font-medium">{Number(t.total_odds).toFixed(2)}</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};

export default Tickets;
