import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'

export default function ProjectDetails() {
    const { id } = useParams()
    const { user } = useAuth()
    const { t, language } = useLanguage()
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
            setError(err.response?.data?.detail || 'Error loading project')
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
            setEpvoNotice({ type: 'success', text: 'ЕПВО-настройка сохранена. Теперь можно перестроить план.' })
        } catch (err) {
            setEpvoNotice({ type: 'error', text: err.response?.data?.detail?.[0]?.msg || err.response?.data?.detail || err.message })
        } finally {
            setSavingEpvo(false)
        }
    }

    if (loading) return <LoadingSpinner />

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
                            <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #f9a825', background: '#fff8e1' }}>
                                <h3 style={{ marginTop: 0, color: '#8a5a00' }}>⚠️ ЕПВО-настройка неполная</h3>
                                <p style={{ marginBottom: 10, lineHeight: 1.5 }}>
                                    Эта программа создана без корректного направления/группы ЕПВО или с заглушкой. Генератор может подбирать лишние дисциплины и bridge-модули.
                                </p>
                                <p style={{ marginBottom: 12, fontSize: 13, color: '#6b5a2a' }}>
                                    Текущие значения: область <b>{c.education_area || '—'}</b>, направление <b>{c.direction_code || '—'}</b>, группа <b>{c.group_code || '—'}</b>.
                                </p>
                                <Link to={`/projects/${id}/epvo`} className="btn btn-secondary">
                                    {t('compare_epvo')}
                                </Link>
                                {epvoForm && (
                                    <div style={{ marginTop: 14, display: 'grid', gap: 8 }}>
                                        <select className="form-control" value={epvoForm.education_area} onChange={e => updateEpvoForm('education_area', e.target.value)}>
                                            <option value="">Область образования</option>
                                            {educationAreas.map(area => <option key={area.code} value={area.code}>{area.title}</option>)}
                                        </select>
                                        <select className="form-control" value={epvoForm.direction_code} onChange={e => updateEpvoForm('direction_code', e.target.value)} disabled={!epvoForm.education_area}>
                                            <option value="">Направление подготовки</option>
                                            {directions.map(direction => <option key={direction.code} value={direction.code}>{direction.title}</option>)}
                                        </select>
                                        <select className="form-control" value={epvoForm.group_code} onChange={e => updateEpvoForm('group_code', e.target.value)} disabled={!epvoForm.direction_code}>
                                            <option value="">Группа ОП</option>
                                            {groups.map(group => <option key={group.code} value={group.code}>{group.title}</option>)}
                                        </select>
                                        <button className="btn btn-primary" onClick={saveEpvoSetup} disabled={savingEpvo || !epvoForm.education_area || !epvoForm.direction_code || !epvoForm.group_code}>
                                            {savingEpvo ? 'Сохранение…' : 'Сохранить ЕПВО-настройку'}
                                        </button>
                                        {epvoNotice && <div style={{ color: epvoNotice.type === 'error' ? '#b71c1c' : '#1b5e20', fontSize: 13 }}>{epvoNotice.text}</div>}
                                        {epvoNotice?.type === 'success' && <Link to={`/projects/${id}/plan`} className="btn btn-secondary">Перестроить план</Link>}
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
                                            {project.domain1}
                                        </span>
                                        <span className="badge" style={{ background: '#764ba2', color: 'white', padding: '4px 8px', borderRadius: '12px', fontSize: '12px' }}>
                                            {project.domain2}
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
