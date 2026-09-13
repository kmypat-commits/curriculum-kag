import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatApiError } from '../utils/errors'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'

const DEMO_DETAILS = {
    'demo-ict-health': {
        title: 'ICT в здравоохранении', domain1: 'ICT', domain2: 'Здравоохранение', level: 'Бакалавриат',
        goal: 'Подготовка специалистов, которые проектируют цифровые решения для клиник, медицинских данных и сервисов общественного здоровья.',
        credits: 240, semesters: 8, outcomes: 12, courses: 48,
        checks: ['Объём: 240 кредитов', 'ГОСО: профильные и общеуниверситетские компоненты', 'Пререквизиты проверены', 'Нагрузка распределена по 8 семестрам'],
        semestersList: ['Основы программирования и академическое письмо', 'Математика, данные и анатомия цифрового здоровья', 'Базы данных и управление медицинской информацией', 'UX медицинских сервисов и аналитика', 'Информационная безопасность и интероперабельность', 'Проектирование клинических систем', 'Практика и исследовательский семинар', 'Дипломный проект'],
        coursesList: ['Программирование на Python', 'Академическое письмо', 'Математика для цифрового здоровья', 'Анатомия и физиология', 'Базы данных', 'Медицинская информатика', 'UX-исследования', 'Аналитика медицинских данных', 'Информационная безопасность', 'Интероперабельность медицинских систем', 'Проектирование клинических решений', 'Практика и дипломный проект']
    },
    'demo-ai-data': {
        title: 'Искусственный интеллект и анализ данных', domain1: 'ICT', domain2: 'Data Science', level: 'Магистратура',
        goal: 'Междисциплинарная программа по машинному обучению, исследовательским методам и ответственному применению AI.',
        credits: 60, semesters: 4, outcomes: 8, courses: 20,
        checks: ['Объём: 60 кредитов', 'Исследовательский трек выделен отдельно', 'Пререквизиты для ML связаны', 'Bridge-модуль выравнивает входной уровень'],
        semestersList: ['Математические методы и Python для исследований', 'Машинное обучение и инженерия данных', 'Ответственный AI и исследовательская практика', 'Магистерская диссертация'],
        coursesList: ['Математическая статистика', 'Python для исследований', 'Машинное обучение', 'Инженерия данных', 'Глубокое обучение', 'MLOps', 'Ответственный AI', 'Исследовательский семинар']
    },
    'demo-cyber-law': {
        title: 'Кибербезопасность и цифровое право', domain1: 'Кибербезопасность', domain2: 'Право', level: 'Докторантура',
        goal: 'Исследовательская программа на стыке управления киберрисками, цифрового регулирования и доказательного policy design.',
        credits: 180, semesters: 6, outcomes: 10, courses: 30,
        checks: ['Объём: 180 кредитов', 'Правовые и технические результаты сбалансированы', 'Исследовательские пререквизиты учтены', 'Семестровая траектория согласована'],
        semestersList: ['Методология и теория киберрисков', 'Цифровое право и сравнительная политика', 'Исследовательский дизайн', 'Полевое исследование', 'Публикационный семинар', 'Докторская диссертация'],
        coursesList: ['Теория киберрисков', 'Методология научных исследований', 'Цифровое право', 'Сравнительная политика', 'Privacy Engineering', 'Критическая инфраструктура', 'Полевое исследование', 'Публикационный семинар']
    }
}

