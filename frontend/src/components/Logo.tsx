/**
 * Pinpoint wordmark — bullseye + golf-flag icon, recreated as inline SVG so it
 * scales crisply and sits well on the dark theme. Brand green rings + red
 * pennant; the flagstick is rendered light so it reads on dark backgrounds.
 */

export function Logo({
  className = '',
  showTagline = false,
}: {
  className?: string
  showTagline?: boolean
}) {
  return (
    <span className={`flex items-center gap-2 ${className}`}>
      <svg
        viewBox="0 0 56 56"
        className="h-7 w-7 shrink-0"
        role="img"
        aria-label="Pinpoint logo"
      >
        {/* bullseye */}
        <circle cx="24" cy="36" r="15" fill="none" stroke="#34A65F" strokeWidth="3" />
        <circle cx="24" cy="36" r="8.5" fill="none" stroke="#34A65F" strokeWidth="3" />
        <circle cx="24" cy="36" r="3" fill="#1E6B3A" />
        {/* flagstick rising from the center */}
        <line
          x1="24"
          y1="36"
          x2="24"
          y2="9"
          stroke="#CBD5E1"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        {/* red pennant */}
        <path d="M24 9 L39 13.5 L24 18 Z" fill="#D6402F" />
      </svg>
      <span className="leading-none">
        <span className="block font-semibold tracking-tight text-fg">Pinpoint</span>
        {showTagline && (
          <span className="block text-[10px] uppercase tracking-[0.2em] text-fg-tertiary">
            Golf Analytics
          </span>
        )}
      </span>
    </span>
  )
}
