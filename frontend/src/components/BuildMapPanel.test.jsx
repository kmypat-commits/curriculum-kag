import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, it, expect } from 'vitest'
import BuildMapPanel from './BuildMapPanel'
import axios from 'axios'

vi.mock('axios', () => ({ default: { get: vi.fn() } }))

it('uses the actual event stream state while the slower status poll still says queued', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', events: [], next_cursor: 0, has_more: false } })
    render(<BuildMapPanel versionId={3} status={{ state: 'queued', job_id: 'real' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'build_map_show_graph' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'build_map_motion' }))
    await waitFor(() => expect(screen.getByRole('region')).toHaveClass('has-motion'))
    vi.unstubAllGlobals()
})

it('pauses opted-in light flow outside the viewport and after completion', async () => {
    let observeVisibility
    vi.stubGlobal('IntersectionObserver', class {
        constructor(callback) { observeVisibility = callback }
        observe() {}
        disconnect() {}
    })
    axios.get.mockResolvedValue({ data: { state: 'idle' } })
    const { rerender } = render(<BuildMapPanel versionId={3} status={{ state: 'running' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'build_map_motion' }))
    expect(screen.getByRole('region')).not.toHaveClass('has-motion')
    const { act } = await import('@testing-library/react')
    act(() => observeVisibility([{ isIntersecting: true }]))
    expect(screen.getByRole('region')).toHaveClass('has-motion')
    act(() => observeVisibility([{ isIntersecting: false }]))
    expect(screen.getByRole('region')).not.toHaveClass('has-motion')
    act(() => observeVisibility([{ isIntersecting: true }]))
    rerender(<BuildMapPanel versionId={3} status={{ state: 'complete' }} title="Programme" t={x => x} />)
    expect(screen.getByRole('region')).not.toHaveClass('has-motion')
    vi.unstubAllGlobals()
})

it('shows the programme identity with motion off until explicitly enabled', async () => {
    axios.get.mockResolvedValue({ data: { state: 'idle' } })
    render(<BuildMapPanel versionId={3} status={{ state: 'idle' }} title="Wood engineering" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    expect(screen.getByText('Wood engineering')).toBeInTheDocument()
    const motion = screen.getByRole('checkbox', { name: 'build_map_motion' })
    expect(motion).not.toBeChecked()
    fireEvent.click(motion)
    expect(motion).toBeChecked()
})

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
