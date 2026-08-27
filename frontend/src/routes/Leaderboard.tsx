import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { PlayerDrawer } from '../components/PlayerDrawer'
import { type ArchivedBoard, useArchivedBoard } from '../lib/api/archivedBoard'
import { type Status, useStatus } from '../lib/api/health'
import {
  type ForwardMarketSkill,
  type ForwardTrackRecord,
  useForwardTrackRecord,
} from '../lib/api/forwardTrackRecord'
import { usePredictions, type PlayerOutcome } from '../lib/api/predictions'
import { useCurrentTournament, useTournaments } from '../lib/api/tournaments'
import type { Tournament } from '../lib/api/types'
import { computeReportCard } from '../lib/reportCard'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

function formatFinish(o: PlayerOutcome): string {
  if (o.final_position != null) return `${o.final_position}`
  if (o.made_cut === false) return 'MC'
  return '—'
}

type SortKey = 'win_prob' | 'top_5_prob' | 'top_10_prob' | 'top_20_prob' | 'make_cut_prob'

// Per-column config. ``cellClass`` carries the per-column emphasis (Win is
// de-emphasised — the model does not sharply separate a single winner; Top 20 is
// highlighted as the most reliable market).
const COLUMNS: { key: SortKey; label: string; cellClass: string; barClass: string }[] = [
  { key: 'win_prob', label: 'Win', cellClass: 'text-fg-tertiary', barClass: 'bg-fg-tertiary/20' },
  { key: 'top_5_prob', label: 'Top 5', cellClass: 'text-fg', barClass: 'bg-fg-secondary/20' },
  { key: 'top_10_prob', label: 'Top 10', cellClass: 'text-fg', barClass: 'bg-fg-secondary/25' },
  { key: 'top_20_prob', label: 'Top 20', cellClass: 'text-accent font-semibold', barClass: 'bg-accent/25' },
  { key: 'make_cut_prob', label: 'Make Cut', cellClass: 'text-fg-secondary', barClass: 'bg-fg-secondary/20' },
]

const MARKET_LABELS: Record<string, string> = {
  make_cut_prob: 'Make cut',
  top_20_prob: 'Top 20',
  top_10_prob: 'Top 10',
  top_5_prob: 'Top 5',
  win_prob: 'Win',
}

// Skill-priority order, matching the Betting Edge market picker: make-cut and
// top-20 carry the most genuine backtest skill, win/top-5 the least.
const MARKET_ORDER = ['make_cut_prob', 'top_20_prob', 'top_10_prob', 'top_5_prob', 'win_prob']

// A market "clears the baseline" once its lead over the field-average
// baseline is bigger than the event-to-event swing in the record (the 90%
// range across events stays above zero) — the same bar the backend's own
// forward-record grader uses. Below that, or before there are enough events
// to measure the swing at all (ci_lower null), the point estimate is shown
// but labeled "too early to say" rather than hidden — with a handful of
// events, showing nothing looks like the feature is broken instead of like
// the record is still accumulating. Deliberately not called "confirmed": a
// 90% interval clearing zero is a threshold, and five correlated markets on
// the same players make it looser than it sounds.
type DisplayMarketSkill = ForwardMarketSkill & { clearsBaseline: boolean }

function orderedSkillMarkets(markets: ForwardMarketSkill[]): DisplayMarketSkill[] {
  return [...markets]
    .sort((a, b) => MARKET_ORDER.indexOf(a.market) - MARKET_ORDER.indexOf(b.market))
    .map((m) => ({ ...m, clearsBaseline: m.ci_lower != null && m.ci_lower > 0 }))
}

const CLEARS_TOOLTIP =
  'Ahead of the field-average baseline by more than the week-to-week swing in this record: the 90% range across events stays above zero.'
const TOO_EARLY_TOOLTIP =
  'The lead over the field-average baseline is smaller than the week-to-week swing so far, or there are too few events to measure the swing.'

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

// One-line summary. Leads with what the record is (how many events, how they
// were obtained), then what it shows. "The served board" rather than "the
// model": under Path A most covered players are served DataGolf's own
// probabilities, so these are not the in-house model's numbers.
function summarizeTrackRecord(tr: ForwardTrackRecord, markets: DisplayMarketSkill[]): string {
  const captured = tr.events_captured ?? 0
  const backfilled = tr.events_backfilled ?? 0
  const eventWord = `${tr.events} completed event${tr.events === 1 ? '' : 's'}`
  const opening =
    captured + backfilled === tr.events && tr.events > 0
      ? `${eventWord} graded: ${captured} recorded live before play, ${backfilled} reconstructed afterwards.`
      : `${eventWord} graded.`
  const clears = markets.filter((m) => m.clearsBaseline).map((m) => MARKET_LABELS[m.market])
  if (clears.length === 0) {
    return `${opening} Too early to say whether the served board beats the field-average baseline on any market.`
  }
  return `${opening} The served board is ahead of the field-average baseline on ${joinNames(clears)}.`
}

