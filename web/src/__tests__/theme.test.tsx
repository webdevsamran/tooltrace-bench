/**
 * The theme is decided in two places, and they have to agree.
 *
 * `useTheme` in `App.tsx` reads `prefers-color-scheme` and stamps `data-theme`
 * on the root — correct, and one turn too late. It runs in an effect, so the
 * first paint happens with the attribute unset and a system-dark user watches a
 * white page flash to dark.
 *
 * The fix is four lines of blocking script in `index.html` that stamp the same
 * attribute before the body renders. Which means the same rule is now written
 * twice, in two languages, in two files — so a change to one silently breaks
 * the other, and the break is invisible to everyone whose OS is set to light.
 *
 * That is what this file is for. It does not test that the flash is gone (no
 * unit test can see a paint); it tests that the two copies still say the same
 * thing, which is the part that rots.
 *
 * The alternative was duplicating the dark palette into a
 * `prefers-color-scheme` block — forty custom properties, of which the first
 * attempt copied eight, producing a half-dark first paint that is worse than
 * the flash.
 */

import { describe, expect, it } from 'vitest'

// `?raw` rather than `node:fs`: this project's web tsconfig has no `@types/node`
// -- deliberately, it is a browser bundle -- and adding them so a test could
// call `readFileSync` would put Node globals in scope for every file in `src`.
// Vite resolves these at transform time, so a renamed file fails to compile
// here instead of silently reading an empty string.
//
// The stylesheet is not read here at all. Vitest leaves CSS unprocessed by
// default and its stub answers with an empty string -- but only once some other
// file in the run has already pulled the module in, so an assertion against it
// passed alone and failed in the suite. An order-dependent result is the one
// thing `src/test-setup.ts` already argues nobody can act on. The two claims
// that needed the stylesheet moved to
// `tests/test_theme_stamp_has_something_to_select.py`, where reading a file is
// a file read.
import APP from '../App.tsx?raw'
import INDEX from '../../index.html?raw'

describe('the pre-paint stamp', () => {
  it('exists at all', () => {
    expect(INDEX).toContain('documentElement.dataset.theme')
  })

  it('runs before the module that renders the app', () => {
    // Below it, the script would run after the paint it exists to precede.
    const stamp = INDEX.indexOf('documentElement.dataset.theme')
    const app = INDEX.indexOf('src/main.tsx')
    expect(stamp).toBeGreaterThan(-1)
    expect(app).toBeGreaterThan(stamp)
  })

  it('is not deferred or a module, either of which would make it non-blocking', () => {
    const tag = INDEX.slice(INDEX.lastIndexOf('<script', INDEX.indexOf('dataset.theme')))
    const opening = tag.slice(0, tag.indexOf('>'))
    expect(opening).not.toContain('defer')
    expect(opening).not.toContain('async')
    expect(opening).not.toContain('type="module"')
  })

  it('reads the key the hook writes', () => {
    // A renamed key means the stamp restores a theme nobody chose.
    expect(INDEX).toContain("'ttb-theme'")
    expect(APP).toContain("'ttb-theme'")
  })

  it('accepts exactly the three choices the hook accepts', () => {
    for (const choice of ['light', 'dark', 'system']) {
      expect(INDEX).toContain(`'${choice}'`)
      expect(APP).toContain(`'${choice}'`)
    }
  })

  it('resolves "system" against the same media query the hook watches', () => {
    expect(INDEX).toContain('prefers-color-scheme: dark')
    expect(APP).toContain('prefers-color-scheme: dark')
  })

  it('survives a browser that refuses localStorage', () => {
    // Private mode throws on read. Without the catch, the whole page is blank.
    const stamp = INDEX.slice(INDEX.indexOf('dataset.theme') - 800, INDEX.indexOf('</script>'))
    expect(stamp).toContain('try')
    expect(stamp).toContain('catch')
  })
})
