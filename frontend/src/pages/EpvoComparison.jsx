import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import axios from 'axios'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatApiError } from '../utils/errors'

const labels = {
    ru: {
        epvo_match: 'Полнота типовых дисциплин ЕПВО',
        epvo_quality_notes: 'Замечания и рекомендации ЕПВО',
        similar_epvo_programs: 'Похожие программы ЕПВО',
        typical_epvo_los: 'Типовые результаты обучения ЕПВО',
        disciplines: 'Дисциплины',
        similarity: 'Сходство',
        expert_support: 'Экспертная поддержка',
        selected_scopes: 'Выбранные направления и группы',
        expert_links: 'Экспертных связей',
        quality_verdict: 'Вердикт качества',
        priority_missing: 'Приоритетно проверить',
        apply_priority: 'Добавить выбранные дисциплины',
        rebuild_hint: 'После добавления перестройте варианты A/B/C в конструкторе плана.',
        open_plan_builder: 'Открыть конструктор плана',
        quality_formula: 'Формула: 70% полнота относительно типовых дисциплин ЕПВО + 30% экспертная поддержка связей дисциплина–LO.',
        epvo_match_hint: 'Это показывает, сколько типовых дисциплин из референсного набора ЕПВО уже есть в плане.',
        plan_from_epvo: 'Дисциплины плана из ЕПВО',
        repository_status: 'Статус',
        status_in_plan: 'уже в плане',
        status_in_repository: 'есть в репозитории',
        status_missing: 'будет добавлена',
        all_statuses: 'все',
        selected_count: 'выбрано',
        select_new: 'выбрать новые',
        select_visible: 'выбрать видимые',
        clear_selection: 'снять выбор',
        added_details: 'Результат добавления',
        compare_ready: 'Сравнение готово',
        light_mode: 'лёгкий режим',
        reference_limits: 'Показана быстрая выборка, чтобы страница не зависала. Для планировщика используются полные данные ЕПВО.',
        loading_compare: 'Сравниваю с ЕПВО. Это может занять несколько секунд…',
    },
    kk: {
        epvo_match: 'ЕПВО типтік пәндерінің толықтығы',
        epvo_quality_notes: 'ЕПВО ескертулері мен ұсыныстары',
        similar_epvo_programs: 'Ұқсас ЕПВО бағдарламалары',
        typical_epvo_los: 'ЕПВО типтік оқу нәтижелері',
        disciplines: 'Пәндер',
        similarity: 'Ұқсастық',
        expert_support: 'Сараптамалық қолдау',
        selected_scopes: 'Таңдалған бағыттар мен топтар',
        expert_links: 'Сараптамалық байланыстар',
        quality_verdict: 'Сапа қорытындысы',
        priority_missing: 'Бірінші тексерілетіндер',
        apply_priority: 'Таңдалған пәндерді қосу',
        rebuild_hint: 'Қосқаннан кейін жоспар құрастырғышта A/B/C нұсқаларын қайта құрыңыз.',
        open_plan_builder: 'Жоспар құрастырғышын ашу',
        quality_formula: 'Формула: 70% ЕПВО типтік пәндерімен сәйкестік + 30% пән–LO байланыстарының сараптамалық қолдауы.',
        epvo_match_hint: 'Бұл ЕПВО референстік жинағындағы типтік пәндердің қаншасы жоспарда бар екенін көрсетеді.',
        plan_from_epvo: 'Жоспардағы ЕПВО пәндері',
        repository_status: 'Мәртебе',
        status_in_plan: 'жоспарда бар',
        status_in_repository: 'репозиторийде бар',
        status_missing: 'қосылады',
        all_statuses: 'барлығы',
        selected_count: 'таңдалды',
        select_new: 'жаңаларын таңдау',
        select_visible: 'көрінетіндерді таңдау',
        clear_selection: 'таңдауды өшіру',
        added_details: 'Қосу нәтижесі',
        compare_ready: 'Салыстыру дайын',
        light_mode: 'жеңіл режим',
        reference_limits: 'Бет тоқтап қалмауы үшін жылдам таңдау көрсетілді. Жоспарлағыш толық ЕПВО деректерін пайдаланады.',
        loading_compare: 'ЕПВО-мен салыстырып жатырмын. Бұл бірнеше секунд алуы мүмкін…',
    },
    en: {
        epvo_match: 'Typical EPVO course completeness',
        epvo_quality_notes: 'EPVO quality notes',
        similar_epvo_programs: 'Similar EPVO programmes',
        typical_epvo_los: 'Typical EPVO learning outcomes',
        disciplines: 'Disciplines',
        similarity: 'Similarity',
        expert_support: 'Expert support',
        selected_scopes: 'Selected directions and groups',
        expert_links: 'Expert links',
        quality_verdict: 'Quality verdict',
        priority_missing: 'Priority missing items',
        apply_priority: 'Add selected courses',
        rebuild_hint: 'After adding them, rebuild A/B/C variants in the plan builder.',
        open_plan_builder: 'Open plan builder',
        quality_formula: 'Formula: 70% completeness against typical EPVO courses + 30% expert support for course–LO links.',
        epvo_match_hint: 'This shows how many typical courses from the EPVO reference set are already present in the plan.',
        plan_from_epvo: 'Plan courses from EPVO',
        repository_status: 'Status',
        status_in_plan: 'already in plan',
        status_in_repository: 'in repository',
        status_missing: 'will be added',
        all_statuses: 'all',
        selected_count: 'selected',
        select_new: 'select new',
        select_visible: 'select visible',
        clear_selection: 'clear selection',
        added_details: 'Apply result',
        compare_ready: 'Comparison ready',
        light_mode: 'light mode',
        reference_limits: 'A fast sample is shown so the page does not freeze. The planner still uses the full EPVO dataset.',
        loading_compare: 'Comparing with EPVO. This can take a few seconds…',
    },
}