// "How to read this board" used to assert Top 20 was "the market where the
// board is most reliable" unconditionally, directly above a widget that can
// itself be saying "too early to say" about that same market. This derives
// the claim from the same clearsBaseline signal the widget uses, so the two
// can never disagree — when neither market has cleared yet, this says so
// instead of repeating a claim the widget next to it is actively hedging.
function rankingHint(tr: ForwardTrackRecord | undefined): string {
  if (!tr?.available || tr.markets.length === 0) {
    return 'ranked by Top 20 and Make Cut, the widest markets on the board, while the live record above builds up'
  }
  const ranked = orderedSkillMarkets(tr.markets)
  const clears = (key: string) => ranked.find((m) => m.market === key)?.clearsBaseline ?? false
  const top20 = clears('top_20_prob')
  const cut = clears('make_cut_prob')
  if (top20 && cut) {
    return 'ranked by Top 20 and Make Cut — both currently ahead of the field-average baseline in the record above'
  }
  if (top20) {
    return 'ranked by Top 20, currently ahead of the baseline in the record above, together with Make Cut'
  }
  if (cut) {
    return 'ranked by Top 20, together with Make Cut, which is currently ahead of the baseline in the record above'
  }
  return 'ranked by Top 20 and Make Cut, the widest markets on the board — the record above has not yet shown either one ahead of the baseline'
}

// "About N more events" only means something if the reader knows which pool
// it describes: the combined record reaches the target far sooner than the
// live-capture record, which is rebuilding from two events.
//
// Says "reach this page's N-event target" rather than "settle": the backend's
// `_MEANINGFUL_EVENTS = 20` is a chosen rule of thumb for a sample worth
// reading, not a calculated significance threshold, and "settle" implied a
// statistical claim the number doesn't back.
function settlingFooter(tr: ForwardTrackRecord): string | null {
  const target = tr.events + tr.events_to_meaningful
  const captured = tr.events_captured ?? 0
  const liveMore = Math.max(0, target - captured)
  if (tr.events_to_meaningful <= 0) return null
  if (captured > 0 && liveMore > tr.events_to_meaningful) {
    return (
      `About ${tr.events_to_meaningful} more completed events to reach this page's ${target}-event ` +
      `rule-of-thumb sample size (a chosen target, not a calculated threshold); the live-only record needs about ${liveMore} more.`
    )
  }
  return (
    `About ${tr.events_to_meaningful} more completed events to reach this page's ${target}-event ` +
    `rule-of-thumb sample size (a chosen target, not a calculated threshold).`
  )
}

// The two provenances render as separate blocks with their own n. Falls back
// to a single pooled block against an older backend that doesn't report the
// split, so a deploy-order skew never blanks the widget.
type ProvenanceBlockData = {
  title: string
  events: number
  players: number
  markets: ForwardMarketSkill[]
  note: string
}

function provenanceBlocks(tr: ForwardTrackRecord): ProvenanceBlockData[] {
  const blocks: ProvenanceBlockData[] = []
  const captured = tr.markets_captured ?? []
  const backfilled = tr.markets_backfilled ?? []
  if (captured.length > 0 && (tr.events_captured ?? 0) > 0) {
    const events = tr.events_captured ?? 0
    const allEarly = captured.every((m) => !(m.ci_lower != null && m.ci_lower > 0))
    blocks.push({
      title: 'Predicted live',
      events,
      players: tr.players_captured ?? 0,
      markets: captured,
      note:
        'Recorded before play began, as the site served them.' +
        (allEarly
          ? ` ${events} event${events === 1 ? '' : 's'} is not enough to tell skill from luck; expect these numbers to move.`
          : ''),
    })
  }
  if (backfilled.length > 0 && (tr.events_backfilled ?? 0) > 0) {
    blocks.push({
      title: 'Reconstructed',
      events: tr.events_backfilled ?? 0,
      players: tr.players_backfilled ?? 0,
      markets: backfilled,
      note:
        'Rebuilt afterwards from the data available before each event. No result information goes in, but later code produced them, so they are not a record of what the site showed those weeks.',
    })
  }
  if (blocks.length === 0) {
    blocks.push({
      title: 'All graded events',
      events: tr.events,
      players: tr.players_graded,
      markets: tr.markets,
      note: '',
    })
  }
  return blocks
}

