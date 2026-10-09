import { useEffect, useState } from 'react'
import axios from 'axios'

export default function useBuildEvents(versionId, jobId, opened) {
    const [events, setEvents] = useState([])
    const [error, setError] = useState(false)
    const [noJob, setNoJob] = useState(false)
    const [state, setState] = useState(null)
    const [job, setJob] = useState(null)
    useEffect(() => {
        if (!opened || !versionId) return
        let timer, controller, disposed = false, busy = false, finished = false, cursor = 0, currentJob = jobId
        setEvents([]); setError(false); setNoJob(false); setState(null); setJob(null)
        const tick = async () => {
            if (disposed || document.hidden || busy || finished) return
            busy = true
            controller = new AbortController()
            let delay = 2000
            try {
                if (!currentJob) {
                    const { data } = await axios.get(`/api/planner/${versionId}/build-status`, { signal: controller.signal })
                    currentJob = data.job_id
                }
                if (!currentJob) { if (!disposed) setNoJob(true); finished = true; return }
                const { data } = await axios.get(`/api/planner/${versionId}/build-events`, {
                    params: { job_id: currentJob, after: cursor, limit: 50 }, signal: controller.signal,
                })
                if (disposed) return
                cursor = data.next_cursor
                setError(false)
                setState(data.state)
                setJob({ versionId, jobId: currentJob })
                setEvents(previous => [...previous, ...data.events].slice(-500))
                if (!data.has_more && (['complete', 'cancelled', 'failed', 'rejected', 'timed_out', 'infeasible', 'superseded'].includes(data.state)
                    || data.events.some(e => ['complete', 'cancelled', 'failed', 'rejected', 'timed_out', 'infeasible'].includes(e.data?.state)))) {
                    finished = true
                    if (cursor === 0) setNoJob(true)
                }
                delay = data.has_more ? 50 : 2000
            } catch (e) {
                if (!disposed && e.code !== 'ERR_CANCELED') setError(true)
                delay = 5000
            } finally {
                busy = false
                if (!disposed && !document.hidden && !finished) timer = window.setTimeout(tick, delay)
            }
        }
        const visibility = () => {
            window.clearTimeout(timer)
            if (document.hidden) controller?.abort()
            else tick()
        }
        document.addEventListener('visibilitychange', visibility)
        tick()
        return () => { disposed = true; window.clearTimeout(timer); controller?.abort(); document.removeEventListener('visibilitychange', visibility) }
    }, [versionId, jobId, opened])
    return { events, error, noJob, state, job }
}
