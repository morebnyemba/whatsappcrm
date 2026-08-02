import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';

export default function Login() {
  const { sendCode, confirmCode } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState('phone'); // 'phone' | 'code'
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  const onSendCode = async (e) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await sendCode(phone);
      setStep('code');
      setMsg('If that number has an account, we sent a login code on WhatsApp.');
    } catch {
      setError('Could not send a code. Please try again.');
    } finally { setBusy(false); }
  };

  const onVerify = async (e) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await confirmCode(phone, code);
      navigate('/matches', { replace: true });
    } catch {
      setError('Invalid or expired code.');
    } finally { setBusy(false); }
  };

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="brand-lg">BetBlitz</div>
        <p className="muted">Log in to view your matches, bets and wallet.</p>

        {step === 'phone' && (
          <form onSubmit={onSendCode}>
            <label>WhatsApp number</label>
            <input
              type="tel" inputMode="tel" placeholder="e.g. 263771234567"
              value={phone} onChange={(e) => setPhone(e.target.value)} required autoFocus
            />
            <button className="btn" disabled={busy}>{busy ? 'Sending…' : 'Send login code'}</button>
            <p className="muted small">We'll send a one-time code to your WhatsApp.</p>
          </form>
        )}

        {step === 'code' && (
          <form onSubmit={onVerify}>
            {msg && <p className="ok small">{msg}</p>}
            <label>6-digit code</label>
            <input
              type="text" inputMode="numeric" pattern="[0-9]*" maxLength={6} placeholder="123456"
              value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} required autoFocus
            />
            <button className="btn" disabled={busy}>{busy ? 'Verifying…' : 'Verify & log in'}</button>
            <button type="button" className="link" onClick={() => { setStep('phone'); setCode(''); setMsg(''); }}>
              Use a different number
            </button>
          </form>
        )}

        {error && <p className="err small">{error}</p>}
        <p className="muted small">To place a bet, chat to BetBlitz on WhatsApp and reply <b>bet</b>.</p>
      </div>
    </div>
  );
}
