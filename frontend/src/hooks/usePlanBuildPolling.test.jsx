import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import axios from 'axios'
import usePlanBuildPolling from './usePlanBuildPolling'
vi.mock('axios', () => ({ default: { get: vi.fn() } }))
afterEach(() => vi.useRealTimers())

it('does not treat the previous completed job as the submitted new build', async () => {
    vi.useFakeTimers()
    axios.get.mockReset().mockResolvedValueOnce({ data: { state: 'complete', job_id: 'previous' } })
        .mockResolvedValueOnce({ data: { state: 'running', job_id: 'new' } })
    const onStatus = vi.fn(), onComplete = vi.fn()
    const { result } = renderHook(() => usePlanBuildPolling({ onStatus, onComplete }))
    await act(async () => result.current.start(3, { ignoreJobId: 'previous' }))
    expect(onStatus).not.toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
    await act(async () => vi.advanceTimersByTimeAsync(30000))
    expect(onStatus).toHaveBeenCalledWith({ state: 'running', job_id: 'new' })
})

it('does not expose completion until the persisted variants refresh resolves', async () => {
    let finishRefresh
    axios.get.mockReset().mockResolvedValue({ data: { state: 'complete', job_id: 'saved' } })
    const onStatus = vi.fn()
    const onComplete = vi.fn(() => new Promise(resolve => { finishRefresh = resolve }))
    const { result } = renderHook(() => usePlanBuildPolling({ onStatus, onComplete }))
    await act(async () => result.current.start(1632))
    expect(onComplete).toHaveBeenCalledWith(1632)
    expect(onStatus).not.toHaveBeenCalled()
    await act(async () => finishRefresh())
    expect(onStatus).toHaveBeenCalledWith({ state: 'complete', job_id: 'saved' })
})

it('ignores an in-flight completion from a stopped previous polling session', async () => {
    let finishOld
    axios.get.mockReset().mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
        .mockResolvedValueOnce({ data: { state: 'running', job_id: 'new' } })
    const onStatus = vi.fn(), onComplete = vi.fn()
    const { result } = renderHook(() => usePlanBuildPolling({ onStatus, onComplete }))
    await act(async () => result.current.start(3))
    await act(async () => result.current.start(4))
    await act(async () => finishOld({ data: { state: 'complete', job_id: 'old' } }))
    expect(onComplete).not.toHaveBeenCalled()
    expect(onStatus.mock.calls).toEqual([[{ state: 'running', job_id: 'new' }]])
})

it('does not stop on the idle snapshot while the build command is being accepted', async () => {
    vi.useFakeTimers()
    axios.get.mockResolvedValueOnce({ data: { state: 'idle' } })
        .mockResolvedValueOnce({ data: { state: 'running', job_id: 'actual' } })
        .mockResolvedValueOnce({ data: { state: 'complete', job_id: 'actual' } })
    const onStatus = vi.fn(), onComplete = vi.fn()
    const { result } = renderHook(() => usePlanBuildPolling({ onStatus, onComplete }))
    await act(async () => result.current.start(1632))
    expect(onStatus).not.toHaveBeenCalled()
    await act(async () => vi.advanceTimersByTimeAsync(30000))
    expect(onStatus).toHaveBeenCalledWith({ state: 'running', job_id: 'actual' })
    await act(async () => vi.advanceTimersByTimeAsync(30000))
    expect(onComplete).toHaveBeenCalledWith(1632)
})
