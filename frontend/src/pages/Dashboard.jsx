import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'
import { useNotifications } from '../contexts/NotificationContext'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'
const DEMO_PROJECTS = [
    { id: 'demo-ict-health', title: 'ICT в здравоохранении', domain1: 'ICT', domain2: 'Здравоохранение', created_at: '2026-08-15T00:00:00Z', status: 'active' },
    { id: 'demo-ai-data', title: 'Искусственный интеллект и анализ данных', domain1: 'ICT', domain2: 'Data Science', created_at: '2026-08-20T00:00:00Z', status: 'active' },
    { id: 'demo-cyber-law', title: 'Кибербезопасность и цифровое право', domain1: 'Кибербезопасность', domain2: 'Право', created_at: '2026-08-28T00:00:00Z', status: 'draft' },
]

export default function Dashboard() {
    const { user, logout } = useAuth()
    const { t, language } = useLanguage()
    const navigate = useNavigate()
    const { notify } = useNotifications()
    const [projects, setProjects] = useState([])
    const [loading, setLoading] = useState(true)
    const [loadError, setLoadError] = useState(false)
    const [stats, setStats] = useState({ totalProjects: 0, totalCourses: 0, activePlans: 0 })

    useEffect(() => {
        if (!user) { navigate('/login'); return }
        if (DEMO_MODE) {
            setProjects(DEMO_PROJECTS)
            setStats({ totalProjects: DEMO_PROJECTS.length, totalCourses: 1280, activePlans: 2 })
            setLoading(false)
            return
        }
        setLoadError(false)
        Promise.all([axios.get('/api/projects'), axios.get('/api/repository/stats')])
            .then(([projectsRes, repositoryStats]) => {
                setProjects(projectsRes.data)
                setStats({
                    totalProjects: projectsRes.data.length,
                    totalCourses: repositoryStats.data.total_courses || 0,
                    activePlans: projectsRes.data.filter(p => p.status === 'active').length
                })
            })
            .catch(error => {
                console.error('Error fetching data:', error)
                setLoadError(true)
            })
            .finally(() => setLoading(false))
    }, [user, navigate])

    const handleDeleteProject = async (projectId) => {
        if (!window.confirm(t('confirm_delete'))) return
        if (DEMO_MODE) {
            setProjects(projects.filter(project => project.id !== projectId))
            return
        }
        try {
            await axios.delete(`/api/projects/${projectId}`)
            setProjects(projects.filter(p => p.id !== projectId))
        } catch (error) {
            console.error('Error deleting project:', error)
            notify(t('project_delete_error'))
        }
    }

    if (loading) return <LoadingSpinner />

    const copy = t('dashboard_subtitle')
    const versionsLabel = t('versions')

    return (
        <div className="app-shell">
            <header className="app-header">
                <div className="container">
                    <Link to="/" className="app-brand"><span className="app-brand-mark">CK</span><span>Curriculum KAG</span></Link>
                    <div className="app-nav">
                        <LanguageSelector />
                        <Link to="/repository" className="app-nav-link">{t('repository')}</Link>
                        <Link to="/versions" className="app-nav-link">{versionsLabel}</Link>
                        <span className="user-chip">{user?.full_name || user?.email}</span>
                        <button onClick={() => { logout(); navigate('/login') }} className="btn btn-secondary">{t('logout')}</button>
                    </div>
                </div>
            </header>

            <main className="container">
                <section className="page-hero">
                    <div>
                        <div className="eyebrow">{t('curriculum_workspace')}</div>
                        <h1 className="page-title">{t('projects')}</h1>
                        <p className="page-subtitle">{copy}</p>
                    </div>
                    <Link to="/projects/new" className="btn btn-primary">+ {t('create_project')}</Link>
                </section>

                {loadError && <div className="inline-alert inline-alert-error" role="alert">
                    <span className="inline-alert-icon" aria-hidden="true">!</span>
                    <div><strong>{t('dashboard_load_error')}</strong><p>{t('dashboard_load_error_hint')}</p></div>
                    <button className="btn btn-secondary" onClick={() => window.location.reload()}>{t('retry')}</button>
                </div>}

                <section className="stat-grid" aria-label={t('dashboard_overview')}>
                    <div className="stat-card"><span className="stat-dot"/><div className="stat-value">{stats.totalProjects}</div><div className="stat-label">{t('total_projects')}</div></div>
                    <div className="stat-card"><span className="stat-dot stat-dot-success"/><div className="stat-value">{stats.totalCourses}</div><div className="stat-label">{t('total_courses')}</div></div>
                    <div className="stat-card"><span className="stat-dot stat-dot-warning"/><div className="stat-value">{stats.activePlans}</div><div className="stat-label">{t('active_plans')}</div></div>
                </section>

                <section className="card">
                    <div className="section-head"><h2>{t('projects')}</h2><span className="section-count" aria-label={`${projects.length} ${t('projects')}`}>{projects.length}</span></div>
                    {projects.length === 0 ? (
                        <div className="empty-state"><p>{t('no_projects')}</p><Link to="/projects/new" className="btn btn-primary">{t('create_project')}</Link></div>
                    ) : (
                        <div className="table-wrap"><table className="table">
                            <caption className="sr-only">{t('projects')}</caption>
                            <thead><tr><th>{t('program_name')}</th><th>{t('domains')}</th><th>{t('date_created')}</th><th>{t('status')}</th><th>{t('actions')}</th></tr></thead>
                            <tbody>{projects.map(project => (
                                <tr key={project.id}>
                                    <td><strong>{project.title}</strong></td>
                                    <td className="table-muted">{project.domain1}, {project.domain2}</td>
                                    <td className="table-muted">{project.created_at ? new Date(project.created_at).toLocaleDateString() : '—'}</td>
                                    <td><span className={`status-pill ${project.status === 'active' ? 'status-active' : 'status-draft'}`}>{project.status === 'active' ? t('active') : t('draft')}</span></td>
                                    <td><div className="table-actions"><Link to={`/projects/${project.id}`} className="btn btn-primary">{t('open')}</Link><button aria-label={`${t('delete')}: ${project.title}`} onClick={() => handleDeleteProject(project.id)} className="btn btn-danger">{t('delete')}</button></div></td>
                                </tr>
                            ))}</tbody>
                        </table></div>
                    )}
                </section>

                <section className="quick-grid">
                    <Link to="/repository" className="card quick-card"><div className="quick-icon" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5A2.5 2.5 0 0 0 17.5 16H4V5.5Zm0 10.5h13.5A2.5 2.5 0 0 1 20 18.5V21H6.5A2.5 2.5 0 0 1 4 18.5V16Z"/></svg></div><div><h3>{t('course_repository')}</h3><p>{t('course_repository_desc')}</p></div></Link>
                    <Link to="/projects/new" className="card quick-card"><div className="quick-icon quick-icon-accent" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M12 5v14M5 12h14"/></svg></div><div><h3>{t('create_project')}</h3><p>{t('create_project_desc')}</p></div></Link>
                    <Link to="/research" className="card quick-card"><div className="quick-icon quick-icon-success" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M5 18V10M12 18V6M19 18v-4"/></svg></div><div><h3>{t('research_dashboard')}</h3><p>{t('research_dashboard_desc')}</p></div></Link>
                </section>
            </main>
        </div>
    )
}
