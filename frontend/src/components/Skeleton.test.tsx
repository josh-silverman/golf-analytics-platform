import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SkeletonTable, SkeletonText } from './Skeleton'

describe('Skeleton', () => {
  it('renders a labelled table placeholder with the requested row count', () => {
    const { container } = render(
      <SkeletonTable rows={6} cols={4} caption="Loading predictions…" />,
    )
    expect(screen.getByRole('status', { name: /loading predictions/i })).toBeInTheDocument()
    // header row + 6 body rows
    expect(container.querySelectorAll('.divide-y > div')).toHaveLength(6)
  })

  it('renders the requested number of text lines', () => {
    const { container } = render(<SkeletonText lines={4} />)
    expect(container.querySelectorAll('span.block')).toHaveLength(4)
  })
})
