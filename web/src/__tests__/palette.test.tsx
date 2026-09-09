import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { CommandPalette, filterCommands, score, type Command } from '../palette'

const COMMANDS: Command[] = [
  { id: '/leaderboard', label: 'Leaderboard', group: 'Explore', to: '/leaderboard' },
  { id: '/workspace/experiments', label: 'Experiments', group: 'Workspace', to: '/workspace/experiments' },
  { id: '/traces', label: 'Traces', group: 'Analyze', to: '/traces' },
]

describe('scoring', () => {
  it('ranks a contiguous match above a scattered one', () => {
    const contiguous = score('lead', 'Leaderboard Explore')
    const scattered = score('lbd', 'Leaderboard Explore')
    expect(contiguous).not.toBeNull()
    expect(scattered).not.toBeNull()
    expect(contiguous as number).toBeLessThan(scattered as number)
  })

  it('matches a subsequence across words so "wsx" finds Workspace Experiments', () => {
    expect(score('wsx', 'Workspace Experiments')).not.toBeNull()
  })

  it('finds a command whichever order its label and group concatenate in', () => {
    // The real command is label "Experiments", group "Workspace", so the
    // label-first haystack reads "Experiments Workspace" and "wsx" cannot
    // thread through it. Matching must not depend on that accident.
    expect(score('wsx', 'Experiments Workspace')).toBeNull()
    const found = filterCommands(COMMANDS, 'wsx')
    expect(found.map((c) => c.label)).toContain('Experiments')
  })

  it('returns null when a character is absent', () => {
    expect(score('zzz', 'Leaderboard')).toBeNull()
  })

  it('an empty query keeps every command', () => {
    expect(filterCommands(COMMANDS, '')).toHaveLength(3)
    expect(filterCommands(COMMANDS, '   ')).toHaveLength(3)
  })

  it('filters by group as well as label', () => {
    const found = filterCommands(COMMANDS, 'workspace')
    expect(found[0].label).toBe('Experiments')
  })
})

function renderPalette(onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <CommandPalette open onClose={onClose} commands={COMMANDS} />
    </MemoryRouter>,
  )
  return onClose
}

describe('command palette', () => {
  it('renders nothing while closed', () => {
    render(
      <MemoryRouter>
        <CommandPalette open={false} onClose={vi.fn()} commands={COMMANDS} />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('exposes the combobox/listbox pattern a screen reader needs', async () => {
    renderPalette()
    const input = await screen.findByRole('combobox')
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-controls', 'palette-list')
    // The first option is active on open, and named by aria-activedescendant.
    expect(input).toHaveAttribute('aria-activedescendant', 'cmd-/leaderboard')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getAllByRole('option')).toHaveLength(3)
  })

  it('moves the active descendant with the arrow keys and wraps', async () => {
    const user = userEvent.setup()
    renderPalette()
    const input = await screen.findByRole('combobox')
    await user.click(input)
    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', 'cmd-/workspace/experiments')
    await user.keyboard('{ArrowUp}{ArrowUp}')
    expect(input).toHaveAttribute('aria-activedescendant', 'cmd-/traces')
  })

  it('filters as you type and reports an empty result honestly', async () => {
    const user = userEvent.setup()
    renderPalette()
    const input = await screen.findByRole('combobox')
    await user.type(input, 'trac')
    // Subsequence matching is deliberately permissive -- "trac" also threads
    // through "Experiments Workspace" -- so what matters is that the
    // contiguous match ranks first, not that everything else is excluded.
    expect(screen.getAllByRole('option')[0]).toHaveTextContent('Traces')
    await user.clear(input)
    await user.type(input, 'qqqq')
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
    expect(screen.getByText(/no matches for/i)).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const onClose = renderPalette()
    await user.click(await screen.findByRole('combobox'))
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('runs an action command instead of navigating', async () => {
    const user = userEvent.setup()
    const run = vi.fn()
    const onClose = vi.fn()
    render(
      <MemoryRouter>
        <CommandPalette
          open
          onClose={onClose}
          commands={[{ id: 'theme', label: 'Theme: System', group: 'Appearance', run }]}
        />
      </MemoryRouter>,
    )
    await user.click(await screen.findByRole('combobox'))
    await user.keyboard('{Enter}')
    expect(run).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalled()
  })
})
