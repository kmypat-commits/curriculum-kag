import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'

export default function Dashboard() {
    const { user, logout } = useAuth()
    const { t, language } = useLanguage()
    const navigate = useNavigate()
    const [projects, setProjects] = useState([])
    const [loading, setLoading] = useState(true)
    const [stats, setStats] = useState({ totalProjects: 0, totalCourses: 0, activePlans: 0 })

    useEffect(() => {
        if (!user) { navigate('/login'); return }
        Promise.all([axios.get('/api/projects'), axios.get('/api/repository/stats')])
            .then(([projectsRes, repositoryStats]) => {
                setProjects(projectsRes.data)
                setStats({
                    totalProjects: projectsRes.data.length,
                    totalCourses: repositoryStats.data.total_courses || 0,
                    activePlans: projectsRes.data.filter(p => p.status === 'active').length
                })
            })
            .catch(error => console.error('Error fetching data:', error))
            .finally(() => setLoading(false))
    }, [user, navigate])

    const handleDeleteProject = async (projectId) => {
        if (!window.confirm(t('confirm_delete'))) return
        try {
            await axios.delete(`/api/projects/${projectId}`)
            setProjects(projects.filter(p => p.id !== projectId))
        } catch (error) {
            console.error('Error deleting project:', error)
            alert(t('project_delete_error'))
        }
    }

    if (loading) return <LoadingSpinner />

    const copy = language === 'ru'
        ? 'Проектируйте образовательные программы, проверяйте результаты обучения и управляйте учебными планами в одном спокойном рабочем пространстве.'
        : language === 'kk'
            ? 'Білім беру бағдарламаларын жобалаңыз, оқу нәтижелерін тексеріңіз және оқу жоспарларын бір жұмыс кеңістігінде басқарыңыз.'
            : 'Design programmes, verify learning outcomes and manage curricula in one focused workspace.'

    return (
        <div className="app-shell">
            <header className="app-header">
                <div className="container">
                    <Link to="/" className="app-brand"><span className="app-brand-mark">CK</span><span>Curriculum KAG</span></Link>
                    <div className="app-nav">
                        <LanguageSelector />
                        <Link to="/repository" className="app-nav-link">{t('repository')}</Link>
                        <Link to="/versions" className="app-nav-link">Версии</Link>
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

                <section className="stat-grid">
                    <div className="stat-card"><span className="stat-dot"/><div className="stat-value">{stats.totalProjects}</div><div className="stat-label">{t('total_projects')}</div></div>
                    <div className="stat-card"><span className="stat-dot" style={{background:'#248a3d',boxShadow:'0 0 0 6px #e8f7ed'}}/><div className="stat-value">{stats.totalCourses}</div><div className="stat-label">{t('total_courses')}</div></div>
                    <div className="stat-card"><span className="stat-dot" style={{background:'#9a5b00',boxShadow:'0 0 0 6px #fff6e5'}}/><div className="stat-value">{stats.activePlans}</div><div className="stat-label">{t('active_plans')}</div></div>
                </section>

                <section className="card">
                    <div className="section-head"><h2>{t('projects')}</h2><span style={{color:'#6e6e73',fontSize:13}}>{projects.length}</span></div>
                    {projects.length === 0 ? (
                        <div style={{textAlign:'center',padding:'52px 20px',color:'#6e6e73'}}><p>{t('no_projects')}</p><Link to="/projects/new" className="btn btn-primary" style={{marginTop:18}}>{t('create_project')}</Link></div>
                    ) : (
                        <div className="table-wrap"><table className="table">
                            <thead><tr><th>{t('program_name')}</th><th>{t('domains')}</th><th>{t('date_created')}</th><th>{t('status')}</th><th>{t('actions')}</th></tr></thead>
                            <tbody>{projects.map(project => (
                                <tr key={project.id}>
                                    <td><strong>{project.title}</strong></td>
                                    <td style={{color:'#6e6e73'}}>{project.domain1}, {project.domain2}</td>
                                    <td style={{color:'#6e6e73'}}>{project.created_at ? new Date(project.created_at).toLocaleDateString() : '—'}</td>
                                    <td><span className={`status-pill ${project.status === 'active' ? 'status-active' : 'status-draft'}`}>{project.status === 'active' ? t('active') : t('draft')}</span></td>
                                    <td><div style={{display:'flex',gap:8}}><Link to={`/projects/${project.id}`} className="btn btn-primary">{t('open')}</Link><button onClick={() => handleDeleteProject(project.id)} className="btn btn-danger">{t('delete')}</button></div></td>
                                </tr>
                            ))}</tbody>
                        </table></div>
                    )}
                </section>

                <section className="quick-grid">
                    <Link to="/repository" className="card quick-card"><div className="quick-icon">R</div><div><h3>{t('course_repository')}</h3><p>{t('course_repository_desc')}</p></div></Link>
                    <Link to="/projects/new" className="card quick-card"><div className="quick-icon">+</div><div><h3>{t('create_project')}</h3><p>{t('create_project_desc')}</p></div></Link>
                    <Link to="/research" className="card quick-card"><div className="quick-icon">M</div><div><h3>{t('research_dashboard')}</h3><p>{t('research_dashboard_desc')}</p></div></Link>
                </section>
            </main>
        </div>
    )
}
