import { useEffect, useMemo, useRef, useState } from 'react'
import useBuildEvents from '../hooks/useBuildEvents'
import { buildEventGraph } from '../utils/buildEventGraph'
import './BuildMapPanel.css'

function LiveGraph({ elements, t, onInspect, motion }) {
    const host = useRef(null)
    const cy = useRef(null)
    const [ready, setReady] = useState(false)
    const [failed, setFailed] = useState(false)
    useEffect(() => {
        let disposed = false
        Promise.all([import('cytoscape'), import('cytoscape-dagre')]).then(([graph, layout]) => {
            if (disposed) return
            graph.default.use(layout.default)
            cy.current = graph.default({ container: host.current, elements: [],
                minZoom: .2, maxZoom: 2.5,
                style: [
                    { selector: 'node', style: { label: 'data(label)', 'font-size': 10, color: '#c4cfdf',
                        'text-wrap': 'ellipsis', 'text-max-width': 115, 'text-valign': 'bottom', 'text-margin-y': 5,
                        'background-color': '#667b98', width: 8, height: 8 } },
                    { selector: 'edge', style: { width: .65, 'line-color': '#46556c', opacity: .55, 'curve-style': 'bezier' } },
                    { selector: 'node[state="profile"]', style: { width: 20, height: 20, 'background-color': '#ded3ff', color: '#fff', 'font-size': 14 } },
                    { selector: 'node[state="outcome"]', style: { width: 12, height: 12, 'background-color': '#b7a2ef' } },
                    { selector: 'node[state="selected"]', style: { width: 12, height: 12, 'background-color': '#f3c277', color: '#fff' } },
                    { selector: 'node[state="published"]', style: { width: 12, height: 12, 'background-color': '#80d8b2', color: '#fff' } },
                    { selector: 'edge[kind="placement"]', style: { width: 1.4, 'line-color': '#f3c277', opacity: .9 } },
                    { selector: 'edge[kind="prerequisite"]', style: { 'line-style': 'dashed', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#8e9fb8' } },
                ],
            })
            cy.current.on('tap', 'node', e => onInspect(e.target.data()))
            setReady(true)
        }).catch(() => { if (!disposed) setFailed(true) })
        return () => { disposed = true; cy.current?.destroy(); cy.current = null }
    }, [onInspect])
    useEffect(() => {
        if (!ready || !cy.current) return
        cy.current.json({ elements })
        cy.current.layout({ name: 'dagre', rankDir: 'BT', nodeSep: 18, rankSep: 80,
            animate: motion && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
            animationDuration: 350, fit: true, padding: 35 }).run()
    }, [ready, elements, motion])
    return <div className="build-map-graph" ref={host} role="img" aria-label={t('build_map_graph')}>
        {failed && <p>{t('build_map_graph_unavailable')}</p>}
    </div>
}

export default function BuildMapPanel({ versionId, status, title, t, stageLabel = stage => stage, onPublished }) {
    const [opened, setOpened] = useState(false)
    const [expanded, setExpanded] = useState(false)
    const [inspected, setInspected] = useState(null)
    const [graphEnabled, setGraphEnabled] = useState(true)
    const [textOnly, setTextOnly] = useState(false)
    const [motion, setMotion] = useState(false)
    const [visible, setVisible] = useState(!document.hidden)
    const [inViewport, setInViewport] = useState(false)
    const panel = useRef(null)
    const publishedJob = useRef(null)
    const { events, error, noJob, state: eventState, job: eventJob } = useBuildEvents(versionId, status?.job_id, opened)
    useEffect(() => {
        if (eventState !== 'complete' || eventJob?.versionId !== versionId
            || eventJob?.jobId !== status?.job_id || !['queued', 'running'].includes(status?.state)
            || !onPublished) return
        const key = `${versionId}:${eventJob.jobId}`
        if (publishedJob.current === key) return
        publishedJob.current = key
        onPublished(versionId)
    }, [eventState, eventJob, versionId, status?.job_id, status?.state, onPublished])
    const elements = useMemo(() => buildEventGraph(events, title, t('build_map_aggregate')), [events, title, t])
    const candidate = [...events].reverse().find(e => e.type === 'candidates')?.data
    const lastStage = [...events].reverse().find(e => e.type === 'stage')?.data
    const terminal = ['complete', 'cancelled', 'failed', 'rejected', 'timed_out', 'infeasible', 'superseded'].includes(status?.state)
    const animate = motion && visible && inViewport && !textOnly && !terminal && (eventState || status?.state) === 'running'
    useEffect(() => {
        if (!opened || !panel.current) return
        if (!window.IntersectionObserver) { setInViewport(true); return }
        const observer = new IntersectionObserver(entries => setInViewport(entries.some(entry => entry.isIntersecting)))
        observer.observe(panel.current)
        return () => { observer.disconnect(); setInViewport(false) }
    }, [opened])
    useEffect(() => {
        const update = () => setVisible(!document.hidden)
        document.addEventListener('visibilitychange', update)
        return () => document.removeEventListener('visibilitychange', update)
    }, [])
    useEffect(() => {
        const preference = window.matchMedia?.('(max-width: 600px), (prefers-reduced-motion: reduce)')
        const update = () => setTextOnly(Boolean(preference?.matches))
        update()
        preference?.addEventListener?.('change', update)
        return () => preference?.removeEventListener?.('change', update)
    }, [])
    useEffect(() => {
        if (!expanded) return
        const close = e => { if (e.key === 'Escape') setExpanded(false) }
        window.addEventListener('keydown', close)
        panel.current?.focus()
        return () => window.removeEventListener('keydown', close)
    }, [expanded])
    return <div className="build-map-wrapper">
        <button className="btn btn-secondary" type="button" aria-expanded={opened} onClick={() => setOpened(v => !v)}>{t(opened ? 'build_map_close' : 'build_map_open')}</button>
        {opened && <section ref={panel} tabIndex={-1} className={`build-map-panel${expanded ? ' is-expanded' : ''}${animate ? ' has-motion' : ''}`} aria-label={t('build_map_open')}>
            <div className="build-map-toolbar"><div className="build-map-heading"><h3>{t('build_map_open')}</h3><p>{title}</p></div>
                <button type="button" onClick={() => setExpanded(v => !v)}>{t(expanded ? 'build_map_restore' : 'build_map_expand')}</button>
                <button type="button" onClick={() => { setOpened(false); setExpanded(false) }}>{t('build_map_close')}</button>
            </div>
            <p className="build-map-explanation">{t('build_map_explanation')}</p>
            <div className="build-map-facts" aria-live="polite">
                <span><small>{t('build_map_candidates')}</small><strong>{candidate?.count ?? '—'}</strong></span>
                <span><small>{t('build_map_stage')}</small><strong>{stageLabel(lastStage?.stage || status?.stage || 'idle')}</strong></span>
                <span><small>{t('build_map_variant')}</small><strong>{candidate?.variant || '—'}</strong></span>
            </div>
            {error && <p role="status">{t('build_map_connection_error')}</p>}
            {noJob && <p>{t('build_map_no_job')}</p>}
            <div className="build-map-controls">{!textOnly && <label><input type="checkbox" checked={graphEnabled} onChange={e => setGraphEnabled(e.target.checked)} /> {t('build_map_show_graph')}</label>}
                <label><input type="checkbox" checked={motion} disabled={textOnly} onChange={e => setMotion(e.target.checked)} /> {t('build_map_motion')}</label>
            </div>
            {textOnly || !graphEnabled ? <>
                <p>{t('build_map_text_alternative')}</p>
                <ul>{elements.filter(e => e.data.courseId).map(e => <li key={e.data.id}>{e.data.label} · ID {e.data.courseId} — {t(e.data.state === 'published' ? 'build_map_published' : e.data.state === 'selected' ? 'build_map_selected' : 'build_map_candidates')}</li>)}</ul>
            </> : !noJob && <LiveGraph elements={elements} t={t} onInspect={setInspected} motion={animate} />}
            <div className="build-map-legend"><span>{t('build_map_candidates')}</span><span>{t('build_map_selected')}</span><span>{t('build_map_published')}</span></div>
            {inspected && <p>{inspected.label}{inspected.courseId ? ` · ID ${inspected.courseId}` : ''}{inspected.detail ? ` · ${inspected.detail}` : ''}</p>}
            <details><summary>{t('build_map_events')}</summary><ol>
                {events.map(e => <li key={e.sequence}>{e.data.stage ? stageLabel(e.data.stage) : t(`build_event_${e.type}`)}{e.data.error ? ` — ${e.data.error}` : ''}</li>)}
            </ol></details>
            {candidate?.exclusions && <details><summary>{t('build_map_exclusions')}</summary><ul>
                {Object.entries(candidate.exclusions).filter(([, count]) => typeof count === 'number' && count > 0).map(([reason, count]) => <li key={reason}>{t(`build_exclusion_${reason}`)}: {count}</li>)}
            </ul></details>}
        </section>}
    </div>
}
