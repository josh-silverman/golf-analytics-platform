/**
 * PlayerDrawer — slide-in panel showing a player's current-event outlook and
 * strokes-gained trends, opened from the leaderboard without leaving the page.
 *
 * Mounted only while open (parent renders it conditionally), so its data hooks
 * always have a valid id. Entrance slides in from the right; backdrop click or
 * Escape closes it.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { usePlayer, useRecentRounds } from '../lib/api/players'
import type { PlayerOutcome } from '../lib/api/predictions'
import { PlayerSGTrends } from './PlayerSGTrends'

type ProbKey = 'win_prob' | 'top_5_prob' | 'top_10_prob' | 'top_20_prob' | 'make_cut_prob'

const OUTLOOK_MARKETS: { key: ProbKey; label: string; valueClass: string }[] = [
  { key: 'win_prob', label: 'Win', valueClass: 'text-fg-tertiary' },
  { key: 'top_5_prob', label: 'Top 5', valueClass: 'text-fg' },
  { key: 'top_10_prob', label: 'Top 10', valueClass: 'text-fg' },
  { key: 'top_20_prob', label: 'Top 20', valueClass: 'text-accent' },
  { key: 'make_cut_prob', label: 'Make Cut', valueClass: 'text-fg-secondary' },
]

function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

interface PlayerDrawerProps {
  playerId: number
  outcome: PlayerOutcome | null
  tournamentName: string | null
  onClose: () => void
}

export function PlayerDrawer({ playerId, outcome, tournamentName, onClose }: PlayerDrawerProps) {
  const { data: playerEnv, isLoading } = usePlayer(playerId)
  const { data: roundsEnv } = useRecentRounds(playerId)

  const player = playerEnv?.data
  // API returns most-recent first; reverse so charts read oldest → newest.
  const rounds = roundsEnv ? [...roundsEnv.data].reverse() : []

  // Entrance transition: mount off-screen, then slide in next frame.
  const [shown, setShown] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(id)
  }, [])

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      {/* backdrop */}
      <div
        className={`absolute inset-0 bg-black/50 transition-opacity duration-200 ${
          shown ? 'opacity-100' : 'opacity-0'
        }`}
        onClick={onClose}
      />

      {/* panel */}
      <div
        className={`relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l bg-background shadow-2xl transition-transform duration-200 ${
          shown ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div className="space-y-6 p-6">
          {/* header */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">
                {player?.full_name ?? 'Player'}
              </h2>
              {player && (
                <p className="mt-0.5 text-sm text-fg-secondary">
                  <span className="font-mono text-fg">{player.country}</span>
                  {player.turned_pro ? <> · turned pro {player.turned_pro}</> : null}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md border px-2 py-1 text-sm text-fg-secondary hover:text-fg"
            >
              ✕
            </button>
          </div>

          {/* current-event outlook */}
          {outcome && (
            <section className="space-y-2">
              <p className="text-xs uppercase tracking-wider text-fg-tertiary">
                {tournamentName ? `${tournamentName} outlook` : 'Current outlook'}
              </p>
              <div className="grid grid-cols-5 gap-2">
                {OUTLOOK_MARKETS.map((m) => (
                  <div key={m.key} className="rounded-lg border bg-surface p-2 text-center">
                    <p className="text-[10px] uppercase tracking-wider text-fg-tertiary">{m.label}</p>
                    <p className={`mt-0.5 font-mono text-sm font-semibold tabular-nums ${m.valueClass}`}>
                      {formatPct(outcome[m.key])}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* SG trends */}
          {isLoading ? (
            <p className="text-fg-secondary">Loading trends…</p>
          ) : (
            <PlayerSGTrends rounds={rounds} />
          )}

          <Link
            to={`/players/${playerId}`}
            className="inline-block text-sm text-accent hover:underline"
          >
            Open full profile →
          </Link>
        </div>
      </div>
    </div>
  )
}
