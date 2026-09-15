/**
 * A bundle name reaches three URLs, so it is validated once before any of them.
 *
 * CodeQL flagged `web/src/pages/operations.tsx` with `js/xss-through-dom`: DOM
 * text -- the value of a `<select>` -- interpolated into an `href`. The options
 * come from published data the app itself rendered, so the practical risk was
 * low, and "low" is not an argument anybody should have to make about a link.
 *
 * Bundle directories are named by `bundle_slug` in `tooltrace/artifacts/
 * bundles.py`. Anything that does not match that shape did not come from this
 * project, and is treated as no selection at all.
 */

import { describe, expect, it } from 'vitest'
import { assetUrl, safeBundleName } from '../api'

describe('bundle names that are real', () => {
  it('accepts the shape the writer actually produces', () => {
    const real =
      'failure-recovery-retry-after-tool-failure-scripted-2bfd3ca9a484-retry-after-tool-failure-0.tooltrace'
    expect(safeBundleName(real)).toBe(real)
  })

  it('accepts dots, dashes and underscores', () => {
    expect(safeBundleName('a_b-c.d')).toBe('a_b-c.d')
  })
})

describe('bundle names that are not', () => {
  it('refuses path traversal', () => {
    // The one that could repoint a link at another path on the same origin.
    expect(safeBundleName('../../etc/passwd')).toBeNull()
    expect(safeBundleName('a/../b')).toBeNull()
  })

  it('refuses a scheme', () => {
    expect(safeBundleName('javascript:alert(1)')).toBeNull()
    expect(safeBundleName('https://evil.test/x')).toBeNull()
  })

  it('refuses a query or fragment that would escape the path', () => {
    expect(safeBundleName('good?x=1')).toBeNull()
    expect(safeBundleName('good#frag')).toBeNull()
  })

  it('refuses markup', () => {
    expect(safeBundleName('<img src=x onerror=alert(1)>')).toBeNull()
  })

  it('refuses whitespace and the empty string', () => {
    expect(safeBundleName('')).toBeNull()
    expect(safeBundleName('  ')).toBeNull()
    expect(safeBundleName('a b')).toBeNull()
    expect(safeBundleName(null)).toBeNull()
    expect(safeBundleName(undefined)).toBeNull()
  })

  it('refuses a leading dot, so a dotfile cannot be requested', () => {
    expect(safeBundleName('.git')).toBeNull()
  })
})

describe('what a validated name builds', () => {
  it('stays under the published bundles path', () => {
    const url = assetUrl(`bundles/${safeBundleName('demo-1.tooltrace')}/trace.json`)
    expect(url).toContain('bundles/demo-1.tooltrace/trace.json')
    expect(url).not.toContain('..')
  })
})