// The record spans the 2026-07-29 Path A fix. Boards served before it
// cold-started the whole field but carry the same model version id, so when the
// graded set mixes regimes the aggregate is not measuring one system. Say so
// rather than let the headline number imply otherwise. Returns null when every
// graded board came from the same regime, which is the normal case over time.
function regimeCaveat(tr: ForwardTrackRecord): string | null {
  const pathA = tr.events_path_a ?? 0
  const cold = tr.events_cold_start_only ?? 0
  const unknown = tr.events_regime_unknown ?? 0
  const parts: string[] = []
  if (cold > 0) parts.push(`${cold} served cold-start only`)
  if (unknown > 0) parts.push(`${unknown} of unrecorded coverage`)
  if (parts.length === 0) return null
  return `Includes ${parts.join(' and ')} out of ${pathA + cold + unknown}, so this pools more than one serving configuration.`
}

function formatSkill(skill: number): string {
  const sign = skill >= 0 ? '+' : ''
  return `${sign}${(skill * 100).toFixed(1)}%`
}

const STATUS_BADGE: Record<string, string> = {
  upcoming: 'bg-warning/15 text-warning',
  in_progress: 'bg-positive/15 text-positive',
  completed: 'bg-fg-tertiary/15 text-fg-tertiary',
}

const STATUS_LABEL: Record<string, string> = {
  upcoming: 'Upcoming',
  in_progress: 'In Progress',
  completed: 'Completed',
}

// Dropdown ordering: live first, then soonest upcoming, then most-recent done.
const _STATUS_ORDER: Record<string, number> = { in_progress: 0, upcoming: 1, completed: 2 }

// Cap on how many completed events the dropdown offers, most-recent first, so
// it doesn't grow unbounded as the schedule accumulates.
const MAX_COMPLETED_EVENTS = 25

function eventLabel(t: Tournament): string {
  const d = new Date(t.start_date).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  return `${t.name} · ${STATUS_LABEL[t.status] ?? t.status} · ${d}`
}

const SORT_KEYS: SortKey[] = COLUMNS.map((c) => c.key)

