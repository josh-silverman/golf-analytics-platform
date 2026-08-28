/**
 * TrackRecord — a browsable public record of how Pinpoint's predictions
 * performed, one tournament at a time, back to the earliest pinned board.
 *
 * Deliberately one view, not two: the same content serves a fan skimming and
 * a reviewer checking rigor. Everything here is read from the ledger via the
 * existing archived-board endpoints — nothing is recomputed.
 */

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'

import { TopPicksTable } from '../components/TopPicksTable'
import { useArchivedBoard } from '../lib/api/archivedBoard'
import { useArchivedBoardList } from '../lib/api/archivedBoardList'
import { useForwardTrackRecord } from '../lib/api/forwardTrackRecord'
import {
  CLEARS_TOOLTIP,
  conclusiveLine,
  formatSkill,
  headlineSkillMarkets,
  MARKET_LABELS,
  provenanceBlocks,
  regimeCaveat,
  settlingFooter,
  TOO_EARLY_TOOLTIP,
} from '../lib/forwardRecord'
import { computeReportCard } from '../lib/reportCard'
import { ProvenanceNote, SummaryTile } from './Leaderboard'

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

function formatEventLabel(name: string, startDate: string): string {
  const d = new Date(startDate).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
  return `${name} · ${d}`
}

export function TrackRecord() {
  const { data: events, isLoading: eventsLoading, isError: eventsError } = useArchivedBoardList()
  const { data: trackRecord } = useForwardTrackRecord()
  const [searchParams, setSearchParams] = useSearchParams()

  // Selected week: an explicit pick overrides; otherwise the most recent
  // pinned event (the list is already newest-first). Seeded from the URL so
  // a week is shareable/bookmarkable, matching the Leaderboard's pattern.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const e = searchParams.get('event')
    return e ? Number(e) : null
  })
  const effectiveId = selectedId ?? events?.[0]?.tournament_id ?? null

  useEffect(() => {
    const next = new URLSearchParams()
    if (effectiveId != null) next.set('event', String(effectiveId))
    setSearchParams(next, { replace: true })
  }, [effectiveId, setSearchParams])

  const selectedEvent = events?.find((e) => e.tournament_id === effectiveId) ?? null

  const {
    data: archived,
    isLoading: boardLoading,
    isError: boardError,
  } = useArchivedBoard(effectiveId)

  const reportCard = computeReportCard(archived)

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-10">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">Track Record</h1>
        <p className="max-w-2xl text-sm text-fg-secondary">
          How Pinpoint's predictions performed, one tournament at a time, back to the earliest
          pinned board. Top 20 is the headline market here, consistent with the rest of the site —
          Win is intentionally coarse and not scored on this page.
        </p>

        {eventsLoading && <p className="text-fg-secondary text-sm">Loading events…</p>}

        {eventsError && (
          <p className="text-negative text-sm">Could not load the list of tracked events.</p>
        )}

        {!eventsLoading && events && events.length === 0 && (
          <p className="text-sm text-fg-secondary">
            The record starts once boards are pinned before an event. Nothing has been pinned yet.
          </p>
        )}

        {events && events.length > 0 && (
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
              {events.map((e) => (
                <option key={e.tournament_id} value={e.tournament_id}>
                  {formatEventLabel(e.tournament_name, e.tournament_start_date)}
                </option>
              ))}
            </select>
          </div>
        )}
      </header>

      {events && events.length > 0 && (
        <>
          {boardLoading && <p className="text-fg-secondary text-sm">Loading pinned board…</p>}

          {boardError && (
            <p className="text-negative text-sm">Could not load the pinned board for this event.</p>
          )}

          {archived?.available && !archived.graded && (
            <p className="rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-fg-secondary">
              A board is pinned for {selectedEvent?.tournament_name ?? 'this event'}, but results
              have not settled yet. No report card until it's graded.
            </p>
          )}

          {reportCard && archived && (
            <div className="space-y-4">
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
              <TopPicksTable board={archived} />
            </div>
          )}
        </>
      )}

      {trackRecord?.available && trackRecord.markets.length > 0 && (
        <section className="space-y-3 border-t border-border/70 pt-6">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium text-fg">Overall record</h2>
            {regimeCaveat(trackRecord) && (
              <span
                className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-semibold text-warning"
                title={regimeCaveat(trackRecord) ?? undefined}
              >
                mixed serving configurations
              </span>
            )}
          </div>
          <p className="text-xs text-fg-tertiary">
            Every figure compares the served board against one reference: predicting the field
            average for every player.
          </p>
          <div className="space-y-3">
            {provenanceBlocks(trackRecord).map((b) => {
              const shown = headlineSkillMarkets(b.markets)
              return (
                <div key={b.title} className="text-xs text-fg-secondary">
                  <p className="font-medium text-fg">
                    {b.title} · {b.events} event{b.events === 1 ? '' : 's'}, {b.players} players graded
                  </p>
                  {shown.length > 0 && (
                    <>
                      <p className="mt-0.5">
                        {shown.map((m, i) => (
                          <span key={m.market} className="text-fg-tertiary">
                            {i > 0 && ' · '}
                            {MARKET_LABELS[m.market]}{' '}
                            <span
                              className={`font-mono ${m.clearsBaseline ? 'text-accent' : 'text-fg-tertiary'}`}
                              title={m.clearsBaseline ? CLEARS_TOOLTIP : TOO_EARLY_TOOLTIP}
                            >
                              {formatSkill(m.brier_skill)}
                            </span>
                          </span>
                        ))}
                      </p>
                      <p className="mt-0.5 text-fg-tertiary">{conclusiveLine(shown)}</p>
                    </>
                  )}
                  {b.note && <p className="mt-0.5 text-fg-tertiary">{b.note}</p>}
                </div>
              )
            })}
          </div>
          {settlingFooter(trackRecord) && (
            <p className="text-xs text-fg-tertiary">{settlingFooter(trackRecord)}</p>
          )}
        </section>
      )}
    </main>
  )
}
