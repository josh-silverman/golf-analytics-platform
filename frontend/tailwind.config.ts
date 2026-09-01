import type { Config } from 'tailwindcss'

// Dark-only theme. Base tokens originate in
// docs/architecture/03-integration-and-deployment.md §3; the 2026-08 frontend
// redesign retuned four of them and added the chart ramp. Notes inline.
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#0A0E1A',
        surface: '#131826',
        'surface-2': '#1A2032',
        fg: {
          DEFAULT: '#F0F2F8',
          secondary: '#9BA3B7',
          // Lifted from #5E6680: the old value sat at ~2.8:1 on `background`,
          // well under AA for the 10-12px caption text it is used for
          // everywhere. #7B84A3 clears ~4.5:1 on `surface` and is close on
          // the darker page ground.
          tertiary: '#7B84A3',
        },
        // The Pinpoint brand green. Unchanged.
        accent: '#34A65F',
        // Brand green is too dim for interactive text on the dark ground
        // (links, active nav). This is the same hue, lifted to clear AA at
        // small sizes without becoming neon.
        'accent-fg': '#46C07C',
        // Outcome-good. Shifted from #22C55E toward mint so it no longer
        // reads as the same colour as the brand accent at a glance — the two
        // do different jobs and were visually indistinguishable before.
        positive: '#3FD98A',
        // Softened from a pure #EF4444: a dense strokes-gained table renders
        // dozens of these at once and the pure red vibrated against the navy.
        negative: '#F0655F',
        warning: '#F5A524',
        border: '#232B40',
        // A firmer edge for the few elements that need to separate from an
        // already-bordered parent (drawer against page, sticky header row).
        'border-strong': '#2E3752',
        // Chart ramp for the bespoke SVGs (SG categories, edge bars). Tuned
        // to sit on #0A0E1A without buzzing. `total` is the brand accent so
        // the most important series matches the rest of the UI.
        chart: {
          total: '#34A65F',
          ott: '#5B9DF0',
          app: '#A78BFA',
          arg: '#F5A524',
          putt: '#2DD4BF',
          grid: '#232B40',
        },
      },
      borderColor: {
        DEFAULT: '#232B40',
      },
      fontFamily: {
        sans: [
          '"Geist Variable"',
          'Geist',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
        mono: [
          '"Geist Mono Variable"',
          '"Geist Mono"',
          'ui-monospace',
          'SFMono-Regular',
          'monospace',
        ],
      },
      fontSize: {
        // Two display steps the app was missing. Everything else stays on
        // Tailwind's default scale.
        title: ['1.75rem', { lineHeight: '1.15', letterSpacing: '-0.015em' }],
        display: ['2.75rem', { lineHeight: '1.04', letterSpacing: '-0.025em' }],
      },
      keyframes: {
        rise: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'none' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        rise: 'rise 0.35s cubic-bezier(0.16, 1, 0.3, 1) both',
        'fade-in': 'fade-in 0.25s ease-out both',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
}

export default config
