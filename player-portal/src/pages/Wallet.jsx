import React, { useEffect, useState } from 'react';
import { fetchWallet, fetchTransactions } from '../api';
import { IconWallet, IconAlert, IconArrowUp, IconArrowDown } from '../icons';

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

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Wallet</h1>
          <p className="muted small">Your balance and recent activity.</p>
        </div>
      </div>

      {error && <div className="top-alert"><IconAlert size={16} /> {error}</div>}

      {loading ? (
        <div className="skeleton" style={{ height: 132, marginTop: 12 }} />
      ) : (
        <div className="balance-card">
          <div className="row">
            <div className="muted small">Current balance</div>
            <IconWallet size={18} />
          </div>
          <div className="balance">${fmt(wallet?.balance)}</div>
          <div className="muted small">Deposit, withdraw and bet on WhatsApp — reply <b>menu</b>.</div>
        </div>
      )}

      <h2>Transactions</h2>
      {loading && (
        <div className="cards">
          {[0, 1, 2].map((i) => <div className="skeleton" style={{ height: 62 }} key={i} />)}
        </div>
      )}
      {!loading && !error && txns.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon"><IconWallet size={26} /></div>
          <strong>No transactions yet</strong>
          <span className="small">Deposits, withdrawals and bets will show up here.</span>
        </div>
      )}
      <div className="cards">
        {txns.map((tx) => {
          const positive = Number(tx.amount) >= 0;
          return (
            <div className="txn" key={tx.id}>
              <div className="txn-left">
                <div className={`txn-icon ${positive ? 'up' : 'down'}`}>
                  {positive ? <IconArrowUp size={16} /> : <IconArrowDown size={16} />}
                </div>
                <div>
                  <div className="txn-title">{tx.description || tx.transaction_type}</div>
                  <div className="muted small">{new Date(tx.created_at).toLocaleString()} · {tx.status}</div>
                </div>
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
