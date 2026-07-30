import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { FiDollarSign, FiArrowUp, FiArrowDown, FiLoader } from 'react-icons/fi';
import apiClient from '../../services/api';

const fmt = (n) => Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const Wallet = () => {
  const [wallet, setWallet] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [w, t] = await Promise.all([
          apiClient.get('/crm-api/football/wallet/me/'),
          apiClient.get('/crm-api/football/wallet/transactions/'),
        ]);
        if (!active) return;
        setWallet(w.data);
        setTransactions(Array.isArray(t.data) ? t.data : (t.data?.results ?? []));
      } catch (e) {
        if (active) setError(e?.response?.data?.detail || 'Could not load your wallet.');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  if (loading) {
    return <div className="container mx-auto p-6 flex items-center gap-2 text-muted-foreground"><FiLoader className="animate-spin" /> Loading wallet…</div>;
  }
  if (error) {
    return <div className="container mx-auto p-6 text-red-600">{error}</div>;
  }

  return (
    <div className="container mx-auto p-6">
      <h1 className="text-3xl font-bold mb-6">My Wallet</h1>

      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Current Balance</CardTitle>
          <CardDescription>Your available betting funds</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-baseline gap-2">
            <FiDollarSign className="h-6 w-6 text-primary" />
            <span className="text-4xl font-bold">{fmt(wallet?.balance)}</span>
          </div>
          <p className="text-sm text-muted-foreground mt-4">
            Deposits, withdrawals and bets are managed on WhatsApp — reply <strong>menu</strong> in your BetBlitz chat.
          </p>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Transaction History</h2>
        <Card>
          <CardContent className="p-4">
            {transactions.length === 0 ? (
              <p className="text-muted-foreground text-sm py-4">No transactions yet.</p>
            ) : (
              <div className="space-y-4">
                {transactions.map((tx) => {
                  const positive = Number(tx.amount) >= 0;
                  return (
                    <div key={tx.id} className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-full ${positive ? 'bg-green-100' : 'bg-red-100'}`}>
                          {positive ? <FiArrowUp className="h-4 w-4 text-green-600" /> : <FiArrowDown className="h-4 w-4 text-red-600" />}
                        </div>
                        <div>
                          <div className="font-medium">{tx.description || tx.transaction_type}</div>
                          <div className="text-sm text-muted-foreground">{new Date(tx.created_at).toLocaleString()}</div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className={`font-medium ${positive ? 'text-green-600' : 'text-red-600'}`}>
                          {positive ? '+' : '-'}${fmt(Math.abs(Number(tx.amount)))}
                        </div>
                        <div className="text-sm text-muted-foreground">{tx.status}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Wallet;
