import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import axios from 'axios'
import usePlanBuildPolling from './usePlanBuildPolling'
vi.mock('axios', () => ({ default: { get: vi.fn() } }))
afterEach(() => vi.useRealTimers())

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
