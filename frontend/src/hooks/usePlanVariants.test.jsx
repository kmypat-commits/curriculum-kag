import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import axios from 'axios'
import usePlanVariants from './usePlanVariants'

vi.mock('axios', () => ({ default: { get: vi.fn() } }))

it('does not replace a freshly loaded plan with a delayed previous response', async () => {
    let finishOld, oldRequest
    axios.get.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
        .mockResolvedValueOnce({data: [{variant_type: 'A', plan_id: 10}]})
    const { result } = renderHook(() => usePlanVariants())
    act(() => { oldRequest = result.current.fetchVariants(3) })
    await act(async () => result.current.fetchVariants(4))
    await act(async () => { finishOld({data: [{variant_type: 'A', plan_id: 9}]}); await oldRequest })
    expect(result.current.variants.A.plan_id).toBe(10)
})
