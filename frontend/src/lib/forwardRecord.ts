/**
 * Shared presentation logic for the forward out-of-sample track record.
 *
 * Consumed by the Leaderboard's one-line summary and the Track Record
 * page's aggregate section — both read the same `useForwardTrackRecord`
 * data and need the same market ordering, labels, and framing, so this is
 * one definition rather than two drifting in sync.
 */

import type { ForwardMarketSkill, ForwardTrackRecord } from './api/forwardTrackRecord'

export const MARKET_LABELS: Record<string, string> = {
  make_cut_prob: 'Make cut',
  top_20_prob: 'Top 20',
  top_10_prob: 'Top 10',
  top_5_prob: 'Top 5',
  win_prob: 'Win',
}

// Skill-priority order, matching the Betting Edge market picker: make-cut and
// top-20 carry the most genuine backtest skill, win/top-5 the least.
export const MARKET_ORDER = ['make_cut_prob', 'top_20_prob', 'top_10_prob', 'top_5_prob', 'win_prob']

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
export type DisplayMarketSkill = ForwardMarketSkill & { clearsBaseline: boolean }

export function orderedSkillMarkets(markets: ForwardMarketSkill[]): DisplayMarketSkill[] {
  return [...markets]
    .sort((a, b) => MARKET_ORDER.indexOf(a.market) - MARKET_ORDER.indexOf(b.market))
    .map((m) => ({ ...m, clearsBaseline: m.ci_lower != null && m.ci_lower > 0 }))
}

export const CLEARS_TOOLTIP =
  'Ahead of the field-average baseline by more than the week-to-week swing in this record: the 90% range across events stays above zero.'
export const TOO_EARLY_TOOLTIP =
  'The lead over the field-average baseline is smaller than the week-to-week swing so far, or there are too few events to measure the swing.'

// The aggregate block shows only these two markets, not all five. Make cut
// and Top 20 are the ones that carry real backtest skill and the ones that
// ever clear the baseline in practice (same ranking MARKET_ORDER encodes);
// Top 10, Top 5 and Win are consistently near-zero or too-early on this
// record and just added visual noise as a full five-market row. The other
// three are still in the API response and in MARKET_ORDER for callers that
// want them (the Leaderboard's one-liner does); this constant is specific
// to the aggregate block's reduced view.
export const HEADLINE_MARKETS = ['make_cut_prob', 'top_20_prob']

