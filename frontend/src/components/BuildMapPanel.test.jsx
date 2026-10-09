import { render, screen, fireEvent } from '@testing-library/react'
import { vi, it, expect } from 'vitest'
import BuildMapPanel from './BuildMapPanel'
import axios from 'axios'

vi.mock('axios', () => ({ default: { get: vi.fn() } }))

it('does not fetch telemetry until opened and explains a missing live job', async () => {
    axios.get.mockResolvedValue({ data: { state: 'idle' } })
    render(<BuildMapPanel versionId={3} status={{ state: 'idle' }} title="Programme" t={x => x} />)
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    expect(screen.getByRole('region')).toBeInTheDocument()
    expect(await screen.findByText('build_map_no_job')).toBeInTheDocument()
})

it('uses a text alternative instead of loading the graph on small or reduced-motion displays', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn()})))
    axios.get.mockResolvedValue({data: {events: [], next_cursor: 0, has_more: false, state: 'complete'}})
    render(<BuildMapPanel versionId={3} status={{job_id: 'real', state: 'complete'}} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', {name: 'build_map_open'}))
    expect(await screen.findByText('build_map_text_alternative')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    vi.unstubAllGlobals()
})

it('does not invent a graph for an old completed job without recorded events', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn()})))
    axios.get.mockResolvedValue({data: {events: [], next_cursor: 0, has_more: false, state: 'complete'}})
    render(<BuildMapPanel versionId={3} status={{job_id: 'old', state: 'complete'}} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', {name: 'build_map_open'}))
    expect(await screen.findByText('build_map_no_job')).toBeInTheDocument()
    vi.unstubAllGlobals()
})
