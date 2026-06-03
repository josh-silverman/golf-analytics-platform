# frontend

Vite + React + TypeScript dashboard for the PGA Tour Analytics Platform. Phase 0 scope: one route at `/` that fetches `/api/v1/healthz` and renders the backend status, with the dark-theme tokens from doc 03 §3 wired into Tailwind.

## Local development

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api/* → http://localhost:8000
```

The dev server proxies `/api/*` to the backend on port 8000, so run the backend first (`cd ../backend && uv run uvicorn app.main:app --reload`). Without it you'll see the error state on the home page — that's the wiring proof.

## Tests, lint, type check, build

```bash
npm run test         # vitest watch mode
npm run test:run     # one-shot (what CI uses)
npm run lint         # eslint flat config
npm run typecheck    # tsc -b --noEmit
npm run build        # tsc -b && vite build → dist/
```

## Design tokens

The dark palette lives in [tailwind.config.ts](./tailwind.config.ts), sourced from doc 03 §3:

| Token            | Hex       | Tailwind class examples                          |
|------------------|-----------|--------------------------------------------------|
| `background`     | `#0A0E1A` | `bg-background`                                  |
| `surface`        | `#131826` | `bg-surface`                                     |
| `surface-2`      | `#1A2032` | `bg-surface-2`                                   |
| `fg`             | `#F0F2F8` | `text-fg`                                        |
| `fg-secondary`   | `#9BA3B7` | `text-fg-secondary`                              |
| `fg-tertiary`    | `#5E6680` | `text-fg-tertiary`                               |
| `accent`         | `#4FD1C5` | `text-accent` / `bg-accent` / `border-accent`    |
| `positive`       | `#22C55E` | `text-positive`                                  |
| `negative`       | `#EF4444` | `text-negative`                                  |
| `warning`        | `#F59E0B` | `text-warning`                                   |

The subtle `#232B40` panel divider is wired as `borderColor.DEFAULT`, so bare `border` applies it.

Routes, components, charts, and the rest of the IA from doc 03 §3 land in Phase 1+.
