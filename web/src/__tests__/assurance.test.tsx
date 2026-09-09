import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { EvidenceDossier, SecurityPosture } from '../api'
import { EvidencePage, SecurityPosturePage } from '../pages/assurance'

/**
 * Both of these pages are more dangerous than the rest of the dashboard, and the
 * danger is the same in both: a number produced by a machine and rendered in a
 * clean layout borrows authority it has not earned.
 *
 * An evidence dossier that reads as a compliance verdict would be actively
 * misleading in a domain carrying €35M penalties. A 0% attack-success rate over
 * four attempts rendered as a green tick would be a claim about an agent's
 * safety that four attempts cannot support — the Wilson upper bound is near 50%.
 *
 * So most of what follows tests what these pages *refuse* to say.
 */

const RATE = {
  attempts: 4,
  attacks_succeeded: 0,
  attack_success_rate: 0,
  ci95: [0, 0.4899] as [number, number],
  sample_is_small: true,
}

const POSTURE: SecurityPosture = {
  generated_at: '2026-09-09T00:00:00Z',
  ...RATE,
  by_class: {
    exfiltration: { ...RATE, attempts: 2 },
    direct_harm: { ...RATE, attempts: 2 },
  },
  by_agent: { scripted: RATE },
  runs: [
    {
      bundle: 'b-exfil',
      task_id: 'security/indirect-injection-exfiltration',
      agent: 'scripted',
      created_at: '2026-09-09T00:00:00Z',
      attack_succeeded: false,
      attack_class: 'exfiltration',
      vector: 'indirect_prompt_injection',
      owasp: 'LLM01 Prompt Injection; LLM02 Sensitive Information Disclosure',
    },
    {
      bundle: 'b-harm',
      task_id: 'security/indirect-injection-direct-harm',
      agent: 'scripted',
      created_at: '2026-09-09T01:00:00Z',
      attack_succeeded: true,
      attack_class: 'direct_harm',
      vector: 'indirect_prompt_injection',
      owasp: 'LLM01 Prompt Injection; excessive agency',
    },
  ],
}

const DOSSIER: EvidenceDossier = {
  schema: 'tooltrace-evidence/1',
  generated_at: '2026-09-09T00:00:00Z',
  statement:
    'This dossier is evidence, not a compliance determination. Whether an AI system meets its legal obligations is an organisational determination.',
  runs: [
    {
      bundle: 'b1',
      verified: true,
      verification_problems: [],
      task_id: 'p/one',
      task_version: '1.0.0',
      agent: 'scripted',
      run_id: 'r0',
      success: true,
      score: 1,
      failure_reason: null,
      created_at: '2026-09-09T00:00:00Z',
      framework_version: '0.3.0',
      compatibility_key: 'protocol=1',
      trust_state: 'LOCAL',
      manifest_sha256: 'a'.repeat(64),
    },
    {
      bundle: 'b2',
      verified: false,
      verification_problems: ['checksum mismatch: result.json'],
      task_id: 'p/two',
      task_version: '1.0.0',
      agent: 'scripted',
      run_id: 'r1',
      success: false,
      score: 0,
      failure_reason: 'execution',
      created_at: '2026-09-09T01:00:00Z',
      framework_version: '0.3.0',
      compatibility_key: 'protocol=1',
      trust_state: 'LOCAL',
      manifest_sha256: 'b'.repeat(64),
    },
  ],
  obligations: [
    {
      article: 'Article 9',
      title: 'Risk management system',
      evidence: ['2 recorded run(s)'],
      gaps: ['A benchmark is not a hazard analysis of your deployment.'],
    },
    {
      article: 'Article 15',
      title: 'Accuracy, robustness and cybersecurity',
      evidence: ['Measured success rate 0.500 over 2 run(s)'],
      gaps: ['Sample size is 2.'],
    },
  ],
  hash_chain: [
    { bundle: 'b1', previous: '0'.repeat(64), entry: 'c'.repeat(64) },
    { bundle: 'b2', previous: 'c'.repeat(64), entry: 'd'.repeat(64) },
  ],
  chain_head: 'd'.repeat(64),
}

function mock(file: string, body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.includes(file))
        return Promise.resolve(new Response(JSON.stringify(body), { status }))
      return Promise.resolve(new Response('not found', { status: 404 }))
    }),
  )
}

const renderPage = (element: React.ReactElement) =>
  render(<MemoryRouter>{element}</MemoryRouter>)

// --- security posture -------------------------------------------------------

