import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { IconBall, IconPhone, IconShield, IconAlert, IconCheck } from '../icons';

const OTP_LENGTH = 6;

export default function Login() {
  const { sendCode, confirmCode } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState('phone'); // 'phone' | 'code'
  const [phone, setPhone] = useState('');
  const [digits, setDigits] = useState(Array(OTP_LENGTH).fill(''));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const inputRefs = useRef([]);

  const code = digits.join('');

  const onSendCode = async (e) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await sendCode(phone);
      setStep('code');
      setDigits(Array(OTP_LENGTH).fill(''));
      setMsg('We sent a 6-digit login code to your WhatsApp.');
      setTimeout(() => inputRefs.current[0]?.focus(), 50);
    } catch {
      setError('Could not send a code. Please check the number and try again.');
    } finally { setBusy(false); }
  };

  const onVerify = async (e) => {
    e?.preventDefault();
    if (code.length !== OTP_LENGTH) return;
    setError(''); setBusy(true);
    try {
      await confirmCode(phone, code);
      navigate('/matches', { replace: true });
    } catch {
      setError('That code is invalid or has expired.');
      setDigits(Array(OTP_LENGTH).fill(''));
      inputRefs.current[0]?.focus();
    } finally { setBusy(false); }
  };

  const setDigitAt = (idx, value) => {
    const next = [...digits];
    next[idx] = value;
    setDigits(next);
    return next;
  };

  const onDigitChange = (idx, raw) => {
    const value = raw.replace(/\D/g, '');
    if (!value) { setDigitAt(idx, ''); return; }
    const next = setDigitAt(idx, value[value.length - 1]);
    if (idx < OTP_LENGTH - 1) inputRefs.current[idx + 1]?.focus();
    if (next.every((d) => d !== '')) setTimeout(() => onVerify(), 0);
  };

  const onDigitKeyDown = (idx, e) => {
    if (e.key === 'Backspace' && !digits[idx] && idx > 0) {
      inputRefs.current[idx - 1]?.focus();
    }
  };

  const onPaste = (e) => {
    const text = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, OTP_LENGTH);
    if (!text) return;
    e.preventDefault();
    const next = Array(OTP_LENGTH).fill('').map((_, i) => text[i] || '');
    setDigits(next);
    const lastFilled = Math.min(text.length, OTP_LENGTH) - 1;
    inputRefs.current[Math.max(lastFilled, 0)]?.focus();
    if (text.length === OTP_LENGTH) setTimeout(() => onVerify(), 0);
  };

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="brand-mark">
          <div className="brand-logo"><IconBall size={20} color="#fff" /></div>
          <div>
            <div className="brand-lg">BetBlitz</div>
            <div className="brand-tag">Player portal</div>
          </div>
        </div>

        <div className="step-dots">
          <span className={step === 'phone' ? 'active' : ''} />
          <span className={step === 'code' ? 'active' : ''} />
        </div>

        {step === 'phone' && (
          <>
            <p className="lede">Enter your WhatsApp number to view your matches, bets and wallet.</p>
            <form onSubmit={onSendCode}>
              <div className="field">
                <label><IconPhone size={14} /> WhatsApp number</label>
                <div className="input-wrap">
                  <span className="prefix">+</span>
                  <input
                    type="tel" inputMode="tel" placeholder="263771234567"
                    value={phone} onChange={(e) => setPhone(e.target.value.replace(/[^\d+]/g, ''))}
                    required autoFocus
                  />
                </div>
              </div>
              <button className="btn" disabled={busy || !phone}>
                {busy && <span className="spinner" />}
                {busy ? 'Sending…' : 'Send login code'}
              </button>
              <p className="muted small" style={{ marginTop: 10, textAlign: 'center' }}>
                We'll send a one-time code to your WhatsApp — no password needed.
              </p>
            </form>
          </>
        )}

        {step === 'code' && (
          <>
            {msg && <div className="ok-banner"><IconCheck size={16} /> {msg}</div>}
            <form onSubmit={onVerify}>
              <div className="field">
                <label>Enter the 6-digit code</label>
                <div className="otp-row" onPaste={onPaste}>
                  {digits.map((d, i) => (
                    <input
                      key={i}
                      ref={(el) => (inputRefs.current[i] = el)}
                      className="otp-box"
                      type="text" inputMode="numeric" maxLength={1}
                      value={d}
                      onChange={(e) => onDigitChange(i, e.target.value)}
                      onKeyDown={(e) => onDigitKeyDown(i, e)}
                      autoFocus={i === 0}
                    />
                  ))}
                </div>
              </div>
              <button className="btn" disabled={busy || code.length !== OTP_LENGTH}>
                {busy && <span className="spinner" />}
                {busy ? 'Verifying…' : 'Verify & log in'}
              </button>
              <button
                type="button" className="link"
                onClick={() => { setStep('phone'); setDigits(Array(OTP_LENGTH).fill('')); setMsg(''); setError(''); }}
              >
                Use a different number
              </button>
            </form>
          </>
        )}

        {error && <div className="err-banner"><IconAlert size={16} /> {error}</div>}

        <div className="divider-note">
          <IconShield size={16} />
          <span>To place a bet, chat to BetBlitz on WhatsApp and reply <b>bet</b>. This portal is a secure, read-only view of your account.</span>
        </div>
      </div>
    </div>
  );
}