function DemoProjectDetails({ project, onBack }) {
    const outcomes = ['Формулировать измеримые результаты обучения программы', 'Проектировать междисциплинарную учебную траекторию', 'Проверять пререквизиты и семестровую нагрузку', 'Обосновывать выбор дисциплин данными и требованиями ГОСО']
    return <div className="app-shell">
        <header className="app-header"><div className="container"><div className="app-brand"><button className="btn btn-secondary" onClick={onBack}>← Программы</button><span>Curriculum KAG</span></div><span className="status-pill status-active">DEMO-режим</span></div></header>
        <main className="container" style={{ paddingTop: 36 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}><span style={{ color: '#366092', fontSize: 14 }}>{project.level}</span><span style={{ color: '#617089' }}>·</span><span style={{ color: '#617089', fontSize: 14 }}>{project.domain1} · {project.domain2}</span></div>
            <h1 className="page-title" style={{ maxWidth: 900 }}>{project.title}</h1>
            <p className="page-subtitle" style={{ maxWidth: 820 }}>Демонстрационный проект в том же рабочем формате, что и реальные программы системы.</p>
            <div className="demo-details-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 300px', gap: 24, marginTop: 28, alignItems: 'start' }}>
                <div><div className="card"><h2 style={{ marginTop: 0 }}>Цель программы</h2><p style={{ lineHeight: 1.6 }}>{project.goal}</p></div>
                    <div className="card"><h2 style={{ marginTop: 0 }}>Результаты обучения (LO)</h2>{outcomes.map((outcome, index) => <div key={outcome} style={{ display: 'flex', gap: 14, padding: '14px 0', borderBottom: index === outcomes.length - 1 ? 'none' : '1px solid #e8edf1' }}><strong style={{ minWidth: 42, color: '#366092' }}>LO{index + 1}</strong><span style={{ lineHeight: 1.5 }}>{outcome}</span></div>)}</div>
                    <div className="card"><h2 style={{ marginTop: 0 }}>Дисциплины программы</h2><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10 }}>{project.coursesList.map((course, index) => <div key={course} style={{ padding: '12px 14px', border: '1px solid #e8edf1', borderRadius: 10, background: '#fbfcfe' }}><strong style={{ display: 'block', color: '#366092', fontSize: 12 }}>Дисциплина {index + 1}</strong><span style={{ display: 'block', marginTop: 5, lineHeight: 1.35 }}>{course}</span></div>)}</div></div>
                    <div className="card"><h2 style={{ marginTop: 0 }}>Учебная траектория</h2>{project.semestersList.map((item, index) => <div key={item} style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 16, padding: '12px 0', borderBottom: index === project.semestersList.length - 1 ? 'none' : '1px solid #e8edf1' }}><strong style={{ color: '#366092' }}>Семестр {index + 1}</strong><span>{item}</span></div>)}</div>
                </div>
                <aside><div className="card"><h3 style={{ marginTop: 0, color: '#366092' }}>Ограничения</h3><div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '14px 0 20px' }}><span className="status-pill status-active">{project.domain1}</span><span className="status-pill status-draft">{project.domain2}</span></div><ul style={{ paddingLeft: 20, lineHeight: 1.9, color: '#425466' }}><li>Семестров: <b>{project.semesters}</b></li><li>Кредитов: <b>{project.credits}</b></li><li>Дисциплин: <b>{project.courses}</b></li><li>Результатов LO: <b>{project.outcomes}</b></li></ul></div>
                    <div className="card"><h3 style={{ marginTop: 0, color: '#366092' }}>Проверка качества</h3>{project.checks.map(check => <p key={check} style={{ marginTop: 12, lineHeight: 1.4, color: '#245c46' }}>✓ {check}</p>)}</div></aside>
            </div>
        </main>
    </div>
}