function csvEscape(s: string): string {
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// Export the current (sorted + filtered) board as CSV for offline analysis.
function downloadBoardCsv(filename: string, rows: PlayerOutcome[]): void {
  const header = ['Rank', 'Player', 'Win', 'Top 5', 'Top 10', 'Top 20', 'Make Cut']
  const body = rows.map((o, i) =>
    [
      i + 1,
      csvEscape(o.player_name),
      o.win_prob.toFixed(4),
      o.top_5_prob.toFixed(4),
      o.top_10_prob.toFixed(4),
      o.top_20_prob.toFixed(4),
      o.make_cut_prob.toFixed(4),
    ].join(','),
  )
  const csv = [header.join(','), ...body].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// Which board the report card scored, in the same vocabulary the forward-record
// widget uses above it: "Predicted live" for a board pinned before play,
// "Reconstructed" for one the backfill rebuilt afterwards. The distinction is
// the difference between a forward record and a re-run, and it has to reach the
// reader on the card itself rather than only in the aggregate widget.
// Exported for reuse by the Track Record page, which shows the same
// captured-vs-reconstructed + out-of-sample caveat for one standalone week.
export function ProvenanceNote({ board, n }: { board: ArchivedBoard; n: number }) {
  const captured = board.source === 'captured'
  const when = board.captured_at ? new Date(board.captured_at).toLocaleDateString() : null
  return (
    <div className="space-y-1 text-xs text-fg-tertiary">
      <p>
        <span className="font-medium text-fg-secondary">
          {captured ? 'Predicted live' : 'Reconstructed'} · {n} players on the board
          {when ? ` · pinned ${when}` : ''}:
        </span>{' '}
        {captured
          ? 'scored against the board recorded before play began, exactly as the site served it.'
          : 'this board was rebuilt after the event from the data available beforehand. No result information goes in, but later code produced it, so it is not a record of what the site showed that week.'}
      </p>
      {!board.out_of_sample && (
        <p className="italic">
          The model that produced this board was not trained strictly before the event, so these
          figures are not an out-of-sample result and the forward record excludes them.
        </p>
      )}
      <p>The Finish column shows where each player ended up (MC = missed cut).</p>
    </div>
  )
}

// Serving provenance for the board on screen (H6). `model_version_id` reads
// "path_a@<id>" as soon as Path A is CONFIGURED, before any DataGolf call
// happens — so a board that cold-started the entire field is stamped
// identically to a healthy one. `dg_direct_count` is what actually tells
// them apart, and it was already being computed and simply discarded before
// this fix. Deliberately does not read `status.model_version_id` as "the
// model that made this board" — that field is the registry's active model,
// which can differ from what a specific board is stamped with (ledger.md
// §3.1); the two are shown side by side, not merged.
function BoardProvenance({
  status,
  boardModelVersionId,
  dgDirectCount,
  dgFetchStatus,
  fieldSize,
}: {
  status: Status | undefined
  boardModelVersionId: string | null
  dgDirectCount: number | null
  dgFetchStatus: string | null
  fieldSize: number
}) {
  if (!status) return null

  const isPathA = status.serving_strategy === 'path_a'

  let badge: { label: string; cls: string }
  let note: string
  if (!isPathA) {
    badge = { label: status.serving_strategy, cls: 'bg-fg-tertiary/15 text-fg-tertiary' }
    note = `Serving strategy is "${status.serving_strategy}", not Path A: every player on this board is scored by the in-house model, so DataGolf direct-coverage does not apply.`
  } else if (dgDirectCount == null) {
    badge = { label: 'Path A · coverage unknown', cls: 'bg-warning/15 text-warning' }
    note = 'Path A is configured, but this board does not report how many players were priced by DataGolf directly — a fully cold-started board would look identical to a healthy one here.'
  } else if (dgDirectCount === 0) {
    // NO_COVERAGE means the fetch worked and DataGolf genuinely had nothing —
    // a real cold start. Anything else (FETCH_FAILED, an unexpected OK paired
    // with a zero count, or a null/NOT_ATTEMPTED status) is a broken or
    // unusual fetch producing the same zero, which needs the opposite reaction.
    const legitimateColdStart = dgFetchStatus === 'no_coverage'
    badge = {
      label: legitimateColdStart ? 'Path A · cold-started (no coverage)' : 'Path A · fetch problem',
      cls: 'bg-negative/15 text-negative',
    }
    note = legitimateColdStart
      ? 'DataGolf answered but had nothing for this field, so the in-house model cold-started every player. A legitimate result, not a fetch failure.'
      : `DataGolf's fetch did not produce usable data for this event (status: ${dgFetchStatus ?? 'unknown'}), so this board cold-started every player — a degraded result, not a clean cold start.`
  } else {
    badge = {
      label: `Path A · ${dgDirectCount}/${fieldSize} direct`,
      cls: 'bg-accent/15 text-accent',
    }
    note = `${dgDirectCount} of ${fieldSize} players on this board were priced directly by DataGolf; the remaining ${fieldSize - dgDirectCount} cold-started the in-house model.`
  }

  const registryLabel = status.model_version_id
    ? `${status.model_name} (${status.model_version_id})`
    : `${status.model_name} (no active version)`
  const differs =
    boardModelVersionId != null &&
    status.model_version_id != null &&
    boardModelVersionId !== status.model_version_id

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-fg-tertiary">
      <span
        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badge.cls}`}
        title={note}
      >
        {badge.label}
      </span>
      <span>
        Registry-active model: <span className="font-mono">{registryLabel}</span>
        {differs
          ? ` — this board is stamped ${boardModelVersionId}, a different id; the two need not match.`
          : '.'}
      </span>
    </div>
  )
}

// Combined label + value in a single text node on purpose, so the player name
// never appears as its own element (keeps it out of exact-text test queries).
// Exported for reuse by the Track Record page's report-card tiles.
export function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-surface px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-fg-tertiary">{label}</p>
      <p className="mt-0.5 truncate text-sm text-fg">{value}</p>
    </div>
  )
}

export function Leaderboard() {
  const { data: currentTournament, isLoading: currentLoading } = useCurrentTournament()
  const { data: tournamentsEnv } = useTournaments()
  const { data: trackRecord } = useForwardTrackRecord()
  // Best-effort: the provenance strip degrades to nothing, never to an error,
  // if the registry snapshot is unreachable.
  const { data: status } = useStatus()
  const [searchParams, setSearchParams] = useSearchParams()

  // Selected event: an explicit pick overrides; otherwise follow the current
  // event. Seeded from the URL so a board is shareable/bookmarkable.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const e = searchParams.get('event')
    return e ? Number(e) : null
  })
  const effectiveId = selectedId ?? currentTournament?.id ?? null

  // Event options for the switcher; falls back to just the current event when
  // the full list isn't available. DataGolf only carries the current week's
  // field, so an upcoming event that isn't "current" has no field to predict
  // yet — offering it leads to either an empty board or a very slow first
  // build. Filtered to in-progress/completed events plus whichever one is
  // current; completed events are further capped to the most recent
  // MAX_COMPLETED_EVENTS so the dropdown (and its slow-cold-load surface)
  // stays bounded.
  const eventOptions = useMemo(() => {
    const list = Array.isArray(tournamentsEnv?.data)
      ? tournamentsEnv.data
      : currentTournament
        ? [currentTournament]
        : []
    const selectable = list.filter(
      (t) => t.status !== 'upcoming' || t.id === currentTournament?.id,
    )
    const sorted = [...selectable].sort((a, b) => {
      const sa = _STATUS_ORDER[a.status] ?? 9
      const sb = _STATUS_ORDER[b.status] ?? 9
      if (sa !== sb) return sa - sb
      const ta = +new Date(a.start_date)
      const tb = +new Date(b.start_date)
      return a.status === 'upcoming' ? ta - tb : tb - ta
    })
    const live = sorted.filter((t) => t.status !== 'completed')
    const completed = sorted.filter((t) => t.status === 'completed').slice(0, MAX_COMPLETED_EVENTS)
    return [...live, ...completed]
  }, [tournamentsEnv, currentTournament])

  // The trimmed eventOptions may not include the selected event (e.g. a
  // bookmarked link to an older completed event beyond the dropdown's cap),
  // so fall back to the full fetched list before falling back to
  // currentTournament — showing the wrong event's name/status badge would be
  // worse than a slightly bigger lookup.
  const selectedTournament =
    eventOptions.find((t) => t.id === effectiveId) ??
    (Array.isArray(tournamentsEnv?.data) ? tournamentsEnv.data : []).find(
      (t) => t.id === effectiveId,
    ) ??
    currentTournament ??
    null

  const isCompleted = selectedTournament?.status === 'completed'

  // Which board this page shows, and where it comes from.
  //
  // A completed event is served from the ledger: the snapshot pinned before
  // play, the same one the report card scores. Anything else is served live.
  // The two are never mixed, so the table and the card above it cannot show
  // different numbers for the same event.
  //
  // The live board is switched off entirely for a completed event. Asking for
  // it would recompute an expensive board with today's model — numbers that
  // are not what was predicted beforehand and that nothing on the page renders.
  const {
    data: predictions,
    isLoading: predictionsLoading,
    isError,
    error,
  } = usePredictions(effectiveId, !isCompleted)

  const {
    data: archived,
    isLoading: archivedLoading,
    isError: archivedError,
    error: archivedErr,
  } = useArchivedBoard(effectiveId, isCompleted)

  // The pinned board for a completed event, the live board otherwise. Null
  // means there is nothing to render — for a completed event that is the
  // honest answer when no snapshot exists, never a fallback recomputation.
  const boardOutcomes: PlayerOutcome[] | null = isCompleted
    ? archived?.available
      ? archived.outcomes
      : null
    : (predictions?.outcomes ?? null)

  const boardLoading = isCompleted ? archivedLoading : predictionsLoading

  // Serving provenance for whichever board is on screen: the pinned board's
  // own fields for a completed event, the live board's for anything else.
  // `model_version_id` here is the board's own stamp, which is deliberately
  // NOT the same field as `status.model_version_id` — see BoardProvenance.
  const boardProvenance = isCompleted
    ? {
        modelVersionId: archived?.model_version_id ?? null,
        dgDirectCount: archived?.dg_direct_count ?? null,
        dgFetchStatus: archived?.dg_fetch_status ?? null,
      }
    : {
        modelVersionId: predictions?.model_version_id ?? null,
        dgDirectCount: predictions?.dg_direct_count ?? null,
        dgFetchStatus: predictions?.dg_fetch_status ?? null,
      }

  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const s = searchParams.get('sort') as SortKey | null
    return s && SORT_KEYS.includes(s) ? s : 'top_20_prob'
  })
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(() =>
    searchParams.get('dir') === 'asc' ? 'asc' : 'desc',
  )
  const [query, setQuery] = useState('')
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(() => {
    const p = searchParams.get('player')
    return p ? Number(p) : null
  })

  // Mirror the current view into the URL (replace, so it doesn't spam history).
  useEffect(() => {
    const next = new URLSearchParams()
    if (effectiveId != null) next.set('event', String(effectiveId))
    next.set('sort', sortKey)
    next.set('dir', sortDir)
    if (selectedPlayerId != null) next.set('player', String(selectedPlayerId))
    setSearchParams(next, { replace: true })
  }, [effectiveId, sortKey, sortDir, selectedPlayerId, setSearchParams])

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  // Per-market maxima over the whole field, so each bar scales to the event's
  // leader in that market (filtering doesn't rescale the bars).
  const colMax = useMemo(() => {
    const m: Record<SortKey, number> = {
      win_prob: 0,
      top_5_prob: 0,
      top_10_prob: 0,
      top_20_prob: 0,
      make_cut_prob: 0,
    }
    for (const o of boardOutcomes ?? []) {
      for (const c of COLUMNS) m[c.key] = Math.max(m[c.key], o[c.key])
    }
    return m
  }, [boardOutcomes])

  const rows = useMemo(() => {
    if (!boardOutcomes) return []
    const q = query.trim().toLowerCase()
    const filtered = q
      ? boardOutcomes.filter((o) => o.player_name.toLowerCase().includes(q))
      : boardOutcomes
    return [...filtered].sort((a, b) => {
      const diff = a[sortKey] - b[sortKey]
      return sortDir === 'desc' ? -diff : diff
    })
  }, [boardOutcomes, sortKey, sortDir, query])

  const drawerOutcome = boardOutcomes?.find((o) => o.player_id === selectedPlayerId) ?? null

  // At-a-glance leaders for a live event. Completed events show the report card
  // in this slot instead, so this deliberately reads the live board only.
  const fieldSummary = useMemo(() => {
    const o = predictions?.outcomes ?? []
    if (o.length === 0) return null
    const top = (k: SortKey) => o.reduce((best, c) => (c[k] > best[k] ? c : best), o[0])
    return {
      favorite: top('win_prob'),
      contender: top('top_20_prob'),
      safestCut: top('make_cut_prob'),
      size: o.length,
    }
  }, [predictions])

  // Report card: how the PINNED pre-event board compared to the result.
  // Shared with the Track Record page — see `lib/reportCard.ts`.
  const reportCard = useMemo(() => computeReportCard(archived), [archived])

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Leaderboard</h1>
          {selectedTournament && (
            <span
              className={`rounded-full px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wider ${
                STATUS_BADGE[selectedTournament.status] ?? 'bg-fg-tertiary/15 text-fg-tertiary'
              }`}
            >
              {selectedTournament.status.replace('_', ' ')}
            </span>
          )}
        </div>

        {/* Event switcher — pick any tournament's board */}
        {eventOptions.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs uppercase tracking-wider text-fg-tertiary" htmlFor="event-select">
              Event
            </label>
            <select
              id="event-select"
              value={effectiveId ?? ''}
              onChange={(e) => setSelectedId(Number(e.target.value))}
              className="max-w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg focus:border-accent focus:outline-none"
            >
              {eventOptions.map((t) => (
                <option key={t.id} value={t.id}>
                  {eventLabel(t)}
                </option>
              ))}
            </select>
            {selectedTournament?.purse != null && (
              <span className="text-xs text-fg-tertiary">
                Purse ${(selectedTournament.purse / 1_000_000).toFixed(1)}M
              </span>
            )}
          </div>
        )}

        {boardOutcomes && (
          <p className="text-xs italic text-fg-tertiary">
            {isCompleted
              ? 'The board as it was pinned before play, read from the prediction ledger. Not recomputed.'
              : 'Pre-event predictions, not updated during play.'}
          </p>
        )}

        {boardOutcomes && (
          <BoardProvenance
            status={status}
            boardModelVersionId={boardProvenance.modelVersionId}
            dgDirectCount={boardProvenance.dgDirectCount}
            dgFetchStatus={boardProvenance.dgFetchStatus}
            fieldSize={boardOutcomes.length}
          />
        )}

        {trackRecord?.available && trackRecord.markets.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs text-fg-secondary">
              <span className="font-medium">Forward out-of-sample track record.</span>{' '}
              {summarizeTrackRecord(trackRecord, orderedSkillMarkets(trackRecord.markets))}
            </p>
            <p className="text-xs text-fg-tertiary">
              Every figure below compares the served board against one reference: predicting the
              field average for every player.
            </p>
            {provenanceBlocks(trackRecord).map((b) => (
              <div key={b.title} className="text-xs text-fg-tertiary">
                <span className="font-medium text-fg-secondary">
                  {b.title} · {b.events} event{b.events === 1 ? '' : 's'}, {b.players} players
                  graded:
                </span>{' '}
                {orderedSkillMarkets(b.markets).map((m, i) => (
                  <span key={m.market}>
                    {i > 0 && '· '}
                    {MARKET_LABELS[m.market]}{' '}
                    <span
                      className={`font-mono ${m.clearsBaseline ? 'text-accent' : 'text-fg-tertiary'}`}
                      title={m.clearsBaseline ? CLEARS_TOOLTIP : TOO_EARLY_TOOLTIP}
                    >
                      {formatSkill(m.brier_skill)}
                    </span>
                    {!m.clearsBaseline && <span className="italic"> (too early to say)</span>}{' '}
                  </span>
                ))}
                {b.note && <span className="italic">{b.note}</span>}
              </div>
            ))}
            {regimeCaveat(trackRecord) && (
              <p className="text-xs italic text-fg-tertiary">{regimeCaveat(trackRecord)}</p>
            )}
            {settlingFooter(trackRecord) && (
              <p className="text-xs text-fg-tertiary">{settlingFooter(trackRecord)}</p>
            )}
          </div>
        )}
      </header>

      {(currentLoading || boardLoading) && (
        <div className="space-y-1">
          <p className="text-fg-secondary">
            {isCompleted ? 'Loading the pinned board…' : 'Loading predictions…'}
          </p>
          {!isCompleted && (
            <p className="text-xs text-fg-tertiary">
              The first load after a while warms live tour data from DataGolf and can take a
              minute. It&rsquo;s fast afterwards.
            </p>
          )}
        </div>
      )}

      {!currentLoading && effectiveId == null && (
        <p className="text-fg-secondary">No active tournament to predict.</p>
      )}

      {(isCompleted ? archivedError : isError) && (
        <p className="text-negative">
          Error:{' '}
          {(() => {
            const e = isCompleted ? archivedErr : error
            return e instanceof Error ? e.message : 'Unknown failure'
          })()}
        </p>
      )}

      {!isCompleted && predictions && predictions.outcomes.length === 0 && (
        <p className="text-fg-secondary">
          No field published for this event yet. DataGolf only carries the current
          week&rsquo;s field, so this board is empty until the event is closer.
        </p>
      )}

      {/* Completed event with nothing in the ledger. The board is withheld
          entirely rather than replaced by a recomputation: a board built today
          is not what was predicted before this event, and showing one under an
          event that has already finished invites exactly that reading. */}
      {isCompleted && !archivedLoading && archived && !archived.available && (
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm leading-relaxed text-fg-secondary">
          <p className="font-medium text-fg">No pre-event board was pinned for this event.</p>
          <p className="mt-1">
            The ledger holds no snapshot for {selectedTournament?.name ?? 'this event'}, so there
            is neither a board to show nor anything to score against the result. Nothing is
            displayed in its place: the current model can still produce a board for this field,
            but that is not what was predicted beforehand and it is not a record of anything.
          </p>
          <p className="mt-1 text-xs text-fg-tertiary">
            Boards are pinned by the scheduled Wednesday capture. An event that finished before
            that job existed, or whose capture window was missed, has no snapshot and cannot be
            given one after the fact.
          </p>
        </div>
      )}

      {boardOutcomes && boardOutcomes.length > 0 && (
        <>
          {/* How to read this board — the ranking claim is derived from the same
              clearsBaseline signal the record widget above uses, so the two
              cannot disagree about which markets are currently ahead. */}
          <div className="rounded-lg border border-border/70 bg-surface px-4 py-3 text-xs leading-relaxed text-fg-secondary">
            <p className="font-medium text-fg">How to read this board</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-4 marker:text-fg-tertiary">
              <li>Players are {rankingHint(trackRecord)}.</li>
              <li>
                <span className="text-fg">Win</span> is intentionally de-emphasised: the board reads
                overall contention well but does not reliably single out one winner. Weigh a
                player&rsquo;s chances by Top 10 / Top 20 / Make Cut rather than the Win column.
              </li>
              <li>Click any column header to re-sort, or a player to view their strokes-gained trends.</li>
            </ul>
          </div>

          {/* Completed event → report card from the same pinned board the table
              below renders; otherwise field at-a-glance. */}
          {isCompleted && reportCard && archived ? (
            <div className="space-y-2">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <SummaryTile
                  label="Winner"
                  value={
                    reportCard.winner
                      ? `${reportCard.winner.player_name} · board #${reportCard.winnerRank} by win%`
                      : '—'
                  }
                />
                <SummaryTile
                  label="Top-20 hits"
                  value={
                    reportCard.top20ByChance != null
                      ? `${reportCard.top20Hits} / ${reportCard.top20Picks} · ${reportCard.top20ByChance.toFixed(1)} by chance`
                      : `${reportCard.top20Hits} / ${reportCard.top20Picks}`
                  }
                />
                <SummaryTile
                  label="Make-cut accuracy"
                  value={
                    reportCard.cutAcc != null
                      ? `${formatPct(reportCard.cutAcc)} · ${
                          reportCard.cutBaseRate != null ? formatPct(reportCard.cutBaseRate) : '—'
                        } always-guess`
                      : 'no cut at this event'
                  }
                />
              </div>
              <ProvenanceNote board={archived} n={reportCard.n} />
            </div>
          ) : (
            fieldSummary && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <SummaryTile
                  label="Favorite"
                  value={`${fieldSummary.favorite.player_name} · ${formatPct(fieldSummary.favorite.win_prob)}`}
                />
                <SummaryTile
                  label="Top contender"
                  value={`${fieldSummary.contender.player_name} · ${formatPct(fieldSummary.contender.top_20_prob)}`}
                />
                <SummaryTile
                  label="Safest cut"
                  value={`${fieldSummary.safestCut.player_name} · ${formatPct(fieldSummary.safestCut.make_cut_prob)}`}
                />
                <SummaryTile label="Field" value={`${fieldSummary.size} players`} />
              </div>
            )
          )}

          {/* Controls */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search players…"
              className="w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-tertiary focus:border-accent focus:outline-none sm:w-72"
              aria-label="Search players"
            />
            <div className="flex items-center gap-3">
              {query.trim() && (
                <p className="text-xs text-fg-tertiary">
                  {rows.length} of {boardOutcomes.length} players
                </p>
              )}
              <button
                type="button"
                onClick={() =>
                  downloadBoardCsv(
                    `${(selectedTournament?.name ?? 'leaderboard')
                      .replace(/[^a-z0-9]+/gi, '-')
                      .toLowerCase()}-board.csv`,
                    rows,
                  )
                }
                className="shrink-0 rounded-md border bg-surface px-3 py-1.5 text-xs font-medium text-fg-secondary transition-colors hover:text-fg"
              >
                Export CSV
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border">
            <div className="max-h-[70vh] overflow-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-surface-2 text-left text-xs uppercase tracking-wider text-fg-tertiary">
                    <th className="px-4 py-3 w-12 text-right">#</th>
                    <th className="px-4 py-3">Player</th>
                    {isCompleted && <th className="px-4 py-3 text-right">Finish</th>}
                    {COLUMNS.map((col) => (
                      <th key={col.key} className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className={`inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-fg ${
                            sortKey === col.key ? 'text-fg' : ''
                          }`}
                          aria-label={`Sort by ${col.label}`}
                          title={
                            col.key === 'win_prob'
                              ? 'Win probabilities are intentionally coarse — see the live record above for which markets are currently ahead of the baseline.'
                              : undefined
                          }
                        >
                          {col.label}
                          <span className="w-2 text-[0.6rem]">
                            {sortKey === col.key ? (sortDir === 'desc' ? '▼' : '▲') : ''}
                          </span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {rows.map((o, idx) => (
                    <tr
                      key={o.player_id}
                      className={`transition-colors hover:bg-surface-2 ${
                        idx === 0 ? 'bg-surface-2/60' : 'bg-surface'
                      }`}
                    >
                      <td className="px-4 py-2.5 text-right font-mono text-fg-tertiary">{idx + 1}</td>
                      <td className="px-4 py-2.5 font-medium text-fg">
                        <button
                          type="button"
                          onClick={() => setSelectedPlayerId(o.player_id)}
                          className="text-left hover:text-accent hover:underline"
                        >
                          {o.player_name}
                        </button>
                      </td>
                      {isCompleted && (
                        <td
                          className={`px-4 py-2.5 text-right font-mono text-xs ${
                            o.final_position != null ? 'text-fg' : 'text-fg-tertiary'
                          }`}
                        >
                          {formatFinish(o)}
                        </td>
                      )}
                      {COLUMNS.map((col) => {
                        const value = o[col.key]
                        const max = colMax[col.key]
                        const width = max > 0 ? Math.max((value / max) * 100, 1.5) : 0
                        return (
                          <td key={col.key} className="px-4 py-2.5">
                            <div className="relative flex items-center justify-end">
                              <div
                                className={`pointer-events-none absolute inset-y-[3px] right-0 rounded-sm ${col.barClass}`}
                                style={{ width: `${width}%` }}
                              />
                              <span className={`relative z-[1] font-mono tabular-nums ${col.cellClass}`}>
                                {formatPct(value)}
                              </span>
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {rows.length === 0 && query.trim() && (
            <p className="text-sm text-fg-tertiary">No players match “{query.trim()}”.</p>
          )}
        </>
      )}

      {selectedPlayerId != null && (
        <PlayerDrawer
          playerId={selectedPlayerId}
          outcome={drawerOutcome}
          tournamentName={selectedTournament?.name ?? null}
          board={isCompleted ? (archived?.available ? archived : null) : (predictions ?? null)}
          onClose={() => setSelectedPlayerId(null)}
        />
      )}
    </main>
  )
}
