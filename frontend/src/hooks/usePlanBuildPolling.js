import { useCallback, useEffect, useRef } from 'react'
import axios from 'axios'

const POLL_INTERVAL_MS = 30000
const RETRY_INTERVAL_MS = 60000

export default function usePlanBuildPolling({ onStatus, onComplete }) {
    const timerRef = useRef(null)
    const revisionRef = useRef(0)
    const callbacksRef = useRef({ onStatus, onComplete })
    callbacksRef.current = { onStatus, onComplete }

    const stop = useCallback(() => {
        revisionRef.current += 1
        if (timerRef.current) {
            window.clearTimeout(timerRef.current)
            timerRef.current = null
        }
    }, [])

    const start = useCallback((versionId, { ignoreJobId } = {}) => {
        stop()
        const revision = revisionRef.current
        const tick = async () => {
            try {
                const { data } = await axios.get(`/api/planner/${versionId}/build-status`)
                if (revisionRef.current !== revision) return
                // POST /build and the first GET may race. An idle read does
                // not mean that the submitted command has finished.
                if (data.state === 'idle' || (ignoreJobId && data.job_id === ignoreJobId)) {
                    timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS)
                    return
                }
                // Publication changes plan IDs. Refresh variants before
                // exposing completion and enabling actions on the new plan.
                if (data.state === 'complete') {
                    await callbacksRef.current.onComplete(versionId)
                    if (revisionRef.current !== revision) return
                }
                callbacksRef.current.onStatus(data)
                if (data.state === 'running' || data.state === 'queued') {
                    timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS)
                    return
                }
                timerRef.current = null
            } catch (_) {
                if (revisionRef.current === revision) timerRef.current = window.setTimeout(tick, RETRY_INTERVAL_MS)
            }
        }
        tick()
    }, [stop])

    useEffect(() => stop, [stop])
    return { start, stop }
}