export default function ProjectDetails() {
    const { id } = useParams()
    const { user } = useAuth()
    const { t, language, localizeDomain } = useLanguage()
    const navigate = useNavigate()
    const [project, setProject] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [epvoForm, setEpvoForm] = useState(null)
    const [educationAreas, setEducationAreas] = useState([])
    const [directions, setDirections] = useState([])
    const [groups, setGroups] = useState([])
    const [savingEpvo, setSavingEpvo] = useState(false)
    const [epvoNotice, setEpvoNotice] = useState(null)

    useEffect(() => {
        fetchProject()
    }, [id])

    const fetchProject = async () => {
        try {
            setLoading(true)
            if (DEMO_MODE && DEMO_DETAILS[id]) {
                setProject(DEMO_DETAILS[id])
                setLoading(false)
                return
            }
            const response = await axios.get(`/api/projects/${id}`)
            setProject(response.data)
            const c = response.data.constraints || {}
            setEpvoForm({
                education_level: c.education_level || 'bachelor',
                education_area: c.education_area || '',
                direction_code: c.direction_code || '',
                group_code: c.group_code || '',
                program_type: c.program_type || 'standard',
                instruction_language: c.instruction_language || 'ru',
                duration_years: c.duration_years || 4,
                total_semesters: c.total_semesters || 8,
                total_credits: c.total_credits || 240,
                max_credits_per_semester: c.max_credits_per_semester || 30,
                min_domain1_percent: c.min_domain1_percent ?? 40,
                min_domain2_percent: c.min_domain2_percent ?? 40,
                allow_new_courses: c.allow_new_courses ?? true,
                max_new_courses: c.max_new_courses || 5
            })
        } catch (err) {
            console.error('Error fetching project:', err)
            setError(formatApiError(err, t('error')))
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        if (!epvoForm?.education_level) return
        axios.get('/api/epvo/education-areas', { params: { education_level: epvoForm.education_level, language } })
            .then(response => setEducationAreas(response.data))
            .catch(() => setEducationAreas([]))
    }, [epvoForm?.education_level, language])

    useEffect(() => {
        if (!epvoForm?.education_area) { setDirections([]); return }
        axios.get('/api/epvo/directions', { params: { education_level: epvoForm.education_level, education_area: epvoForm.education_area, language } })
            .then(response => setDirections(response.data))
            .catch(() => setDirections([]))
    }, [epvoForm?.education_level, epvoForm?.education_area, language])

    useEffect(() => {
        if (!epvoForm?.direction_code) { setGroups([]); return }
        axios.get('/api/epvo/groups', { params: { direction_code: epvoForm.direction_code, language } })
            .then(response => setGroups(response.data))
            .catch(() => setGroups([]))
    }, [epvoForm?.direction_code, language])

    const updateEpvoForm = (field, value) => {
        const reset = field === 'education_area'
            ? { direction_code: '', group_code: '' }
            : field === 'direction_code' ? { group_code: '' } : {}
        setEpvoForm({ ...epvoForm, ...reset, [field]: value })
    }

    const saveEpvoSetup = async () => {
        setSavingEpvo(true)
        setEpvoNotice(null)
        try {
            const payload = { constraints: { ...(project.constraints || {}), ...epvoForm } }
            const response = await axios.patch(`/api/projects/${id}/constraints`, payload)
            setProject({ ...project, constraints: response.data.constraints })
            setEpvoNotice({ type: 'success', text: t('epvo_setup_saved') })
        } catch (err) {
            setEpvoNotice({ type: 'error', text: formatApiError(err, t('error')) })
        } finally {
            setSavingEpvo(false)
        }
    }

    if (loading) return <LoadingSpinner />

    if (DEMO_MODE && DEMO_DETAILS[id]) return <DemoProjectDetails project={DEMO_DETAILS[id]} onBack={() => navigate('/')} />

    if (error) return (
        <div className="container" style={{ textAlign: 'center', paddingTop: '100px' }}>
            <div className="card" style={{ borderColor: 'red' }}>
                <h2 style={{ color: 'red' }}>{t('error')}</h2>
                <p>{error}</p>
                <button className="btn btn-primary" onClick={() => navigate('/')}>{t('back')}</button>
            </div>
        </div>
    )

    if (!project) return null
    const c = project.constraints || {}
    const epvoCodeInvalid = value => !value || value === '1'
    const epvoScopeInvalid = epvoCodeInvalid(c.education_area) || epvoCodeInvalid(c.direction_code) || epvoCodeInvalid(c.group_code)
    const isInterdisciplinary = ['interdisciplinary', 'joint'].includes(c.program_type)
    const secondaryInvalid = isInterdisciplinary && (
        epvoCodeInvalid(c.secondary_education_area) || epvoCodeInvalid(c.secondary_direction_code) || epvoCodeInvalid(c.secondary_group_code)
    )
    const needsEpvoSetup = epvoScopeInvalid || secondaryInvalid

    return (
        <div style={{ minHeight: '100vh', background: '#f5f7fa' }}>
            {/* Header */}
            <header style={{
                background: 'white',
                borderBottom: '1px solid #e0e0e0',
                padding: '15px 0'
            }}>
                <div className="container" style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                        <Link to="/" style={{ textDecoration: 'none', color: '#666' }}>← {t('back')}</Link>
                        <h1 style={{ margin: 0, fontSize: '24px', color: '#366092' }}>
                            {project.title}
                        </h1>
                    </div>
                    <div style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
                        <LanguageSelector />
                        <Link to={'/projects/' + id + '/graph'} className="btn btn-secondary">
                            ◉ {t('open_prerequisite_graph')}
                        </Link>
                        <Link to={`/projects/${id}/plan`} className="btn btn-primary">
                            🛠 {t('plan_builder')}
                        </Link>
                        <Link to={`/projects/${id}/epvo`} className="btn btn-secondary">{t('compare_epvo')}</Link>
                    </div>
                </div>
            </header>

            <div className="container" style={{ paddingTop: '30px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '30px' }}>

                    {/* Main Content */}
                    <div>
                        {needsEpvoSetup && (
                            <div className="card" style={{ marginBottom: '20px', borderTop: '2px solid #f9a825', background: '#fff8e1' }}>
                                <h3 style={{ marginTop: 0, color: '#8a5a00' }}>⚠️ {t('epvo_setup_incomplete')}</h3>
                                <p style={{ marginBottom: 10, lineHeight: 1.5 }}>
                                    {t('epvo_setup_warning')}
                                </p>
                                <p style={{ marginBottom: 12, fontSize: 13, color: '#6b5a2a' }}>
                                    {t('current_epvo_values', { area: c.education_area || '—', direction: c.direction_code || '—', group: c.group_code || '—' })}.
                                </p>
                                <Link to={`/projects/${id}/epvo`} className="btn btn-secondary">
                                    {t('compare_epvo')}
                                </Link>
                                {epvoForm && (
                                    <div style={{ marginTop: 14, display: 'grid', gap: 8 }}>
                                        <select className="form-control" value={epvoForm.education_area} onChange={e => updateEpvoForm('education_area', e.target.value)}>
                                            <option value="">{t('education_area_option')}</option>
                                            {educationAreas.map(area => <option key={area.code} value={area.code}>{area.title}</option>)}
                                        </select>
                                        <select className="form-control" value={epvoForm.direction_code} onChange={e => updateEpvoForm('direction_code', e.target.value)} disabled={!epvoForm.education_area}>
                                            <option value="">{t('direction_option')}</option>
                                            {directions.map(direction => <option key={direction.code} value={direction.code}>{direction.title}</option>)}
                                        </select>
                                        <select className="form-control" value={epvoForm.group_code} onChange={e => updateEpvoForm('group_code', e.target.value)} disabled={!epvoForm.direction_code}>
                                            <option value="">{t('group_option')}</option>
                                            {groups.map(group => <option key={group.code} value={group.code}>{group.title}</option>)}
                                        </select>
                                        <button className="btn btn-primary" onClick={saveEpvoSetup} disabled={savingEpvo || !epvoForm.education_area || !epvoForm.direction_code || !epvoForm.group_code}>
                                            {savingEpvo ? t('saving') : t('save_epvo_setup')}
                                        </button>
                                        {epvoNotice && <div style={{ color: epvoNotice.type === 'error' ? '#b71c1c' : '#1b5e20', fontSize: 13 }}>{epvoNotice.text}</div>}
                                        {epvoNotice?.type === 'success' && <Link to={`/projects/${id}/plan`} className="btn btn-secondary">{t('rebuild_plan')}</Link>}
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="card" style={{ marginBottom: '20px' }}>
                            <h2 style={{ marginTop: 0 }}>{t('program_goal')}</h2>
                            <p style={{ lineHeight: '1.6', fontSize: '16px' }}>{project.goal || t('no_projects')}</p>
                        </div>

                        <div className="card">
                            <h2 style={{ marginTop: 0 }}>{t('learning_outcomes')} (LO)</h2>
                            <div style={{ marginTop: '15px' }}>
                                {project.latest_version?.learning_outcomes?.map((lo, index) => (
                                    <div key={lo.id} style={{
                                        padding: '12px',
                                        borderBottom: index === project.latest_version.learning_outcomes.length - 1 ? 'none' : '1px solid #eee',
                                        display: 'flex',
                                        gap: '15px'
                                    }}>
                                        <span style={{
                                            fontWeight: 'bold',
                                            color: '#366092',
                                            minWidth: '40px',
                                            padding: '4px 8px',
                                            background: '#eef2f7',
                                            borderRadius: '4px',
                                            height: 'fit-content'
                                        }}>
                                            {lo.lo_code || `LO${index + 1}`}
                                        </span>
                                        <span style={{ lineHeight: '1.5' }}>{lo.lo_text}</span>
                                    </div>
                                ))}
                                {(!project.latest_version?.learning_outcomes || project.latest_version.learning_outcomes.length === 0) && (
                                    <p style={{ color: '#666', textAlign: 'center', padding: '20px' }}>
                                        {t('no_projects')}
                                    </p>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Sidebar */}
                    <div>
                        <div className="card" style={{ marginBottom: '20px' }}>
                            <h3 style={{ marginTop: 0, color: '#366092', fontSize: '18px' }}>{t('constraints')}</h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                <div>
                                    <label style={{ fontSize: '12px', color: '#666', display: 'block' }}>{t('domains')}</label>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                                        <span className="badge" style={{ background: '#366092', color: 'white', padding: '4px 8px', borderRadius: '12px', fontSize: '12px' }}>
                                            {localizeDomain(project.domain1)}
                                        </span>
                                        <span className="badge" style={{ background: '#764ba2', color: 'white', padding: '4px 8px', borderRadius: '12px', fontSize: '12px' }}>
                                            {localizeDomain(project.domain2)}
                                        </span>
                                    </div>
                                </div>
                            </div>
                            <div style={{ borderTop: '1px solid #eee', paddingTop: '10px' }}>
                                <label style={{ fontSize: '12px', color: '#666', display: 'block' }}>{t('constraints')}</label>
                                <ul style={{ paddingLeft: '20px', margin: '5px 0', fontSize: '14px' }}>
                                    <li>{t('num_semesters')}: <b>{project.constraints?.total_semesters}</b></li>
                                    <li>{t('total_credits')}: <b>{project.constraints?.total_credits}</b></li>
                                    <li>{t('max_credits_semester')}: <b>{project.constraints?.max_credits_per_semester}</b></li>
                                </ul>
                            </div>
                            <div>
                                <label style={{ fontSize: '12px', color: '#666', display: 'block' }}>{t('status')}</label>
                                <span style={{
                                    display: 'inline-block',
                                    padding: '4px 12px',
                                    background: '#d4edda',
                                    color: '#155724',
                                    borderRadius: '12px',
                                    fontSize: '12px',
                                    marginTop: '5px'
                                }}>
                                    {project.latest_version?.status === 'active' ? t('active') : t('draft')}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="card" style={{ background: '#366092', color: 'white' }}>
                        <h3 style={{ marginTop: 0, fontSize: '16px' }}>{t('analytics')}</h3>
                        <p style={{ fontSize: '14px', opacity: 0.9 }}>
                            {t('check_coverage_description')}
                        </p>
                        <Link to={`/projects/${id}/coverage`} style={{
                            display: 'block',
                            textAlign: 'center',
                            padding: '10px',
                            background: 'white',
                            color: '#366092',
                            textDecoration: 'none',
                            borderRadius: '4px',
                            fontWeight: 'bold'
                        }}>
                            {t('check_coverage')}
                        </Link>
                    </div>
                </div>

            </div>
        </div>
    )
}
