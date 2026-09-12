import type { SVGProps } from "react";

/* Stroke icons for the rail and the top bar (from the mockup). Size comes from the parent. */

const base: SVGProps<SVGSVGElement> = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

const icons = {
  dashboard: (
    <svg {...base}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  ),
  insights: (
    <svg {...base}>
      <path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8 1 .9 1.6l.2 1.1h5l.2-1.1c.1-.6.4-1.2.9-1.6A6 6 0 0 0 12 3Z" />
      <path d="M10 20.5h4" />
    </svg>
  ),
  funds: (
    <svg {...base}>
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  ),
  categories: (
    <svg {...base}>
      <rect x="3" y="4" width="8" height="7" rx="1.5" />
      <rect x="13" y="4" width="8" height="7" rx="1.5" />
      <rect x="3" y="13" width="8" height="7" rx="1.5" />
      <rect x="13" y="13" width="8" height="7" rx="1.5" />
    </svg>
  ),
  movement: (
    <svg {...base}>
      <path d="M4 17l5-5 3.5 3.5L20 8" />
      <path d="M15 8h5v5" />
    </svg>
  ),
  overview: (
    <svg {...base}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
    </svg>
  ),
  output: (
    <svg {...base}>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
    </svg>
  ),
  calculation: (
    <svg {...base}>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h4" />
    </svg>
  ),
  reference: (
    <svg {...base}>
      <path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
      <path d="M4 10h16" />
    </svg>
  ),
  inputs: (
    <svg {...base}>
      <path d="M12 3v18M5 8l7-5 7 5" />
    </svg>
  ),
  versions: (
    <svg {...base}>
      <path d="M4 5h16v4H4zM4 15h16v4H4z" />
      <path d="M12 9v6" />
    </svg>
  ),
  validation: (
    <svg {...base}>
      <path d="M4 12l5 5L20 6" />
    </svg>
  ),
  upload: (
    <svg {...base}>
      <path d="M12 16V4" />
      <path d="M8 8l4-4 4 4" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </svg>
  ),
  admin: (
    <svg {...base}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 15a1.6 1.6 0 0 0-1.5-1H1.4a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 3 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 7 4.6h.1A1.6 1.6 0 0 0 8.6 3V2.9a2 2 0 1 1 4 0V3a1.6 1.6 0 0 0 2.7 1.1 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7h.1a2 2 0 1 1 0 4H21a1.6 1.6 0 0 0-1.6 1.7Z" />
    </svg>
  ),
  pin: (
    <svg {...base}>
      <path d="M9 4h6l-1 6 4 3v2H6v-2l4-3-1-6Z" />
      <path d="M12 15v5" />
    </svg>
  ),
  search: (
    <svg {...base}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  ),
  theme: (
    <svg {...base}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
    </svg>
  ),
  scope: (
    <svg {...base}>
      <path d="M3 5h18l-7 8v6l-4 2v-8z" />
    </svg>
  ),
  spark: (
    <svg {...base}>
      <path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" />
    </svg>
  ),
} as const;

export type IconName = keyof typeof icons;

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return <span className={className ?? "inline-block h-[19px] w-[19px] flex-none [&>svg]:h-full [&>svg]:w-full"}>{icons[name]}</span>;
}
