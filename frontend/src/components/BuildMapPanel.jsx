import { useEffect, useMemo, useRef, useState } from 'react'
import useBuildEvents from '../hooks/useBuildEvents'
import { buildEventGraph } from '../utils/buildEventGraph'
import BuildLabGraph from './BuildLabGraph'
import './BuildMapPanel.css'


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
    const opener = useRef(null)
    const expandButton = useRef(null)
    const closePanel = () => {
        setOpened(false)
        setExpanded(false)
        opener.current?.focus()
    }
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
    const selection = [...events].reverse().find(e => e.type === 'selected' && (!candidate?.variant || e.data.variant === candidate.variant))?.data
    const schedule = selection?.schedule || {}
    const credits = Object.values(schedule).flat().reduce((sum, c) => sum + (Number(c.credits) || 0), 0)
    const chosenCount = Object.values(schedule).flat().length
    const stage = lastStage?.stage || status?.stage || 'idle'
    const steps = ['build_map_step_candidates', 'build_map_step_verify', 'build_map_step_schedule', 'build_map_step_save']
    const descriptions = ['build_map_step_candidates_detail', 'build_map_step_verify_detail', 'build_map_step_schedule_detail', 'build_map_step_save_detail']
    const currentStep = stage === 'complete' || stage === 'saving' ? 3 : selection ? 2
        : stage === 'variants' || stage === 'planning' ? 1 : 0
    const terminal = ['complete', 'cancelled', 'failed', 'rejected', 'timed_out', 'infeasible', 'superseded'].includes(status?.state)
    const animate = motion && visible && inViewport && !textOnly && !terminal && (eventState || status?.state) === 'running'
    const nodeList = <ul className="build-map-node-list">
        {elements.filter(e => e.data.courseId || e.data.state === 'outcome').map(e => <li key={e.data.id}>
            <button type="button" onClick={() => setInspected(e.data)}>{e.data.label}</button>
            {e.data.courseId && <> · ID {e.data.courseId} — {t(e.data.state === 'published' ? 'build_map_published' : e.data.state === 'selected' ? 'build_map_selected' : 'build_map_candidates')}</>}
        </li>)}
    </ul>
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
        if (!expanded || !opened) return
        const previousOverflow = document.body.style.overflow
        document.body.style.overflow = 'hidden'
        const root = panel.current
        const close = e => {
            if (e.key === 'Escape') { e.preventDefault(); setExpanded(false); return }
            if (e.key !== 'Tab') return
            const controls = [...root.querySelectorAll('button, input, select, textarea, a[href], summary, [tabindex]')]
                .filter(el => !el.disabled && el.tabIndex >= 0 && !el.closest('[hidden], [inert]')
                    && !el.closest('details:not([open]) :not(summary)'))
            const first = controls[0], last = controls.at(-1)
            if (!first) { e.preventDefault(); root.focus(); return }
            if (!root.contains(document.activeElement) || document.activeElement === root
                || (e.shiftKey && document.activeElement === first)
                || (!e.shiftKey && document.activeElement === last)) {
                e.preventDefault()
                ;(e.shiftKey ? last : first).focus()
            }
        }
        window.addEventListener('keydown', close)
        panel.current?.focus()
        return () => {
            document.body.style.overflow = previousOverflow
            window.removeEventListener('keydown', close)
            if (expandButton.current?.isConnected) expandButton.current.focus()
        }
    }, [expanded, opened])
    return <div className="build-map-wrapper">
        <button ref={opener} className="btn btn-secondary" type="button" aria-expanded={opened} onClick={() => opened ? closePanel() : setOpened(true)}>{t(opened ? 'build_map_close' : 'build_map_open')}</button>
        {opened && <section ref={panel} tabIndex={-1} role={expanded ? 'dialog' : undefined} aria-modal={expanded ? true : undefined} className={`build-map-panel${expanded ? ' is-expanded' : ''}${motion && visible && inViewport && !textOnly ? ' has-reveal' : ''}${animate ? ' has-motion' : ''}`} aria-label={t('build_map_open')}>
            <div className="build-map-toolbar"><div className="build-map-heading"><h3>{t('build_map_lab')}</h3><p>{title}</p></div>
                <label className="build-lab-motion"><input type="checkbox" checked={motion} disabled={textOnly} onChange={e => setMotion(e.target.checked)} /> {t('build_map_motion')}</label>
                <button ref={expandButton} type="button" onClick={() => setExpanded(v => !v)}>{t(expanded ? 'build_map_restore' : 'build_map_expand')}</button>
                <button type="button" onClick={closePanel}>{t('build_map_close')}</button>
            </div>
            <div className="build-map-facts" aria-live="polite">
                <span><small>{t('build_map_candidates')}</small><strong>{candidate?.count ?? '—'}</strong></span>
                <span><small>{t('build_map_stage')}</small><strong>{stageLabel(lastStage?.stage || status?.stage || 'idle')}</strong></span>
                <span><small>{t('build_map_variant')}</small><strong>{candidate?.variant || '—'}</strong></span>
            </div>
            {error && <p role="status">{t('build_map_connection_error')}</p>}
            {noJob && <p>{t('build_map_no_job')}</p>}
            <div className="build-lab-workspace">
            <aside className="build-lab-stages"><ol className="build-lab-pipeline">
                {steps.map((key, i) => <li key={key} className={i === currentStep ? 'is-current' : ''} aria-current={i === currentStep ? 'step' : undefined}>
                    <span className="build-lab-step-number">{i + 1}</span><div><h4>{t(key)}</h4><p>{t(descriptions[i])}</p></div>
                </li>)}
            </ol><div className="build-lab-source"><h4>{t('build_map_source')}</h4><p>{t('build_map_explanation')}</p>
                <dl><div><dt>{t('build_map_candidates')}</dt><dd>{candidate?.count ?? '—'}</dd></div>
                    <div><dt>{t('build_map_outcomes')}</dt><dd>{candidate?.learning_outcomes?.length ?? '—'}</dd></div>
                    <div><dt>{t('build_map_visible_nodes')}</dt><dd>{elements.filter(e => !e.data.source).length}</dd></div></dl>
            </div></aside>
            <div className="build-lab-canvas">
            <div className="build-lab-schedule" role="group" aria-label={t('build_map_schedule')}><h4>{t('build_map_schedule')}</h4>
                <div className="build-lab-semesters">{Object.entries(schedule).map(([semester, courses]) => <section key={semester}><h5>{t('build_map_semester')} {semester}</h5>
                    {courses.map((c, index) => <button type="button" className="build-lab-course" key={`${c.course_id}-${index}`} title={c.title} onClick={() => setInspected({ label: c.title, courseId: c.course_id })}><span>{c.title || `ID ${c.course_id}`}</span>{c.credits != null && <small>{c.credits} {t('build_map_credits')}</small>}</button>)}
                </section>)}</div>{!Object.keys(schedule).length && <p>{t('build_map_schedule_pending')}</p>}
            </div>
            <div className="build-map-controls">{!textOnly && <label><input type="checkbox" checked={graphEnabled} onChange={e => setGraphEnabled(e.target.checked)} /> {t('build_map_show_graph')}</label>}
                <span>{t('build_map_graph_caption')}</span>
            </div>
            {textOnly || !graphEnabled ? <>
                <p>{t('build_map_text_alternative')}</p>
                {nodeList}
            </> : !noJob && <BuildLabGraph elements={elements} t={t} onInspect={setInspected} motion={animate} />}
            {!textOnly && graphEnabled && !noJob && <details><summary>{t('build_map_text_alternative')}</summary>{nodeList}</details>}
            <div className="build-map-legend"><span>{t('build_map_candidates')}</span><span>{t('build_map_selected')}</span><span>{t('build_map_published')}</span></div>
            </div>
            <aside className="build-lab-evidence"><section><h4>{t('build_map_exclusions')}</h4><ul>{Object.entries(candidate?.exclusions || {}).filter(([, n]) => typeof n === 'number' && n > 0).map(([reason, n]) => <li key={reason}><span className="build-lab-reason-dot"/><span>{t(`build_exclusion_${reason}`)}</span> <strong>{n}</strong></li>)}</ul>
                {!candidate && <p>{t('build_map_candidates_pending')}</p>}
                {candidate && !Object.values(candidate.exclusions || {}).some(n => typeof n === 'number' && n > 0) && <p>{t('build_map_no_exclusions')}</p>}</section>
                <section><h4>{t('build_map_checks')}</h4>
                <p className={selection?.verified ? 'build-lab-verified' : ''}>{selection?.verified ? t('build_event_selected') : t('build_map_checks_pending')}</p>
                <ul className="build-lab-gates">{['build_map_gate_credits', 'build_map_gate_load', 'build_map_gate_prerequisites', 'build_map_gate_required'].map(key => <li key={key}>
                    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" className={selection?.verified ? 'is-passed' : 'is-pending'}>
                        <circle cx="12" cy="12" r="10"/>{selection?.verified ? <path d="m7 12 3 3 7-7"/> : <path d="M12 6v7m0 3v1"/>}</svg>
                    <div><strong>{t(key)}</strong><small>{t(selection?.verified ? 'build_map_gate_passed' : 'build_map_gate_pending')}</small></div>
                </li>)}</ul>
                <dl><div><dt>{t('build_map_actual_credits')}</dt><dd>{selection ? credits : '—'}</dd></div>
                    <div><dt>{t('build_map_semesters_count')}</dt><dd>{selection ? Object.keys(schedule).length : '—'}</dd></div>
                    <div><dt>{t('build_map_optimality')}</dt><dd>{selection?.optimality_proven === true ? t('build_map_proven') : t('build_map_not_reported')}</dd></div></dl>
                </section><section><h4>{t('build_map_selection')}</h4><dl><div><dt>{t('build_map_courses_count')}</dt><dd>{selection ? chosenCount : '—'}</dd></div>
                    <div><dt>{t('build_map_publication')}</dt><dd>{elements.some(e => e.data.state === 'published') ? t('build_map_published') : t('build_map_not_published')}</dd></div></dl>
                </section>
            {inspected && <section className="build-lab-inspection"><h4>{t('build_map_inspect')}</h4><p role="status">{inspected.label}{inspected.courseId ? ` · ID ${inspected.courseId}` : ''}{inspected.detail ? ` · ${inspected.detail}` : ''}</p></section>}
            </aside></div>
            <details className="build-lab-timeline" open><summary>{t('build_map_events')}</summary><ol>
                {events.map(e => <li key={e.sequence}><small>#{e.sequence}</small>{e.data.stage ? stageLabel(e.data.stage) : e.type === 'selected' && !e.data.verified ? t('build_map_selection') : t(`build_event_${e.type}`)}{e.data.error ? ` — ${e.data.error}` : ''}</li>)}
            </ol></details>
        </section>}
    </div>
}