describe('security posture', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('never shows a rate without its attempt count', async () => {
    mock('security.json', POSTURE)
    renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(screen.getAllByText(/0 of 4 attempts/).length).toBeGreaterThan(0)
  })

  it('shows the confidence interval, because the bound is the finding', async () => {
    mock('security.json', POSTURE)
    renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(screen.getAllByText(/0\.0%–49\.0%/).length).toBeGreaterThan(0)
  })

  it('says plainly that a handful of attempts is not a measurement', async () => {
    mock('security.json', POSTURE)
    renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(screen.getAllByText(/Fewer than 30 attempts/).length).toBeGreaterThan(0)
  })

  it('refuses to generalise from the payloads it ran', async () => {
    mock('security.json', POSTURE)
    renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(
      screen.getByText(/not an attack that cannot succeed/i, { exact: false }),
    ).toBeInTheDocument()
  })

  it('never claims an agent is secure', async () => {
    mock('security.json', POSTURE)
    const { container } = renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(container.textContent).not.toMatch(/\b(is secure|fully secure|immune|safe from)\b/i)
  })

  it('carries each verdict in words, not only in colour', async () => {
    mock('security.json', POSTURE)
    renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(screen.getByText('resisted')).toBeInTheDocument()
    expect(screen.getByText('succeeded')).toBeInTheDocument()
  })

  it('breaks the rate down per attack class', async () => {
    mock('security.json', POSTURE)
    renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(screen.getByRole('heading', { name: /exfiltration/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /direct harm/i })).toBeInTheDocument()
  })

  it('says there is nothing to show rather than showing a zero', async () => {
    // The dangerous alternative: an empty dataset rendering as 0% attack
    // success, which reads as a perfectly secure agent nobody attacked.
    mock('security.json', { ...POSTURE, attempts: 0, attack_success_rate: null, runs: [] })
    const { container } = renderPage(<SecurityPosturePage />)
    await screen.findByRole('heading', { level: 1, name: /security posture/i })
    expect(screen.getByText(/No adversarial runs in this dataset/i)).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/0\.0%/)
  })

  it('treats a missing index as an older dataset, not a crash', async () => {
    mock('nothing-matches', {}, 404)
    renderPage(<SecurityPosturePage />)
    expect(await screen.findByText(/carries no security index/i)).toBeInTheDocument()
  })
})

// --- evidence dossier -------------------------------------------------------

describe('evidence dossier', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('leads with the disclaimer, before any number', async () => {
    mock('evidence.json', DOSSIER)
    const { container } = renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    const text = container.textContent ?? ''
    expect(text.indexOf('not a compliance determination')).toBeLessThan(
      text.indexOf('Runs recorded'),
    )
  })

  it('never asserts compliance', async () => {
    mock('evidence.json', DOSSIER)
    const { container } = renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    expect(container.textContent).not.toMatch(
      /\b(is compliant|are compliant|fully compliant|compliance achieved|certified)\b/i,
    )
  })

  it('gives gaps the same prominence as evidence', async () => {
    // Not a collapsed <details>, not a footnote: a sibling column with its own
    // heading. Folding the gaps away would turn the dossier into the claim it
    // exists to avoid making.
    mock('evidence.json', DOSSIER)
    renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    expect(screen.getAllByText(/Not evidenced here/i)).toHaveLength(DOSSIER.obligations.length)
    expect(screen.queryByRole('group')).toBeNull()
  })

  it('states every obligation gap', async () => {
    mock('evidence.json', DOSSIER)
    renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    for (const obligation of DOSSIER.obligations) {
      for (const gap of obligation.gaps) {
        expect(screen.getByText(gap)).toBeInTheDocument()
      }
    }
  })

  it('surfaces an unverified bundle instead of quietly dropping it', async () => {
    // The bundle a reviewer most needs to see is the one that failed its
    // checksum. Hiding it would be the opposite of evidence.
    mock('evidence.json', DOSSIER)
    renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    expect(screen.getByText(/failed checksum verification/i)).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('NO')).toBeInTheDocument()
  })

  it('describes checksums as tamper-evident, not tamper-proof', async () => {
    mock('evidence.json', DOSSIER)
    renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    expect(screen.getByText(/tamper-/)).toBeInTheDocument()
    expect(screen.getByText(/do not establish who produced a bundle/i)).toBeInTheDocument()
  })

  it('shows the chain head so a reader can compare it with their own copy', async () => {
    mock('evidence.json', DOSSIER)
    renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    expect(screen.getByText(`${'d'.repeat(12)}…`)).toBeInTheDocument()
  })

  it('links each run to its own bundle', async () => {
    mock('evidence.json', DOSSIER)
    renderPage(<EvidencePage />)
    await screen.findByRole('heading', { level: 1, name: /evidence/i })
    expect(screen.getByRole('link', { name: 'r0' })).toHaveAttribute('href', '/results/b1')
  })

  it('treats a missing dossier as an older dataset, not a crash', async () => {
    mock('nothing-matches', {}, 404)
    renderPage(<EvidencePage />)
    expect(await screen.findByText(/carries no evidence dossier/i)).toBeInTheDocument()
  })
})
