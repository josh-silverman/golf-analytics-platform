import type { Config } from 'tailwindcss'

// Dark theme tokens from docs/architecture/03-integration-and-deployment.md §3.
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
          tertiary: '#5E6680',
        },
        accent: '#34A65F', // Pinpoint brand green
        positive: '#22C55E',
        negative: '#EF4444',
        warning: '#F59E0B',
        // Available as bg-border / text-border if needed; the subtle 1px
        // panel divider is wired into borderColor.DEFAULT below.
        border: '#232B40',
      },
      borderColor: {
        DEFAULT: '#232B40',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
