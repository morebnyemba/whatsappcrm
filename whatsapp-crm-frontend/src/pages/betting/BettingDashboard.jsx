import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { FiDollarSign, FiFileText, FiClock, FiAward, FiLoader } from 'react-icons/fi';
import apiClient from '../../services/api';

const fmt = (n) => Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const Tile = ({ icon: Icon, label, value }) => (
  <Card>
    <CardHeader className="pb-2">
      <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
        <Icon className="h-4 w-4" /> {label}
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div className="text-3xl font-bold">{value}</div>
    </CardContent>
  </Card>
);

const BettingDashboard = () => {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await apiClient.get('/crm-api/football/tickets/summary/');
        if (active) setSummary(res.data);
      } catch (e) {
        if (active) setError(e?.response?.data?.detail || 'Could not load your betting summary.');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  if (loading) {
    return <div className="p-6 flex items-center gap-2 text-muted-foreground"><FiLoader className="animate-spin" /> Loading…</div>;
  }
  if (error) {
    return <div className="p-6 text-red-600">{error}</div>;
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-1">Betting Dashboard</h1>
      <p className="text-muted-foreground mb-6">BetBlitz betting happens on WhatsApp — reply <strong>bet</strong> to place a bet.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Tile icon={FiDollarSign} label="Balance" value={`$${fmt(summary?.balance)}`} />
        <Tile icon={FiClock} label="Open bets" value={summary?.tickets_open ?? 0} />
        <Tile icon={FiAward} label="Bets won" value={summary?.tickets_won ?? 0} />
        <Tile icon={FiFileText} label="Upcoming matches" value={summary?.upcoming_fixtures ?? 0} />
      </div>
    </div>
  );
};

export default BettingDashboard;
