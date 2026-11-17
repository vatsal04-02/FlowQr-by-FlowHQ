import type { ReactNode } from "react";

/**
 * FlowQR's own navigation glyphs, drawn on one 24px grid: 1.75 stroke, round caps and joins, corner radii from one scale (1.1, 1.5, 2, 3.5), and each one is a picture of what the page
 * holds (a house with a doorway, a review bubble with its star, rising bars for growth, a sunrise for today's plan) instead of the stock set every dashboard ships.
 * They take the same props as a lucide icon, so the nav renders them in the same slot. Each has a quiet tint shape that fills in when the item (or its parent link) carries `data-on`,
 * which is how the active destination gets its second, filled state (see `.gl-fill` in globals.css); no prop is needed.
 */
type Props = { className?: string; strokeWidth?: number; "aria-hidden"?: boolean | "true" | "false" };

const glyph = (tint: ReactNode, line: ReactNode) =>
  function NavGlyph({ className, strokeWidth = 1.75 }: Props) {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden focusable="false">
        <g className="gl-fill" fill="currentColor" fillOpacity={0} stroke="none">{tint}</g>
        {line}
      </svg>
    );
  };

/** The two top-bar tools, drawn with the same rules as the nav set. */
export const SearchGlyph = glyph(null, <><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.4 15.4 4.3 4.3" /></>);
export const BellGlyph = glyph(null, <><path d="M5.2 17.8h13.6l-1.5-2V11a5.3 5.3 0 0 0-10.6 0v4.8z" /><path d="M10 20.6h4" /></>);

const HOUSE = "M4.5 11 12 4.5 19.5 11v7.5a1.5 1.5 0 0 1-1.5 1.5h-3.2v-4.6a1.1 1.1 0 0 0-1.1-1.1h-3.4a1.1 1.1 0 0 0-1.1 1.1V20H6a1.5 1.5 0 0 1-1.5-1.5z";
export const HomeGlyph = glyph(<path d={HOUSE} />, <path d={HOUSE} />);

const BUBBLE = "M5.5 4.5h13A2.5 2.5 0 0 1 21 7v8.2a2.5 2.5 0 0 1-2.5 2.5h-7.3l-3.8 3.2a.6.6 0 0 1-1-.5v-2.7H5.5A2.5 2.5 0 0 1 3 15.2V7a2.5 2.5 0 0 1 2.5-2.5z";
export const ReviewsGlyph = glyph(<path d={BUBBLE} />, <><path d={BUBBLE} /><path d="m12 8.1.95 1.95 2.15.3-1.55 1.5.37 2.15L12 13l-1.92 1 .37-2.15L8.9 10.35l2.15-.3z" fill="currentColor" stroke="none" /></>);

const BARS = <><rect x="4.5" y="12.5" width="3.6" height="7" rx="1.2" /><rect x="10.2" y="8.5" width="3.6" height="11" rx="1.2" /><rect x="15.9" y="4.5" width="3.6" height="15" rx="1.2" /></>;
export const GrowthGlyph = glyph(BARS, BARS);

const MORE = <><rect x="4" y="4" width="6.5" height="6.5" rx="2" /><circle cx="17" cy="7.25" r="3.25" /><circle cx="7.25" cy="17" r="3.25" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="2" /></>;
export const MoreGlyph = glyph(MORE, MORE);

const PIN = "M12 20.5s6-5.1 6-10a6 6 0 1 0-12 0c0 4.9 6 10 6 10z";
export const LocationsGlyph = glyph(<path d={PIN} />, <><path d={PIN} /><circle cx="12" cy="10.5" r="2.2" /></>);

export const TodayGlyph = glyph(<path d="M7.5 17.5a4.5 4.5 0 0 1 9 0z" />, <><path d="M4 17.5h16" /><path d="M7.5 17.5a4.5 4.5 0 0 1 9 0" /><path d="M12 6.4v2.2M5.3 9.8l1.5 1.5M18.7 9.8l-1.5 1.5M8 20.5h8" /></>);

export const TasksGlyph = glyph(<rect x="4" y="4" width="16" height="16" rx="4.5" />, <><rect x="4" y="4" width="16" height="16" rx="4.5" /><path d="m8.6 12.3 2.5 2.5 4.4-5" /></>);

export const ActivityGlyph = glyph(<><circle cx="6" cy="6.5" r="1.7" /><circle cx="6" cy="12" r="1.7" /><circle cx="6" cy="17.5" r="1.7" /></>,
  <><circle cx="6" cy="6.5" r="1.7" /><circle cx="6" cy="12" r="1.7" /><circle cx="6" cy="17.5" r="1.7" /><path d="M11 6.5h8.5M11 12h6M11 17.5h8.5" /></>);

export const SettingsGlyph = glyph(<><circle cx="15" cy="8" r="2.4" /><circle cx="9" cy="16" r="2.4" /></>,
  <><path d="M4 8h8.6M17.4 8H20M4 16h2.6M11.4 16H20" /><circle cx="15" cy="8" r="2.4" /><circle cx="9" cy="16" r="2.4" /></>);

export const BillingGlyph = glyph(<rect x="3" y="5.5" width="18" height="13" rx="3.5" />, <><rect x="3" y="5.5" width="18" height="13" rx="3.5" /><path d="M3 10h18M6.8 14.6H10" /></>);
