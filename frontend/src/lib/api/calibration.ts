import { useQuery } from '@tanstack/react-query'

export interface ReliabilityBin {
  lower: number
  upper: number
  mean_predicted: number
  observed_frequency: number
  count: number
}

export interface OutcomeCalibration {
  outcome_key: string
  brier_raw: number
  brier_calibrated: number
  bins_raw: ReliabilityBin[]
  bins_calibrated: ReliabilityBin[]
}

export interface CalibrationReport {
  model_name: string
  model_version_id: string
  n_calibration_examples: number
  outcomes: OutcomeCalibration[]
}

// 404 (only the fallback model is active) and 409 (active model has no
// calibration data) are expected states, not errors — the page renders a
// message for each rather than an error banner.
export type CalibrationState =
  | { status: 'ok'; report: CalibrationReport }
  | { status: 'no_model' }
  | { status: 'uncalibrated' }

async function fetchCalibration(): Promise<CalibrationState> {
  const r = await fetch('/api/v1/analytics/calibration')
  if (r.status === 404) return { status: 'no_model' }
  if (r.status === 409) return { status: 'uncalibrated' }
  if (!r.ok) throw new Error(`/analytics/calibration returned ${r.status}`)
  const report = (await r.json()) as CalibrationReport
  return { status: 'ok', report }
}

export function useCalibration() {
  return useQuery({ queryKey: ['analytics', 'calibration'], queryFn: fetchCalibration })
}
