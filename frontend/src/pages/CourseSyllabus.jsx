import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import axios from 'axios'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import LoadingSpinner from '../components/LoadingSpinner'

export default function CourseSyllabus() {
    const { id, kind, entityId } = useParams()
    const { t, localize, language } = useLanguage()
    const [weeks, setWeeks] = useState(15)
    const [contactShare, setContactShare] = useState(50)
    const [mode, setMode] = useState('academic')
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [saving, setSaving] = useState(false)
    const [saveNotice, setSaveNotice] = useState(null)

    const load = async () => {
        try {
            setLoading(true)
            const response = await axios.get('/api/planner/syllabus/' + kind + '/' + entityId, {
                params: { weeks, contact_share: contactShare / 100, mode }
            })
            let nextData = response.data
            try {
                const saved = await axios.get('/api/planner/syllabus/draft/' + kind + '/' + entityId)
                const content = saved.data?.content
                if (content && content.weeks === weeks && content.mode === mode && Math.round((content.contact_share || 0) * 100) === contactShare) nextData = content
            } catch (_) { /* no saved draft for these settings */ }
            setData(nextData)
            setError(null)
        } catch (err) {
            setError(err.response?.data?.detail || err.message)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { load() }, [kind, entityId, weeks, contactShare, mode])

    const labels = ({
        ru: { mode: 'Модель курса', academic: 'Академическая', practical: 'Практическая', project: 'Проектная', activity: 'Учебная деятельность', evidence: 'Доказательство результата', checks: 'Автоматическая проверка', ready: 'Черновик готов к экспертной проверке', needsFix: 'Есть замечания к структуре черновика', save: 'Сохранить черновик', saved: 'Черновик сохранён', word: 'Скачать Word' },
        kk: { mode: 'Курс моделі', academic: 'Академиялық', practical: 'Практикалық', project: 'Жобалық', activity: 'Оқу әрекеті', evidence: 'Нәтиже дәлелі', checks: 'Автоматты тексеру', ready: 'Жоба сараптамалық тексеруге дайын', needsFix: 'Жоба құрылымында ескертулер бар', save: 'Жобаны сақтау', saved: 'Жоба сақталды', word: 'Word жүктеу' },
        en: { mode: 'Course model', academic: 'Academic', practical: 'Practical', project: 'Project-based', activity: 'Learning activity', evidence: 'Outcome evidence', checks: 'Automated checks', ready: 'Draft is ready for expert review', needsFix: 'The draft has structural issues', save: 'Save draft', saved: 'Draft saved', word: 'Download Word' }
    })[language] || {}

    const updateRow = (index, field, value) => setData(current => ({
        ...current,
        thematic_plan: current.thematic_plan.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row)
    }))

    const saveDraft = async () => {
        setSaving(true); setSaveNotice(null)
        try {
            await axios.post('/api/planner/syllabus/draft/' + kind + '/' + entityId, { content: data })
            setSaveNotice(labels.saved)
        } catch (err) { setError(err.response?.data?.detail || err.message) }
        finally { setSaving(false) }
    }

    const exportWord = async () => {
        const response = await axios.post('/api/planner/syllabus/export-docx', { content: data }, { responseType: 'blob' })
        const url = URL.createObjectURL(response.data); const link = document.createElement('a')
        link.href = url; link.download = 'course_syllabus.docx'; link.click(); URL.revokeObjectURL(url)
    }

    return <div style={{ minHeight: '100vh', background: '#f5f7fa' }}>
        <style>{'@media print { .no-print { display:none !important; } body { background:white; } .card { box-shadow:none !important; border:none !important; } }'}</style>
        <header className="no-print" style={{ background: 'white', borderBottom: '1px solid #ddd', padding: 14 }}>
            <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Link to={'/projects/' + id + '/graph'}>← {t('back_to_graph')}</Link>
                <LanguageSelector />
            </div>
        </header>
        <main className="container" style={{ paddingTop: 20, paddingBottom: 40 }}>
            <div className="card no-print" style={{ display: 'flex', gap: 16, alignItems: 'end', flexWrap: 'wrap', marginBottom: 16 }}>
                <label>{t('academic_weeks')}<input className="form-control" type="number" min="10" max="20" value={weeks} onChange={event => setWeeks(Number(event.target.value))} /></label>
                <label>{t('contact_share_percent')}<input className="form-control" type="number" min="20" max="80" value={contactShare} onChange={event => setContactShare(Number(event.target.value))} /></label>
                <label>{labels.mode}<select className="form-control" value={mode} onChange={event => setMode(event.target.value)}>
                    <option value="academic">{labels.academic}</option><option value="practical">{labels.practical}</option><option value="project">{labels.project}</option>
                </select></label>
                <button className="btn btn-secondary" onClick={load}>{t('recalculate')}</button>
                <button className="btn btn-primary" disabled={!data || saving} onClick={saveDraft}>{saving ? t('loading') : labels.save}</button>
                <button className="btn btn-secondary" disabled={!data} onClick={exportWord}>{labels.word}</button>
                <button className="btn btn-primary" onClick={() => window.print()}>{t('print_or_pdf')}</button>
                {saveNotice && <strong style={{ color: '#2e7d32' }}>{saveNotice}</strong>}
            </div>
            {loading && <LoadingSpinner />}
            {error && <div className="card" style={{ color: '#b71c1c' }}>{error}</div>}
            {!loading && data && <article className="card">
                <div style={{ textAlign: 'center', marginBottom: 24 }}>
                    <div style={{ color: '#666' }}>{data.code}</div>
                    <h1 style={{ margin: '6px 0' }}>{t('course_syllabus')}</h1>
                    <h2 style={{ margin: 0, color: '#366092' }}>{localize(data.title_translations || data.title)}</h2>
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 20 }}>
                    <tbody>
                        <tr><th style={cell}>{t('credits')}</th><td style={cell}>{data.credits}</td><th style={cell}>{t('total_hours')}</th><td style={cell}>{data.total_hours}</td></tr>
                        <tr><th style={cell}>{t('contact_hours')}</th><td style={cell}>{data.contact_hours}</td><th style={cell}>{t('independent_hours')}</th><td style={cell}>{data.independent_hours}</td></tr>
                        <tr><th style={cell}>{t('lecture_hours')}</th><td style={cell}>{data.lecture_hours}</td><th style={cell}>{t('practical_hours')}</th><td style={cell}>{data.practical_hours}</td></tr>
                    </tbody>
                </table>
                <h3>{t('course_description')}</h3><p>{localize(data.description_translations || data.description) || t('no_description')}</p>
                <h3>{t('learning_outcomes')}</h3><ol>{data.learning_outcomes.map((item, index) => <li key={index}>{item}</li>)}</ol>
                <h3>{t('prerequisites')}</h3><p>{data.prerequisites.map(item => localize(item.title_translations || item.title)).join('; ') || t('none')}</p>
                <h3>{t('postrequisites')}</h3><p>{data.postrequisites.map(item => localize(item.title_translations || item.title)).join('; ') || t('none')}</p>
                <h3>{t('thematic_plan')}</h3>
                <div style={{ marginBottom: 14, padding: 12, borderRadius: 8, background: data.validations?.ready_for_expert_review ? '#e8f5e9' : '#fff3e0', color: data.validations?.ready_for_expert_review ? '#1b5e20' : '#e65100' }}>
                    <strong>{labels.checks}:</strong> {data.validations?.ready_for_expert_review ? labels.ready : labels.needsFix}
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead><tr>
                            <th style={cell}>{t('week')}</th><th style={cell}>{t('topic')}</th><th style={cell}>{t('lectures_short')}</th>
                            <th style={cell}>{t('practice_short')}</th><th style={cell}>{t('independent_short')}</th><th style={cell}>{t('total')}</th>
                            <th style={cell}>LO</th><th style={cell}>{labels.activity}</th><th style={cell}>{t('assessment')}</th><th style={cell}>{labels.evidence}</th>
                        </tr></thead>
                        <tbody>{data.thematic_plan.map((row, index) => <tr key={row.week}>
                            <td style={cell}>{row.week}</td><td style={cell}><textarea style={editor} value={row.topic} onChange={event => updateRow(index, 'topic', event.target.value)} /></td><td style={cell}>{row.lecture_hours}</td>
                            <td style={cell}>{row.practical_hours}</td><td style={cell}>{row.independent_hours}</td><td style={cell}>{row.total_hours}</td>
                            <td style={cell}>{row.learning_outcome}</td><td style={cell}><textarea style={editor} value={row.learning_activity} onChange={event => updateRow(index, 'learning_activity', event.target.value)} /></td><td style={cell}><textarea style={editor} value={row.assessment} onChange={event => updateRow(index, 'assessment', event.target.value)} /></td><td style={cell}><textarea style={editor} value={row.evidence} onChange={event => updateRow(index, 'evidence', event.target.value)} /></td>
                        </tr>)}</tbody>
                        <tfoot><tr><th style={cell} colSpan="2">{t('total')}</th><th style={cell}>{data.lecture_hours}</th><th style={cell}>{data.practical_hours}</th><th style={cell}>{data.independent_hours}</th><th style={cell}>{data.total_hours}</th><th style={cell} colSpan="4">{data.hours_check ? '✓ ' + t('hours_match') : t('hours_do_not_match')}</th></tr></tfoot>
                    </table>
                </div>
                <div style={{ marginTop: 20, padding: 12, background: '#fff8e1', borderLeft: '4px solid #ffb300' }}>
                    <strong>{t('important_assumptions')}</strong>
                    <ul><li>{t('credit_30_hours_rule')}</li><li>{t('institution_template_note')}</li><li>{t('expert_review_required')}</li></ul>
                </div>
            </article>}
        </main>
    </div>
}

const cell = { border: '1px solid #b0bec5', padding: '7px', verticalAlign: 'top', textAlign: 'left' }
const editor = { width: '180px', minHeight: '64px', border: '1px solid #cfd8dc', borderRadius: '5px', padding: '6px', resize: 'vertical', font: 'inherit' }
