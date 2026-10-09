import { useCallback, useEffect, useRef } from 'react'
import axios from 'axios'

const POLL_INTERVAL_MS = 30000
const RETRY_INTERVAL_MS = 60000

export default function usePlanBuildPolling({ onStatus, onComplete }) {
    const timerRef = useRef(null)
    const callbacksRef = useRef({ onStatus, onComplete })
    callbacksRef.current = { onStatus, onComplete }

    const stop = useCallback(() => {
        if (timerRef.current) {
            window.clearTimeout(timerRef.current)
            timerRef.current = null
        }
    }, [])

    const start = useCallback((versionId) => {
        stop()
        const tick = async () => {
            try {
                const { data } = await axios.get(`/api/planner/${versionId}/build-status`)
                // POST /build and the first GET may race. An idle read does
                // not mean that the submitted command has finished.
                if (data.state === 'idle') {
                    timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS)
                    return
                }
                callbacksRef.current.onStatus(data)
                if (data.state === 'running' || data.state === 'queued') {
                    timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS)
                    return
                }
                timerRef.current = null
                if (data.state === 'complete') await callbacksRef.current.onComplete(versionId)
            } catch (_) {
                timerRef.current = window.setTimeout(tick, RETRY_INTERVAL_MS)
            }
        }
        tick()
    }, [stop])

    useEffect(() => stop, [stop])
    return { start, stop }
}
