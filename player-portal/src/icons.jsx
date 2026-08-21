import React from 'react';

// Minimal inline icon set — dependency-free, consistent 1.75px stroke.
const Base = ({ children, size = 20, ...props }) => (
  <svg
    width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
    {...props}
  >
    {children}
  </svg>
);

export const IconBall = (p) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7l3.5 2.5-1.3 4.1H9.8L8.5 9.5 12 7z" />
    <path d="M12 3v4M3.3 9.5l3.8 1.2M20.7 9.5l-3.8 1.2M6 20l3-5.4M18 20l-3-5.4" />
  </Base>
);

export const IconTicket = (p) => (
  <Base {...p}>
    <path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4z" />
    <path d="M14 6v2M14 16v2M14 10.5v3" strokeDasharray="0.1 3.5" />
  </Base>
);

export const IconWallet = (p) => (
  <Base {...p}>
    <path d="M3 7a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v1" />
    <rect x="3" y="7" width="18" height="13" rx="2" />
    <path d="M16 13.5h.01" />
    <path d="M15 13.5a1.5 1.5 0 1 0 3 0 1.5 1.5 0 1 0-3 0" />
  </Base>
);

export const IconUser = (p) => (
  <Base {...p}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20c0-3.6 3.1-6.5 7-6.5s7 2.9 7 6.5" />
  </Base>
);

export const IconLogout = (p) => (
  <Base {...p}>
    <path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3" />
    <path d="M16 17l5-5-5-5M21 12H9" />
  </Base>
);

export const IconPhone = (p) => (
  <Base {...p}>
    <path d="M6 3h4l1.5 4-2 1.3a11 11 0 0 0 5.2 5.2l1.3-2 4 1.5v4a2 2 0 0 1-2 2 17 17 0 0 1-15-15 2 2 0 0 1 2-2z" />
  </Base>
);

export const IconShield = (p) => (
  <Base {...p}>
    <path d="M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z" />
    <path d="M9 12l2 2 4-4" />
  </Base>
);

export const IconClock = (p) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3.5 2" />
  </Base>
);

export const IconArrowUp = (p) => (
  <Base {...p}><path d="M12 19V5M6 11l6-6 6 6" /></Base>
);
export const IconArrowDown = (p) => (
  <Base {...p}><path d="M12 5v14M6 13l6 6 6-6" /></Base>
);

export const IconChevronRight = (p) => (
  <Base {...p}><path d="M9 6l6 6-6 6" /></Base>
);

export const IconAlert = (p) => (
  <Base {...p}>
    <path d="M12 3l9 16H3z" />
    <path d="M12 10v4M12 17.5h.01" />
  </Base>
);

export const IconCheck = (p) => (
  <Base {...p}><path d="M20 6L9 17l-5-5" /></Base>
);

export const IconTrophy = (p) => (
  <Base {...p}>
    <path d="M7 4h10v5a5 5 0 0 1-10 0z" />
    <path d="M7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3" />
    <path d="M10 15.5V18M14 15.5V18M8 21h8M9 18h6" />
  </Base>
);

export const IconInbox = (p) => (
  <Base {...p}>
    <path d="M3 12l2.5-7A2 2 0 0 1 7.4 3.5h9.2a2 2 0 0 1 1.9 1.5L21 12" />
    <path d="M3 12v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6h-5.5l-1 2h-5l-1-2z" />
  </Base>
);
