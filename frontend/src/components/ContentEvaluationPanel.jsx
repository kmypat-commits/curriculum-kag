import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

export default function ContentEvaluationPanel({ versionId, planId, t, mode = 'shadow', onModeChange }) {
    const [opened, setOpened] = useState(false)
    const [result, setResult] = useState(null)
    const [error, setError] = useState(false)
    const [busy, setBusy] = useState(false)
    const revision = useRef(0)
    useEffect(() => {
        revision.current += 1
        setResult(null); setError(false); setOpened(false); setBusy(false)
        return () => { revision.current += 1 }
    }, [versionId, planId])
    const load = async (save = false) => {
        const requestedRevision = revision.current
        setBusy(true); setError(false)
        try {
            const request = save ? axios.post : axios.get
            const response = save
                ? await request(`/api/planner/${versionId}/content-evaluation`, null, { params: { plan_id: planId } })
                : await request(`/api/planner/${versionId}/content-evaluation`, { params: { plan_id: planId } })
            if (revision.current === requestedRevision) setResult(response.data)
        } catch (_) { if (revision.current === requestedRevision) setError(true) }
        finally { if (revision.current === requestedRevision) setBusy(false) }
    }
    const toggle = () => { if (!opened) load(); setOpened(v => !v) }
    const report = result?.report
    return <section className="content-evaluation-section">
        <div className="content-evaluation-actions">
            <button type="button" className="btn btn-secondary" disabled={!planId || busy} aria-expanded={opened} onClick={toggle}>{t('content_evaluation_open')}</button>
            <label>{t('content_evaluation_mode')} <select value={mode} disabled={busy || !onModeChange} onChange={async e => {
                setBusy(true); setError(false)
                try { await onModeChange(e.target.value) } catch (_) { setError(true) } finally { setBusy(false) }
            }}><option value="shadow">{t('content_mode_shadow')}</option><option value="prioritise">{t('content_mode_prioritise')}</option></select></label>
        </div>
        {error && <p role="alert">{t('content_evaluation_error')}</p>}
        {opened && <div className="content-evaluation-report">
            <h3>{t('content_evaluation_open')}</h3>
            <p>{t('content_evaluation_advisory')}</p>
            {busy && <p role="status">{t('loading')}</p>}
            {report && <>
                {result.stale && <p role="status">{t('content_evaluation_stale')}</p>}
                <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => load(true)}>{t('content_evaluation_refresh')}</button>
                <dl className="content-evaluation-indicators">{Object.entries(report.indicators).map(([key, value]) =>
                    <div key={key}><dt>{t(`content_indicator_${key}`)}</dt><dd>{value}</dd></div>)}</dl>
                {report.core_definition_missing && <p>{t('content_evaluation_no_core')}</p>}
                <ul>{report.core_coverage.map(block => <li key={block.block_id}>{block.title} — {t(`content_status_${block.status}`)}</li>)}</ul>
                <div className="content-evaluation-courses">{report.courses.map(course => <details key={course.course_id}>
                    <summary>{course.title} — {t(`content_status_${course.status}`)}</summary>
                    <p>{t(`content_role_${course.role}`)} · ID {course.course_id}</p>
                    {course.evidence.map((e, i) => <blockquote key={i}><p>{e.excerpt}</p><cite>{e.source_reference} · {e.source_field}</cite></blockquote>)}
                </details>)}</div>
                {report.duplicate_groups.map((group, i) => <p key={i}>{t('content_possible_duplicates')}: {group.course_ids.join(', ')}</p>)}
                {report.sequence_findings.map((item, i) => <p key={i}>{t(`content_sequence_${item.reason}`)}: ID {item.course_id} → ID {item.prerequisite_id}</p>)}
                <small>{report.evaluator_version}</small>
            </>}
        </div>}
    </section>
}
