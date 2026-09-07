import { useCallback, useEffect, useState } from 'react'

/**
 * A piece of UI state that also lives in the URL query string.
 *
 * Filters that exist only in component state cannot be shared or survive a
 * reload -- "look at this comparison" becomes "open Compare, pick these two
 * agents, then scroll". Keeping them in the URL makes the view addressable.
 *
 * Uses replaceState rather than pushState: changing a filter should not
 * create a history entry, or Back stops meaning "the previous page" and
 * starts meaning "the previous dropdown value".
 */
export function useUrlState(key: string, initial = ''): [string, (next: string) => void] {
  const read = useCallback(() => {
    if (typeof window === 'undefined') return initial
    const params = new URLSearchParams(window.location.search)
    return params.get(key) ?? initial
  }, [key, initial])

  const [value, setValue] = useState<string>(read)

  // Keep in step with Back/Forward and with links that carry the parameter.
  useEffect(() => {
    const sync = () => setValue(read())
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [read])

  const update = useCallback(
    (next: string) => {
      setValue(next)
      if (typeof window === 'undefined') return
      const params = new URLSearchParams(window.location.search)
      if (next) params.set(key, next)
      else params.delete(key)
      const query = params.toString()
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
      )
    },
    [key],
  )

  return [value, update]
}
