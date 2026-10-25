import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { vi, it, expect } from 'vitest'
import BuildMapPanel from './BuildMapPanel'
import axios from 'axios'
import userEvent from '@testing-library/user-event'

vi.mock('axios', () => ({ default: { get: vi.fn() } }))

it('opens a new build immediately with the actual outcomes before candidates arrive', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', events: [], next_cursor: 0, has_more: false } })
    const { container, rerender } = render(<BuildMapPanel autoOpen versionId={3}
        status={{ job_id: 'new', state: 'queued', stage: 'epvo_repository' }} title="Programme" t={x => x}
        learningOutcomes={[{ lo_code: 'LO1', lo_text: 'Design safe structures' }, { lo_code: 'LO2', lo_text: 'Assess materials' }]} />)
    const region = await screen.findByRole('region')
    expect(within(screen.getByRole('img')).getByRole('button', { name: 'LO1' })).toBeInTheDocument()
    expect(within(screen.getByRole('img')).getByRole('button', { name: 'LO2' })).toBeInTheDocument()
    expect(container.querySelectorAll('.lab-node[data-reveal-step="2"]')).toHaveLength(0)
    expect(container.querySelector('.is-current')).toHaveAttribute('aria-current', 'step')
    fireEvent.click(within(region).getByRole('button', { name: 'build_map_close' }))
    rerender(<BuildMapPanel autoOpen versionId={3} status={{ job_id: 'new', state: 'running' }} title="Programme" t={x => x} />)
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    vi.unstubAllGlobals()
})

it('keeps relationship flow on completion but stops the active-stage outline', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'complete', next_cursor: 2, has_more: false, events: [
        { sequence: 1, type: 'candidates', data: { count: 1, nodes: [{ course_id: 42, title: 'Materials' }] } },
        { sequence: 2, type: 'stage', data: { state: 'complete', stage: 'complete' } },
    ] } })
    render(<BuildMapPanel versionId={3} status={{ state: 'running', job_id: 'done' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    await waitFor(() => expect(screen.getByRole('region')).not.toHaveClass('is-building'))
    expect(screen.getByRole('region')).toHaveClass('has-motion')
    fireEvent.click(within(screen.getByRole('img')).getByRole('button', { name: 'Materials' }))
    expect(screen.getByRole('status')).toHaveTextContent('ID 42')
    vi.unstubAllGlobals()
})

it('traps fullscreen keyboard focus and restores it on escape and close', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'complete', events: [], next_cursor: 0, has_more: false } })
    const user = userEvent.setup()
    render(<BuildMapPanel versionId={3} status={{ state: 'complete', job_id: 'real' }} title="Programme" t={x => x} />)
    const opener = screen.getByRole('button', { name: 'build_map_open' })
    await user.click(opener)
    const expand = screen.getByRole('button', { name: 'build_map_expand' })
    await user.click(expand)
    const dialog = screen.getByRole('dialog', { name: 'build_map_open' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveFocus()
    await user.tab({ shift: true })
    expect(dialog.contains(document.activeElement)).toBe(true)
    await user.tab()
    expect(dialog.contains(document.activeElement)).toBe(true)
    await user.keyboard('{Escape}')
    expect(expand).toHaveFocus()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(expand)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'build_map_close' }))
    expect(opener).toHaveFocus()
    vi.unstubAllGlobals()
})

it('shows passed gate marks only for a verified solution and does not imply publication', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', next_cursor: 1, has_more: false, events: [
        { sequence: 1, type: 'selected', data: { variant: 'A', verified: true, published: false, course_ids: [8087],
            schedule: { 1: [{ course_id: 8087, title: 'Timber design', credits: 5 }] } } },
    ] } })
    render(<BuildMapPanel versionId={3} status={{ state: 'running', job_id: 'real' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    expect(await screen.findAllByText('build_map_gate_passed')).toHaveLength(4)
    expect(screen.getByText('build_map_not_published')).toBeInTheDocument()
    vi.unstubAllGlobals()
})

it('renders recorded course relationships as inspectable geometry with bounded light trails', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', next_cursor: 1, has_more: false, events: [
        { sequence: 1, type: 'candidates', data: { variant: 'A', count: 1,
            learning_outcomes: [{ code: 'ON1', text: 'Design structures' }],
            nodes: [{ course_id: 8087, title: 'Timber design', lo_codes: ['ON1'] }] } },
    ] } })
    const view = render(<BuildMapPanel versionId={3} status={{ state: 'running', job_id: 'real' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    const graphCourse = await within(screen.getByRole('img')).findByRole('button', { name: 'Timber design', hidden: false })
    expect(graphCourse.closest('svg')).not.toBeNull()
    await waitFor(() => expect(view.container.querySelectorAll('animateMotion')).toHaveLength(6))
    fireEvent.click(graphCourse)
    expect(screen.getByRole('status')).toHaveTextContent('ID 8087')
    fireEvent.click(screen.getByRole('checkbox', { name: 'build_map_motion' }))
    expect(view.container.querySelectorAll('animateMotion')).toHaveLength(0)
    vi.unstubAllGlobals()
})

it('keeps verification pending when a selection has no verified flag', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', next_cursor: 1, has_more: false, events: [
        { sequence: 1, type: 'selected', data: { variant: 'A', course_ids: [8087],
            schedule: { 1: [{ course_id: 8087, title: 'Timber design', credits: 5 }] } } },
    ] } })
    render(<BuildMapPanel versionId={3} status={{ state: 'running', job_id: 'real' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    await waitFor(() => expect(screen.getByRole('group', { name: 'build_map_schedule' })).toHaveTextContent('Timber design'))
    expect(screen.queryByText('build_event_selected')).not.toBeInTheDocument()
    expect(screen.getByText('build_map_checks_pending')).toBeInTheDocument()
    vi.unstubAllGlobals()
})

it('shows actual semester courses in the laboratory without inventing a saved result', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', next_cursor: 2, has_more: false, events: [
        { sequence: 1, type: 'candidates', data: { variant: 'A', count: 12, nodes: [] } },
        { sequence: 2, type: 'selected', data: { variant: 'A', course_ids: [8087], schedule: { 2: [{ course_id: 8087, title: 'Timber design', credits: 5 }] } } },
    ] } })
    render(<BuildMapPanel versionId={3} status={{ state: 'running', job_id: 'real' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    expect(await screen.findByRole('heading', { name: 'build_map_lab' })).toBeInTheDocument()
    expect(await screen.findByRole('group', { name: 'build_map_schedule' })).toHaveTextContent('Timber design')
    vi.unstubAllGlobals()
})

it('lets keyboard users inspect outcome evidence in the text alternative', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'complete', next_cursor: 1, has_more: false,
        events: [{ sequence: 1, type: 'candidates', data: { count: 1, variant: 'A',
            learning_outcomes: [{ code: 'ON1', text: 'Design safe timber structures' }],
            nodes: [{ course_id: 8087, title: 'Timber design', lo_codes: ['ON1'] }] } }] } })
    const user = userEvent.setup()
    render(<BuildMapPanel versionId={3} status={{ job_id: 'real', state: 'complete' }} title="Programme" t={x => x} />)
    await user.click(screen.getByRole('button', { name: 'build_map_open' }))
    const outcome = await screen.findByRole('button', { name: 'ON1' })
    outcome.focus()
    await user.keyboard('{Enter}')
    expect(screen.getByText(/Design safe timber structures/)).toBeInTheDocument()
    vi.unstubAllGlobals()
})

