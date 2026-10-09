import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import axios from 'axios'
import useBuildEvents from './useBuildEvents'

vi.mock('axios', () => ({ default: { get: vi.fn() } }))
const event = (seq, stage) => ({ seq, type: 'stage', data: { stage } })
const page = (events, cursor, state = 'running', more = false) => ({
    data: { events, next_cursor: cursor, state, has_more: more },
})
beforeEach(() => { vi.useFakeTimers(); axios.get.mockReset() })
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })

it('drains all pages of a terminal job before stopping requests', async () => {
    axios.get.mockResolvedValueOnce(page([event(1, 'matching')], 1, 'complete', true))
        .mockResolvedValueOnce(page([event(2, 'saved')], 2, 'complete'))
    const { result } = renderHook(() => useBuildEvents(7, 'saved', true))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTimeAsync(50))
    expect(result.current.events.map(e => e.data.stage)).toEqual(['matching', 'saved'])
    expect(result.current.job).toEqual({ versionId: 7, jobId: 'saved' })
    expect(axios.get.mock.calls[1][1].params).toEqual({ job_id: 'saved', after: 1, limit: 50 })
    await act(async () => vi.advanceTimersByTimeAsync(10000))
    expect(axios.get).toHaveBeenCalledTimes(2)
})

it('reopens the saved stream from the beginning without duplicated events', async () => {
    axios.get.mockResolvedValue(page([event(3, 'saved')], 3, 'complete'))
    const { result, rerender } = renderHook(({ opened }) => useBuildEvents(7, 'saved', opened), { initialProps: { opened: true } })
    await act(async () => {})
    rerender({ opened: false }); rerender({ opened: true })
    await act(async () => {})
    expect(result.current.events.map(e => e.seq)).toEqual([3])
    expect(axios.get.mock.calls[1][1].params.after).toBe(0)
})

it('ignores the previous job response after switching to a new job', async () => {
    let resolveOld
    axios.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
        .mockResolvedValueOnce(page([event(5, 'new')], 5))
    const { result, rerender } = renderHook(({ job }) => useBuildEvents(7, job, true), { initialProps: { job: 'old' } })
    rerender({ job: 'new' })
    await act(async () => {})
    await act(async () => resolveOld(page([event(1, 'old')], 1, 'complete')))
    expect(result.current.events.map(e => e.data.stage)).toEqual(['new'])
    expect(result.current.state).toBe('running')
    expect(result.current.job.jobId).toBe('new')
})

it('keeps the cursor through a transient error and clears the error on recovery', async () => {
    axios.get.mockResolvedValueOnce(page([event(1, 'matching')], 1))
        .mockRejectedValueOnce(new Error('offline'))
        .mockResolvedValueOnce(page([event(2, 'saved')], 2, 'complete'))
    const { result } = renderHook(() => useBuildEvents(7, 'saved', true))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.error).toBe(true)
    await act(async () => vi.advanceTimersByTimeAsync(5000))
    expect(result.current.error).toBe(false)
    expect(result.current.events.map(e => e.seq)).toEqual([1, 2])
    expect(axios.get.mock.calls[2][1].params.after).toBe(1)
})

it('pauses in a hidden tab and resumes from the last received cursor', async () => {
    let hidden = false
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
    axios.get.mockResolvedValueOnce(page([event(1, 'matching')], 1))
        .mockResolvedValueOnce(page([event(2, 'saved')], 2, 'complete'))
    const { result } = renderHook(() => useBuildEvents(7, 'saved', true))
    await act(async () => {})
    hidden = true
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => vi.advanceTimersByTimeAsync(10000))
    expect(axios.get).toHaveBeenCalledTimes(1)
    hidden = false
    await act(async () => document.dispatchEvent(new Event('visibilitychange')))
    expect(result.current.events.map(e => e.seq)).toEqual([1, 2])
    expect(axios.get.mock.calls[1][1].params.after).toBe(1)
})

it.each(['cancelled', 'failed', 'superseded'])('stops polling after %s without claiming completion', async state => {
    axios.get.mockResolvedValue(page([event(1, state)], 1, state))
    const { result } = renderHook(() => useBuildEvents(7, 'stopped', true))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTimeAsync(10000))
    expect(result.current.state).toBe(state)
    expect(axios.get).toHaveBeenCalledTimes(1)
})
