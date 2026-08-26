import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Heatmap, Histogram, LineChart, Ring, Scatter } from '../charts'
import { VirtualList } from '../components'
import { validateTaskDraft } from '../pages/workspace2'

describe('charts', () => {
  it('LineChart exposes an accessible label and series legend', () => {
    render(
      <LineChart
        series={[{ name: 'scripted', points: [{ x: 1, y: 0.5 }, { x: 2, y: 0.9 }] }]}
        xLabel="runs"
        yLabel="success rate"
      />,
    )
    expect(screen.getByRole('img', { name: /success rate by runs/i })).toBeInTheDocument()
    expect(screen.getByText('scripted')).toBeInTheDocument()
  })

  it('Histogram labels bins accessibly', () => {
    render(<Histogram bins={[2, 5]} labels={['<1ms', '<2ms']} xLabel="latency" />)
    expect(screen.getByRole('img', { name: /histogram \(latency\)/i })).toBeInTheDocument()
  })

  it('Scatter renders points with titles', () => {
    render(<Scatter points={[{ x: 10, y: 1, label: 'agent-a' }]} xLabel="cost" yLabel="score" />)
    expect(screen.getByRole('img', { name: /score vs cost: 1 points/i })).toBeInTheDocument()
  })

  it('Heatmap summarizes cells in its accessible name', () => {
    render(<Heatmap rows={['fileops']} cols={['scripted']} cells={[0.75]} rowLabel="domain success" />)
    expect(screen.getByRole('img', { name: /fileops: scripted=0\.75/i })).toBeInTheDocument()
  })

  it('Ring shows percentage in its label', () => {
    render(<Ring value={0.42} label="utilization" />)
    expect(screen.getByRole('img', { name: /utilization: 42%/i })).toBeInTheDocument()
  })
})

describe('VirtualList', () => {
  it('renders only a windowed slice of large collections', () => {
    const items = Array.from({ length: 5000 }, (_, i) => i)
    render(
      <VirtualList items={items} itemHeight={24} height={240} ariaLabel="events" render={(n) => <div>item-{n}</div>} />,
    )
    // Windowed: far fewer nodes than the full collection.
    expect(screen.getAllByText(/^item-\d+$/).length).toBeLessThan(40)
    expect(screen.queryByText('item-4999')).not.toBeInTheDocument()
  })
})

describe('validateTaskDraft (authoring studio pre-check)', () => {
  it('flags missing required fields as errors', () => {
    const issues = validateTaskDraft('objective: do something\nassertions: []')
    expect(issues.some((i) => i.level === 'error' && i.message.includes('id'))).toBe(true)
    expect(issues.some((i) => i.level === 'error' && i.message.includes('version'))).toBe(true)
  })

  it('warns on uncontrolled network and judge scoring', () => {
    const yaml = `id: p/x
version: 1.0.0
objective: fetch http://example.invalid via curl and let the model judge
assertions:
  - type: llm_score`
    const issues = validateTaskDraft(yaml)
    expect(issues.some((i) => i.level === 'warn' && i.message.includes('network'))).toBe(true)
    expect(issues.some((i) => i.level === 'warn' && i.message.toLowerCase().includes('judge'))).toBe(true)
  })

  it('accepts a clean deterministic draft with no errors', () => {
    const yaml = `id: p/ok
version: 1.0.0
objective: replace FOO with BAR
network_policy: disabled
deterministic_seed: 7
cleanup: remove temp files
assertions:
  - type: file_contains`
    expect(validateTaskDraft(yaml).filter((i) => i.level === 'error')).toHaveLength(0)
  })

  it('rejects empty drafts', () => {
    expect(validateTaskDraft('')).toEqual([{ level: 'error', message: 'Task draft is empty.' }])
  })
})
