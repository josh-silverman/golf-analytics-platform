import { useCalibration } from '../lib/api/calibration'
import type { OutcomeCalibration, ReliabilityBin } from '../lib/api/calibration'

const OUTCOME_LABELS: Record<string, string> = {
  win_prob: 'Win',
  top_5_prob: 'Top 5',
  top_10_prob: 'Top 10',
  top_20_prob: 'Top 20',
  make_cut_prob: 'Make Cut',
}

function labelFor(key: string): string {
  return OUTCOME_LABELS[key] ?? key
}

const PLOT = 160
const PAD = 24
const SIZE = PLOT + PAD * 2

function px(v: number): number {
  return PAD + v * PLOT
}

function py(v: number): number {
  // SVG y grows downward; invert so 0 sits at the bottom.
  return PAD + (1 - v) * PLOT
}

function radius(count: number, maxCount: number): number {
  if (maxCount <= 0) return 2
  return 2 + 4 * Math.sqrt(count / maxCount)
}

function ReliabilityDiagram({ outcome }: { outcome: OutcomeCalibration }) {
  const populated = (bins: ReliabilityBin[]) => bins.filter((b) => b.count > 0)
  const raw = populated(outcome.bins_raw)
  const calibrated = populated(outcome.bins_calibrated)
  const maxCount = Math.max(1, ...raw.map((b) => b.count), ...calibrated.map((b) => b.count))

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="w-full"
      role="img"
      aria-label={`Reliability diagram for ${labelFor(outcome.outcome_key)}`}
    >
      {/* plot frame */}
      <rect
        x={PAD}
        y={PAD}
        width={PLOT}
        height={PLOT}
        className="fill-transparent stroke-current text-fg-tertiary/30"
        strokeWidth={1}
      />
      {/* perfect-calibration diagonal */}
      <line
        x1={px(0)}
        y1={py(0)}
        x2={px(1)}
        y2={py(1)}
        className="stroke-current text-fg-tertiary/50"
        strokeWidth={1}
        strokeDasharray="3 3"
      />
      {/* raw model: hollow muted markers */}
      {raw.map((b, i) => (
        <circle
          key={`raw-${i}`}
          cx={px(b.mean_predicted)}
          cy={py(b.observed_frequency)}
          r={radius(b.count, maxCount)}
          className="fill-transparent stroke-current text-fg-tertiary"
          strokeWidth={1.5}
        />
      ))}
      {/* calibrated model: filled accent markers */}
      {calibrated.map((b, i) => (
        <circle
          key={`cal-${i}`}
          cx={px(b.mean_predicted)}
          cy={py(b.observed_frequency)}
          r={radius(b.count, maxCount)}
          className="fill-accent/70"
        />
      ))}
      {/* axis labels */}
      <text x={PAD} y={SIZE - 4} className="fill-current text-fg-tertiary" fontSize={9}>
        0
      </text>
      <text
        x={PAD + PLOT}
        y={SIZE - 4}
        textAnchor="end"
        className="fill-current text-fg-tertiary"
        fontSize={9}
      >
        predicted →
      </text>
      <text
        x={4}
        y={PAD + 8}
        className="fill-current text-fg-tertiary"
        fontSize={9}
      >
        observed
      </text>
    </svg>
  )
}

function OutcomeCard({ outcome }: { outcome: OutcomeCalibration }) {
  const improvement = outcome.brier_raw - outcome.brier_calibrated
  const improved = improvement > 0
  return (
    <div className="rounded-lg border bg-surface p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="font-medium text-fg">{labelFor(outcome.outcome_key)}</h3>
        <span
          className={`font-mono text-xs ${improved ? 'text-positive' : 'text-fg-tertiary'}`}
        >
          {improved ? '−' : '+'}
          {Math.abs(improvement).toFixed(4)} Brier
        </span>
      </div>
      <ReliabilityDiagram outcome={outcome} />
      <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
        <div>
          <dt className="text-fg-tertiary">Brier (raw)</dt>
          <dd className="font-mono text-fg-secondary">{outcome.brier_raw.toFixed(4)}</dd>
        </div>
        <div>
          <dt className="text-fg-tertiary">Brier (calibrated)</dt>
          <dd className="font-mono text-fg">{outcome.brier_calibrated.toFixed(4)}</dd>
        </div>
      </dl>
    </div>
  )
}

export function Diagnostics() {
  const { data, isLoading, isError, error } = useCalibration()

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">ML Diagnostics</h1>
        <p className="mt-1 text-sm text-fg-secondary">
          Held-out reliability of the active model — do the predicted probabilities
          match observed frequencies?
        </p>
      </header>

      {isLoading && <p className="text-fg-secondary">Loading diagnostics…</p>}

      {isError && (
        <p className="text-negative">
          Error: {error instanceof Error ? error.message : 'Unknown failure'}
        </p>
      )}

      {data?.status === 'no_model' && (
        <p className="text-fg-secondary">
          No trained model is registered yet — the predictions endpoint is serving the
          fallback. Train and activate a model to see calibration diagnostics.
        </p>
      )}

      {data?.status === 'uncalibrated' && (
        <p className="text-fg-secondary">
          The active model has no calibration data. Retrain through the calibrated
          pipeline to populate reliability diagnostics.
        </p>
      )}

      {data?.status === 'ok' && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-xs text-fg-tertiary">
            <span>
              Model: <span className="font-mono">{data.report.model_name}</span>
            </span>
            <span>
              Version: <span className="font-mono">{data.report.model_version_id}</span>
            </span>
            <span>Calibration set: {data.report.n_calibration_examples} examples</span>
          </div>

          <div className="flex items-center gap-4 text-xs text-fg-tertiary">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-accent/70" />
              calibrated
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-full border border-fg-tertiary" />
              raw
            </span>
            <span>dashed diagonal = perfect calibration</span>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.report.outcomes.map((o) => (
              <OutcomeCard key={o.outcome_key} outcome={o} />
            ))}
          </div>
        </>
      )}
    </main>
  )
}