export function headlineSkillMarkets(markets: ForwardMarketSkill[]): DisplayMarketSkill[] {
  return orderedSkillMarkets(markets.filter((m) => HEADLINE_MARKETS.includes(m.market)))
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

// One line stating which of the shown markets are conclusive at this sample
// size, replacing a "(too early to say)" flag on every non-conclusive
// figure. Stacked per-figure hedging read as uncertainty about everything
// rather than as rigor about specific numbers; one sentence carries the same
// information without repeating the qualifier once per market.
export function conclusiveLine(markets: DisplayMarketSkill[]): string {
  const clears = markets.filter((m) => m.clearsBaseline).map((m) => MARKET_LABELS[m.market])
  if (clears.length === markets.length) {
    return markets.length === 1
      ? `${MARKET_LABELS[markets[0].market]} is conclusive at this sample size.`
      : 'Both markets are conclusive at this sample size.'
  }
  if (clears.length === 0) {
    return markets.length === 1 ? 'Not conclusive yet at this sample size.' : 'Neither market is conclusive yet at this sample size.'
  }
  return `Only ${joinNames(clears)} ${clears.length === 1 ? 'is' : 'are'} conclusive at this sample size.`
}

// One-line summary for the Leaderboard header, linking out to the full
// per-week and aggregate record on the Track Record page. Leads with the
// graded count and the live/reconstructed split (never presents a pooled
// figure as a live record — see docs/ledger.md §"captured and backfilled
// stay distinguishable"), then names which markets currently clear the
// field-average baseline.
export function summarizeTrackRecord(tr: ForwardTrackRecord, markets: DisplayMarketSkill[]): string {
  const captured = tr.events_captured ?? 0
  const backfilled = tr.events_backfilled ?? 0
  const eventWord = `${tr.events} event${tr.events === 1 ? '' : 's'}`
  const opening =
    captured + backfilled === tr.events && tr.events > 0
      ? `${eventWord} graded, ${captured} predicted live and ${backfilled} reconstructed.`
      : `${eventWord} graded.`
  const clears = markets.filter((m) => m.clearsBaseline).map((m) => MARKET_LABELS[m.market])
  if (clears.length === 0) {
    return `${opening} Too early to say whether the board beats the field-average baseline.`
  }
  return `${opening} Ahead of the field-average baseline on ${joinNames(clears)}.`
}

// "About N more events" only means something if the reader knows which pool
// it describes: the combined record reaches the target far sooner than the
// live-capture record, which is rebuilding from a couple of events.
//
// Says "a target we chose, not a statistical threshold" rather than the
// internal phrase "rule-of-thumb sample size": the backend's
// `_MEANINGFUL_EVENTS = 20` is a chosen number worth reading, not a
// calculated significance threshold, and this states that plainly instead
// of naming the internal term for it.
export function settlingFooter(tr: ForwardTrackRecord): string | null {
  const target = tr.events + tr.events_to_meaningful
  const captured = tr.events_captured ?? 0
  const liveMore = Math.max(0, target - captured)
  if (tr.events_to_meaningful <= 0) return null
  if (captured > 0 && liveMore > tr.events_to_meaningful) {
    return (
      `About ${tr.events_to_meaningful} more completed events to reach this page's ${target}-event ` +
      `target (a number we chose, not a statistical threshold). The live-only record needs about ${liveMore} more.`
    )
  }
  return (
    `About ${tr.events_to_meaningful} more completed events to reach this page's ${target}-event ` +
    `target (a number we chose, not a statistical threshold).`
  )
}

// The two provenances render as separate blocks with their own n. Falls back
// to a single pooled block against an older backend that doesn't report the
// split, so a deploy-order skew never blanks the widget.
export type ProvenanceBlockData = {
  title: string
  events: number
  players: number
  markets: ForwardMarketSkill[]
  note: string
}

export function provenanceBlocks(tr: ForwardTrackRecord): ProvenanceBlockData[] {
  const blocks: ProvenanceBlockData[] = []
  const captured = tr.markets_captured ?? []
  const backfilled = tr.markets_backfilled ?? []
  if (captured.length > 0 && (tr.events_captured ?? 0) > 0) {
    const events = tr.events_captured ?? 0
    const allEarly = captured.every((m) => !(m.ci_lower != null && m.ci_lower > 0))
    blocks.push({
      title: 'Recorded before play',
      events,
      players: tr.players_captured ?? 0,
      markets: captured,
      note:
        'Written down before the event began, exactly as the site showed it.' +
        (allEarly
          ? ` ${events} event${events === 1 ? '' : 's'} is not enough to tell skill from luck. Expect these numbers to move.`
          : ''),
    })
  }
  if (backfilled.length > 0 && (tr.events_backfilled ?? 0) > 0) {
    blocks.push({
      title: 'Rebuilt afterwards',
      events: tr.events_backfilled ?? 0,
      players: tr.players_backfilled ?? 0,
      markets: backfilled,
      note:
        'Rebuilt after the fact from the data available before each event. No result information goes in, but later code produced them, so they are not a record of what the site showed those weeks.',
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
// cold-started the whole field but carry the same model version id, so when
// the graded set mixes regimes the aggregate is not measuring one system.
// Say so rather than let the headline number imply otherwise. Returns null
// when every graded board came from the same regime, the normal case over
// time.
export function regimeCaveat(tr: ForwardTrackRecord): string | null {
  const pathA = tr.events_path_a ?? 0
  const cold = tr.events_cold_start_only ?? 0
  const unknown = tr.events_regime_unknown ?? 0
  const parts: string[] = []
  if (cold > 0) parts.push(`${cold} served cold-start only`)
  if (unknown > 0) parts.push(`${unknown} of unrecorded coverage`)
  if (parts.length === 0) return null
  return `Includes ${parts.join(' and ')} out of ${pathA + cold + unknown}, so this pools more than one serving configuration.`
}

export function formatSkill(skill: number): string {
  const sign = skill >= 0 ? '+' : ''
  return `${sign}${(skill * 100).toFixed(1)}%`
}
