/**
 * Chart colours for the bespoke SVG visualisations (strokes-gained
 * sparklines, the edge bar chart). SVG `fill`/`stroke` attributes and
 * gradient stops need literal colour strings, so these mirror the `chart.*`
 * and semantic tokens in `tailwind.config.ts` rather than reaching for
 * utility classes. Keep the two in sync: this is the single place a raw hex
 * is allowed to live outside the Tailwind theme.
 */

export const chart = {
  grid: '#232B40',
  total: '#34A65F',
  ott: '#5B9DF0',
  app: '#A78BFA',
  arg: '#F5A524',
  putt: '#2DD4BF',
} as const

export const semantic = {
  accent: '#34A65F',
  positive: '#3FD98A',
  negative: '#F0655F',
  fg: '#F0F2F8',
  fgSecondary: '#9BA3B7',
  fgTertiary: '#727B99',
} as const
