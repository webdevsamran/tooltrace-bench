import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Command palette (Cmd/Ctrl-K).
 *
 * This replaces a search box that never searched: it wrote the query into the
 * URL hash and nothing read it back, so typing in it did nothing on any page.
 * A palette is the honest version of that affordance — it can actually reach
 * every route, and it collapses a navigation surface that had grown to
 * twenty-nine always-visible links into one keystroke.
 *
 * Accessibility is the combobox/listbox pattern rather than a div soup: the
 * input owns `aria-activedescendant` and the list owns the options, so a
 * screen reader announces the highlighted item as the arrow keys move. The
 * axe suite is a CI gate here, so this has to be right rather than close.
 */

export interface Command {
  id: string
  label: string
  group: string
  /** Navigate here, or run an action. Exactly one is set. */
  to?: string
  run?: () => void
  keywords?: string
}

/**
 * Subsequence match, so "wsx" finds "Workspace Experiments".
 * Returns a score (lower is better) or null when it does not match at all.
 */
export function score(query: string, text: string): number | null {
  if (!query) return 0
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  const direct = t.indexOf(q)
  if (direct >= 0) return direct // contiguous matches rank above scattered ones
  let ti = 0
  let gaps = 0
  for (const ch of q) {
    const next = t.indexOf(ch, ti)
    if (next < 0) return null
    gaps += next - ti
    ti = next + 1
  }
  return 1000 + gaps
}

/**
 * Candidate haystacks for one command.
 *
 * A subsequence match over a single concatenated string is order-dependent:
 * with `label + group` the entry for Experiments reads "Experiments
 * Workspace", and "wsx" cannot thread through it because no `x` follows the
 * `s` of Workspace. Reversed, it matches. Scoring against both orders removes
 * that accident — the user should not have to guess which word we put first.
 */
function haystacks(command: Command): string[] {
  const keywords = command.keywords ? ` ${command.keywords}` : ''
  return [
    `${command.label}${keywords}`,
    `${command.label} ${command.group}${keywords}`,
    `${command.group} ${command.label}${keywords}`,
  ]
}

export function filterCommands(commands: Command[], query: string): Command[] {
  const q = query.trim()
  if (!q) return commands
  const scored: [number, Command][] = []
  for (const command of commands) {
    let best: number | null = null
    for (const hay of haystacks(command)) {
      const s = score(q, hay)
      if (s !== null && (best === null || s < best)) best = s
    }
    if (best !== null) scored.push([best, command])
  }
  return scored.sort((a, b) => a[0] - b[0]).map(([, c]) => c)
}

export function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean
  onClose: () => void
  commands: Command[]
}) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const results = useMemo(() => filterCommands(commands, query), [commands, query])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      // Focus after paint so the dialog exists before we move focus into it.
      const id = requestAnimationFrame(() => inputRef.current?.focus())
      return () => cancelAnimationFrame(id)
    }
    return undefined
  }, [open])

  useEffect(() => setActive(0), [query])

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    const el = listRef.current?.children[active] as HTMLElement | undefined
    // Guarded: jsdom (and any non-browser host) has no scrollIntoView, and
    // scrolling is a nicety that must never break keyboard navigation.
    if (typeof el?.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' })
  }, [active])

  const choose = useCallback(
    (command: Command | undefined) => {
      if (!command) return
      onClose()
      if (command.run) command.run()
      else if (command.to) navigate(command.to)
    },
    [navigate, onClose],
  )

  if (!open) return null

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (results.length ? (i + 1) % results.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      choose(results[active])
    }
  }

  const activeId = results[active] ? `cmd-${results[active].id}` : undefined

  return (
    <div
      className="palette-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          aria-label="Search pages and commands"
          placeholder="Jump to a page or run a command…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {results.length === 0 ? (
          <p className="palette-empty">No matches for “{query}”.</p>
        ) : (
          <ul className="palette-list" id="palette-list" role="listbox" ref={listRef}>
            {results.map((command, i) => (
              <li
                key={command.id}
                id={`cmd-${command.id}`}
                role="option"
                aria-selected={i === active}
                className="palette-item"
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(command)
                }}
              >
                <span>{command.label}</span>
                <span className="group">{command.group}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/** Opens on Cmd/Ctrl-K anywhere except while typing in a field. */
export function usePaletteHotkey(onOpen: () => void) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        onOpen()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onOpen])
}
