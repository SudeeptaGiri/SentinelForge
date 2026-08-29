import React from 'react';

/* Minimal outline icon set (24x24, stroke-based) — no filled/skeuomorphic icons. */
const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

function Svg({ children, size = 16, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...base} {...rest}>
      {children}
    </svg>
  );
}

export const IconBolt = (p) => (
  <Svg {...p}><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" /></Svg>
);
export const IconCloud = (p) => (
  <Svg {...p}><path d="M7 18a4.5 4.5 0 0 1-1-8.9A5.5 5.5 0 0 1 16.5 8 4 4 0 0 1 17 16H7Z" /></Svg>
);
export const IconZap = (p) => (
  <Svg {...p}><path d="M11 21 3 13h6l-1-9 9 9h-6l1 8Z" /></Svg>
);
export const IconSparkle = (p) => (
  <Svg {...p}><path d="M12 3v4M12 17v4M4.2 4.2l2.8 2.8M17 17l2.8 2.8M3 12h4M17 12h4M4.2 19.8 7 17M17 7l2.8-2.8" /></Svg>
);
export const IconLayers = (p) => (
  <Svg {...p}><path d="m12 3 8 4-8 4-8-4 8-4Z" /><path d="m4 12 8 4 8-4M4 16l8 4 8-4" /></Svg>
);
export const IconSearch = (p) => (
  <Svg {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Svg>
);
export const IconBlueprint = (p) => (
  <Svg {...p}><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M8 8h8M8 12h5M8 16h8" /></Svg>
);
export const IconSettings = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.55V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.36a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.64 15a1.7 1.7 0 0 0-1.55-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.64 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.64a1.7 1.7 0 0 0 1.03-1.55V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15 4.64a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.36 9a1.7 1.7 0 0 0 1.55 1.03H21a2 2 0 1 1 0 4h-.09A1.7 1.7 0 0 0 19.4 15Z" /></Svg>
);
export const IconShield = (p) => (
  <Svg {...p}><path d="M12 3l8 3v6c0 4.5-3.4 7.9-8 9-4.6-1.1-8-4.5-8-9V6l8-3Z" /></Svg>
);
export const IconRocket = (p) => (
  <Svg {...p}><path d="M12 15c3-1 5-3 5.5-8.5C12 7 10 9 9 12l3 3Z" /><path d="M9 12l-4 1 2-4M12 15l1 4-4 2" /></Svg>
);
export const IconClock = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></Svg>
);
export const IconX = (p) => (
  <Svg {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>
);
export const IconCheck = (p) => (
  <Svg {...p}><path d="m5 12 5 5 9-10" /></Svg>
);
export const IconRefresh = (p) => (
  <Svg {...p}><path d="M20 11a8 8 0 0 0-14.6-4.4M4 4v5h5M4 13a8 8 0 0 0 14.6 4.4M20 20v-5h-5" /></Svg>
);
export const IconOctagonAlert = (p) => (
  <Svg {...p}><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8l5-5Z" /><path d="M12 8v5M12 16h.01" /></Svg>
);
export const IconChevronDown = (p) => (
  <Svg {...p}><path d="m6 9 6 6 6-6" /></Svg>
);
export const IconAgent = (p) => (
  <Svg {...p}><rect x="4" y="8" width="16" height="11" rx="2" /><path d="M12 8V4M9 4h6M9 13h.01M15 13h.01" /></Svg>
);
export const IconTool = (p) => (
  <Svg {...p}><path d="M14.7 6.3a4 4 0 0 0-5.6 5.6L3 18l3 3 6.1-6.1a4 4 0 0 0 5.6-5.6l-2.1 2.1-2-2 2.1-2.1Z" /></Svg>
);
