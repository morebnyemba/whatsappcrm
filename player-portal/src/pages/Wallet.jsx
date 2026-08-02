import React, { useEffect, useState } from 'react';
import { fetchWallet, fetchTransactions } from '../api';

const fmt = (n) => Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function Wallet() {
  const [wallet, setWallet] = useState(null);
  const [txns, setTxns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([fetchWallet(), fetchTransactions()])
      .then(([w, t]) => { if (active) { setWallet(w); setTxns(t); } })
      .catch(() => active && setError('Could not load your wallet.'))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  if (loading) return <p className="muted">Loading…</p>;
  if (error) return <p className="err">{error}</p>;

  return (
    <div>
      <h1>Wallet</h1>
      <div className="balance-card">
        <div className="muted small">Current balance</div>
        <div className="balance">${fmt(wallet?.balance)}</div>
        <div className="muted small">Deposit, withdraw and bet on WhatsApp — reply <b>menu</b>.</div>
      </div>
      <h2>Transactions</h2>
      {txns.length === 0 && <p className="muted">No transactions yet.</p>}
      <div className="cards">
        {txns.map((tx) => {
          const positive = Number(tx.amount) >= 0;
          return (
            <div className="txn" key={tx.id}>
              <div>
                <div>{tx.description || tx.transaction_type}</div>
                <div className="muted small">{new Date(tx.created_at).toLocaleString()} · {tx.status}</div>
              </div>
              <b className={positive ? 'green-text' : 'red-text'}>
                {positive ? '+' : '-'}${fmt(Math.abs(Number(tx.amount)))}
              </b>
            </div>
          );
        })}
      </div>
    </div>
  );
}