export default function EpvoComparison() {
    const { id } = useParams()
    const { t, localize, language } = useLanguage()
    const [data, setData] = useState(null)
    const [error, setError] = useState('')
    const [applying, setApplying] = useState(false)
    const [notice, setNotice] = useState(null)
    const [statusFilter, setStatusFilter] = useState('all')
    const [selectedPriorityIds, setSelectedPriorityIds] = useState([])
    const l = key => (labels[language] || labels.ru)[key] || key
    const dash = '—'

    const repositoryStatusLabel = status => {
        if (status === 'in_plan') return l('status_in_plan')
        if (status === 'in_repository') return l('status_in_repository')
        return l('status_missing')
    }
    const filteredPriority = (data?.missing_priority || []).filter(item => statusFilter === 'all' || item.repository_status === statusFilter)
    const statusCounts = (data?.missing_priority || []).reduce((acc, item) => {
        const status = item.repository_status || 'missing'
        acc[status] = (acc[status] || 0) + 1
        acc.all = (acc.all || 0) + 1
        return acc
    }, { all: 0 })
    const togglePriority = idValue => {
        setSelectedPriorityIds(current => current.includes(idValue) ? current.filter(value => value !== idValue) : [...current, idValue])
    }
    const selectVisible = () => setSelectedPriorityIds(filteredPriority.slice(0, 10).map(item => item.id))
    const selectNew = () => setSelectedPriorityIds((data?.missing_priority || []).filter(item => item.repository_status === 'missing').map(item => item.id))
    const clearSelection = () => setSelectedPriorityIds([])

    const applyPriority = async () => {
        try {
            setApplying(true)
            setNotice(null)
            const response = await axios.post(`/api/epvo/projects/${id}/apply-priority`, {
                discipline_ids: selectedPriorityIds,
            })
            setNotice({ type: 'success', text: `${response.data.message} ${l('rebuild_hint')}`, applied: response.data.applied || [] })
            const refreshed = await axios.get(`/api/epvo/compare/${id}`, { params: { language } })
            setData(refreshed.data)
        } catch (err) {
            const detail = err.response?.data?.detail
            setNotice({ type: 'error', text: formatApiError(err, t('error')) })
        } finally {
            setApplying(false)
        }
    }

    useEffect(() => {
        setData(null)
        setError('')
        axios.get(`/api/epvo/compare/${id}`, { params: { language } })
            .then(response => setData(response.data))
            .catch(err => {
                const detail = err.response?.data?.detail
                setError(formatApiError(err, t('error')))
            })
    }, [id, language])

    useEffect(() => {
        if (data?.missing_priority?.length) {
            const missingIds = data.missing_priority.filter(item => item.repository_status === 'missing').map(item => item.id)
            setSelectedPriorityIds(missingIds.length ? missingIds : data.missing_priority.slice(0, 10).map(item => item.id))
        }
    }, [data])

    if (!data && !error) return <div className="workspace-page"><LoadingSpinner /><p style={{ textAlign: 'center', color: '#667' }}>{l('loading_compare')}</p></div>

    return <div className="workspace-page">
        <header className="workspace-header">
            <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div><Link to={`/projects/${id}`}>← {t('back')}</Link><h1>{t('compare_epvo')}</h1></div>
                <LanguageSelector />
            </div>
        </header>
        <main className="container workspace-main">
            {error ? <div className="card">{error}</div> : <>
                <div className="card" style={{ background: '#f8fbff', border: '1px solid #dbeafe' }}>
                    <b>{l('compare_ready')}</b>
                    <span style={{ marginLeft: 10, color: '#667' }}>
                        {data.elapsed_seconds ? `${data.elapsed_seconds}s · ` : ''}{l('light_mode')}
                    </span>
                    <div style={{ color: '#667', fontSize: 13, marginTop: 4 }}>{l('reference_limits')}</div>
                </div>

                <div className="stat-grid">
                    <div className="stat-card"><div className="stat-value">{data.match_percentage || 0}%</div><div className="stat-label">{l('epvo_match')}</div></div>
                    <div className="stat-card"><div className="stat-value">{data.reference_disciplines}</div><div className="stat-label">{t('epvo_reference_courses')}</div></div>
                    <div className="stat-card"><div className="stat-value">{data.present_count}</div><div className="stat-label">{t('present_in_plan')}</div></div>
                    <div className="stat-card"><div className="stat-value">{data.epvo_plan_course_percentage || 0}%</div><div className="stat-label">{l('plan_from_epvo')}</div></div>
                    <div className="stat-card"><div className="stat-value">{data.expert_supported_percentage || 0}%</div><div className="stat-label">{l('expert_support')}</div></div>
                </div>
                <p style={{ color: '#667', marginTop: '-8px', marginBottom: 18, fontSize: 13 }}>{l('epvo_match_hint')}</p>

                <div className="card" style={{ borderLeft: `5px solid ${data.epvo_quality_status === 'passed' ? '#2e7d32' : data.epvo_quality_status === 'borderline' ? '#e67e22' : '#c62828'}` }}>
                    <div className="section-head">
                        <h2>{l('quality_verdict')}</h2>
                        <span className={`status-pill ${data.epvo_quality_status === 'passed' ? 'status-active' : 'status-draft'}`}>{data.epvo_quality_score || 0}%</span>
                    </div>
                    <p style={{ marginTop: 0 }}>{data.epvo_quality_label}</p>
                    <p style={{ color: '#667', fontSize: 13 }}>{l('quality_formula')}</p>
                </div>

                {data.scope_summary?.length > 0 && <div className="card">
                    <div className="section-head"><h2>{l('selected_scopes')}</h2><span className="status-pill status-active">{data.scope}</span></div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                        {data.scope_summary.map(scope => <div key={scope.label} style={{ padding: 12, borderRadius: 10, background: '#f6f9fc', border: '1px solid #e1e8f0' }}>
                            <b>{scope.label === 'secondary' ? '2' : '1'}: {scope.group_code || scope.direction_code || t('all_domains')}</b>
                            <div style={{ color: '#667', fontSize: 13 }}>{scope.scope}; {scope.reference_disciplines} {l('disciplines').toLowerCase()}</div>
                        </div>)}
                    </div>
                </div>}

                {(data.weak_spots?.length > 0 || data.recommendations?.length > 0) && <div className="card">
                    <div className="section-head"><h2>{l('epvo_quality_notes')}</h2><span className="status-pill status-draft">{data.group_code || data.direction_code || t('all_domains')}</span></div>
                    {data.weak_spots?.map((item, index) => <p key={`w-${index}`}>⚠️ {item}</p>)}
                    {data.recommendations?.map((item, index) => <p key={`r-${index}`}>💡 {item}</p>)}
                    <p style={{ color: '#667', fontSize: 13 }}>{l('expert_support')}: {data.expert_supported_matches}/{data.total_plan_matches} LO-связей в плане имеют поддержку экспертной разметки ЕПВО.</p>
                </div>}

                {notice && <div className="card" style={{ borderLeft: `5px solid ${notice.type === 'success' ? '#2e7d32' : '#c62828'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span>{notice.text}</span>
                        {notice.type === 'success' && <Link to={`/projects/${id}/plan?epvoApplied=1`} className="btn btn-primary">{l('open_plan_builder')}</Link>}
                    </div>
                    {notice.applied?.length > 0 && <div style={{ marginTop: 10 }}>
                        <b>{l('added_details')}</b>
                        <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                            {notice.applied.slice(0, 10).map(item => (
                                <div key={item.id} style={{ color: '#566', fontSize: 13 }}>
                                    {item.status === 'created' ? '+' : '✓'} {localize(item.title_translations || item.title)}
                                </div>
                            ))}
                        </div>
                    </div>}
                </div>}

                {data.missing_priority?.length > 0 && <div className="card">
                    <div className="section-head">
                        <h2>{l('priority_missing')}</h2>
                        <button className="btn btn-primary" onClick={applyPriority} disabled={applying || selectedPriorityIds.length === 0}>
                            {applying ? `${t('loading')}…` : l('apply_priority')}
                        </button>
                    </div>
                    <p style={{ color: '#667', marginTop: 0 }}>{l('rebuild_hint')}</p>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                        {['all', 'missing', 'in_repository', 'in_plan'].map(status => (
                            <button
                                key={status}
                                className={statusFilter === status ? 'btn btn-primary' : 'btn btn-secondary'}
                                style={{ padding: '6px 10px' }}
                                onClick={() => setStatusFilter(status)}
                            >
                                {status === 'all' ? l('all_statuses') : repositoryStatusLabel(status)} ({statusCounts[status] || 0})
                            </button>
                        ))}
                        <span style={{ color: '#667', alignSelf: 'center' }}>{l('selected_count')}: {selectedPriorityIds.length}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                        <button className="btn btn-secondary" style={{ padding: '6px 10px' }} onClick={selectNew}>{l('select_new')}</button>
                        <button className="btn btn-secondary" style={{ padding: '6px 10px' }} onClick={selectVisible}>{l('select_visible')}</button>
                        <button className="btn btn-secondary" style={{ padding: '6px 10px' }} onClick={clearSelection}>{l('clear_selection')}</button>
                    </div>
                    <div className="table-wrap"><table className="table"><thead><tr><th></th><th>{t('title')}</th><th>{t('credits')}</th><th>{t('semester')}</th><th>{t('source_programs')}</th><th>{l('expert_links')}</th><th>{l('repository_status')}</th><th>{l('similarity')}</th></tr></thead><tbody>
                        {filteredPriority.slice(0, 10).map(item => <tr key={item.id}><td><input type="checkbox" checked={selectedPriorityIds.includes(item.id)} onChange={() => togglePriority(item.id)} /></td><td>{localize(item.title_translations || item.title)}</td><td>{item.credits || dash}</td><td>{item.semester || dash}</td><td>{item.source_program_count}</td><td>{item.expert_link_count || 0}</td><td><span className="status-pill status-draft">{repositoryStatusLabel(item.repository_status)}</span></td><td>{Math.round((item.relevance || 0) * 100)}%</td></tr>)}
                    </tbody></table></div>
                </div>}

                {data.similar_programs?.length > 0 && <div className="card">
                    <div className="section-head"><h2>{localText('Сравнение программы с аналогичными ОП ЕПВО', 'Бағдарламаны ұқсас ЕПВО ББ-мен салыстыру', 'Compare with similar EPVO programmes')}</h2></div>
                    <p style={{ color: '#667', fontSize: 13, marginTop: 0 }}>{localText('Здесь показаны похожие программы из выбранного направления ЕПВО, их типовые дисциплины и результаты обучения.', 'Мұнда таңдалған ЕПВО бағыты бойынша ұқсас бағдарламалар, типтік пәндер және оқу нәтижелері көрсетіледі.', 'This section shows similar programmes from the selected EPVO scope, their typical courses and learning outcomes.')}</p>
                    <div className="table-wrap"><table className="table"><thead><tr><th>{t('title')}</th><th>{t('credits')}</th><th>{l('disciplines')}</th><th>LO</th><th>{l('similarity')}</th></tr></thead><tbody>
                        {data.similar_programs.map(item => <tr key={item.source_id}><td><b>{item.title}</b><div style={{ fontSize: 12, color: '#667' }}>{item.goal}</div></td><td>{item.credits || dash}</td><td>{item.discipline_count}</td><td>{item.lo_count}</td><td>{Math.round((item.similarity || 0) * 100)}%</td></tr>)}
                    </tbody></table></div>
                </div>}

                {data.typical_los?.length > 0 && <div className="card">
                    <div className="section-head"><h2>{l('typical_epvo_los')}</h2></div>
                    {data.typical_los.map((item, index) => <div key={index} style={{ padding: '10px 0', borderTop: index ? '1px solid #eef2f7' : 'none' }}><b>{item.count}×</b> {item.text}</div>)}
                </div>}

                <div className="card">
                    <div className="section-head"><h2>{t('typical_epvo_courses')}</h2><span className="status-pill status-draft">{data.group_code || data.direction_code || t('all_domains')}</span></div>
                    <div className="table-wrap"><table className="table"><thead><tr><th>{t('title')}</th><th>{t('credits')}</th><th>{t('semester')}</th><th>{t('source_programs')}</th><th>{l('expert_links')}</th><th>{l('similarity')}</th><th>{t('status')}</th></tr></thead><tbody>
                        {data.typical_disciplines.map(item => <tr key={item.id}><td>{localize(item.title_translations || item.title)}</td><td>{item.credits || dash}</td><td>{item.semester || dash}</td><td>{item.source_program_count}</td><td>{item.expert_link_count || 0}</td><td>{Math.round((item.relevance || 0) * 100)}%</td><td><span className={`status-pill ${item.present ? 'status-active' : 'status-draft'}`}>{item.present ? t('present') : t('missing')}</span></td></tr>)}
                    </tbody></table></div>
                </div>
            </>}
        </main>
    </div>
}
