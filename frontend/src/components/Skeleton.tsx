/**
 * Loading placeholders shaped like the content they stand in for, so a slow
 * first load (a cold backend can take ~40s) settles into the real layout
 * instead of replacing a spinner with a full page. The shimmer collapses to
 * a static block under reduced-motion (handled in index.css).
 */

function Bar({ className = '' }: { className?: string }) {
  return (
    <span
      className={`relative block overflow-hidden rounded bg-surface-2 ${className}`}
    >
      <span className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-fg/[0.06] to-transparent" />
    </span>
  )
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Bar key={i} className={`h-3.5 ${i === lines - 1 ? 'w-2/5' : 'w-full'}`} />
      ))}
    </div>
  )
}

export function SkeletonTable({
  rows = 10,
  cols = 5,
  caption,
}: {
  rows?: number
  cols?: number
  caption?: string
}) {
  return (
    <div className="space-y-3" role="status" aria-label={caption ?? 'Loading table'}>
      {caption && <p className="text-sm text-fg-secondary">{caption}</p>}
      <div className="overflow-hidden rounded-lg border">
        <div className="flex gap-4 border-b bg-surface-2 px-4 py-3">
          <Bar className="h-3 w-6" />
          <Bar className="h-3 w-32" />
          <div className="flex flex-1 justify-end gap-6">
            {Array.from({ length: cols }).map((_, i) => (
              <Bar key={i} className="h-3 w-10" />
            ))}
          </div>
        </div>
        <div className="divide-y">
          {Array.from({ length: rows }).map((_, r) => (
            <div key={r} className="flex items-center gap-4 bg-surface px-4 py-3">
              <Bar className="h-3 w-6" />
              <Bar className={`h-3.5 ${r % 3 === 0 ? 'w-44' : 'w-28'}`} />
              <div className="flex flex-1 justify-end gap-6">
                {Array.from({ length: cols }).map((_, i) => (
                  <Bar key={i} className="h-3 w-10" />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