it('signals a freshly published job once without waiting for the slow status poll', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'complete', events: [], next_cursor: 0, has_more: false } })
    const onPublished = vi.fn()
    const view = render(<BuildMapPanel versionId={3} status={{ state: 'running', job_id: 'real' }}
        title="Programme" t={x => x} onPublished={onPublished} />)
    fireEvent.click(screen.getByRole('button', {name: 'build_map_open'}))
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(3))
    view.rerender(<BuildMapPanel versionId={3} status={{ state: 'queued', job_id: 'real' }}
        title="Programme" t={x => x} onPublished={onPublished} />)
    expect(onPublished).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
})

it('uses the actual event stream state while the slower status poll still says queued', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
    axios.get.mockResolvedValue({ data: { state: 'running', events: [], next_cursor: 0, has_more: false } })
    render(<BuildMapPanel versionId={3} status={{ state: 'queued', job_id: 'real' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    await waitFor(() => expect(screen.getByRole('region')).toHaveClass('has-motion'))
    expect(screen.getByRole('region')).toHaveClass('is-building')
    vi.unstubAllGlobals()
})

it('pauses light flow outside the viewport and keeps it after completion', async () => {
    let observeVisibility
    vi.stubGlobal('IntersectionObserver', class {
        constructor(callback) { observeVisibility = callback }
        observe() {}
        disconnect() {}
    })
    axios.get.mockResolvedValue({ data: { state: 'idle' } })
    const { rerender } = render(<BuildMapPanel versionId={3} status={{ state: 'running' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    expect(screen.getByRole('region')).not.toHaveClass('has-motion')
    const { act } = await import('@testing-library/react')
    act(() => observeVisibility([{ isIntersecting: true }]))
    expect(screen.getByRole('region')).toHaveClass('has-motion')
    act(() => observeVisibility([{ isIntersecting: false }]))
    expect(screen.getByRole('region')).not.toHaveClass('has-motion')
    act(() => observeVisibility([{ isIntersecting: true }]))
    rerender(<BuildMapPanel versionId={3} status={{ state: 'complete' }} title="Programme" t={x => x} />)
    expect(screen.getByRole('region')).toHaveClass('has-motion')
    expect(screen.getByRole('region')).not.toHaveClass('is-building')
    vi.unstubAllGlobals()
})

it('shows the programme identity with motion enabled and allows pausing', async () => {
    axios.get.mockResolvedValue({ data: { state: 'idle' } })
    render(<BuildMapPanel versionId={3} status={{ state: 'idle' }} title="Wood engineering" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    expect(screen.getByText('Wood engineering')).toBeInTheDocument()
    const motion = screen.getByRole('checkbox', { name: 'build_map_motion' })
    expect(motion).toBeChecked()
    fireEvent.click(motion)
    expect(motion).not.toBeChecked()
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

it('locks background scrolling only while the opened panel is expanded', async () => {
    axios.get.mockResolvedValue({ data: { state: 'idle' } })
    document.body.style.overflow = 'auto'
    render(<BuildMapPanel versionId={3} status={{ state: 'idle' }} title="Programme" t={x => x} />)
    fireEvent.click(screen.getByRole('button', { name: 'build_map_open' }))
    await screen.findByText('build_map_no_job')
    fireEvent.click(screen.getByRole('button', { name: 'build_map_expand' }))
    expect(document.body.style.overflow).toBe('hidden')
    fireEvent.click(screen.getByRole('button', { name: 'build_map_restore' }))
    expect(document.body.style.overflow).toBe('auto')
})
