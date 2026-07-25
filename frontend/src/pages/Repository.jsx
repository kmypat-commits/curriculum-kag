import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'

export default function Repository() {
    const { user, logout } = useAuth()
    const { t, localize, language } = useLanguage()
    const localText = (ru, kk, en) => language === 'kk' ? kk : language === 'en' ? en : ru
    const navigate = useNavigate()
    const [courses, setCourses] = useState([])
    const [repositoryStats, setRepositoryStats] = useState({ total_courses: 0, domains: [] })
    const [loading, setLoading] = useState(true)
    const [coursesLoading, setCoursesLoading] = useState(false)
    const [filter, setFilter] = useState({ direction_code: '', group_code: '', search: '' })
    const [directions, setDirections] = useState([])
    const [groups, setGroups] = useState([])
    const [showImport, setShowImport] = useState(false)
    const [importFile, setImportFile] = useState(null)
    const [showGenerate, setShowGenerate] = useState(false)
    const [generateDomain, setGenerateDomain] = useState('')
    const [generateCount, setGenerateCount] = useState(10)
    const [generating, setGenerating] = useState(false)
    const [generateResult, setGenerateResult] = useState(null)
    const [showAdd, setShowAdd] = useState(false)
    const [addForm, setAddForm] = useState({ course_id: '', title: '', domain: '', credits: 4, cycle_component: 'elective', recommended_semester: 1, description: '' })
    const [addSaving, setAddSaving] = useState(false)

    useEffect(() => {
        if (!user) {
            navigate('/login')
            return
        }
        fetchCourses()
        fetchRepositoryStats()
    }, [user, navigate])

    useEffect(() => {
        axios.get('/api/epvo/directions', { params: { language } })
            .then(response => setDirections(response.data))
            .catch(() => setDirections([]))
    }, [language])

    useEffect(() => {
        if (!filter.direction_code) { setGroups([]); return }
        axios.get('/api/epvo/groups', { params: { direction_code: filter.direction_code, language } })
            .then(response => setGroups(response.data))
            .catch(() => setGroups([]))
    }, [filter.direction_code, language])

    useEffect(() => {
        if (!user) return
        const timer = window.setTimeout(() => fetchCourses(), 250)
        return () => window.clearTimeout(timer)
    }, [filter.direction_code, filter.group_code, filter.search, user])

    const fetchCourses = async () => {
        try {
            setCoursesLoading(true)
            const response = await axios.get('/api/repository/courses', {
                params: {
                    direction_code: filter.direction_code || undefined,
                    group_code: filter.group_code || undefined,
                    search: filter.search || undefined,
                    limit: 200
                }
            })
            setCourses(response.data)
        } catch (error) {
            console.error('Error fetching courses:', error)
        } finally {
            setCoursesLoading(false)
            setLoading(false)
        }
    }

    const fetchRepositoryStats = async () => {
        try {
            const response = await axios.get('/api/repository/stats')
            setRepositoryStats(response.data)
        } catch (error) {
            console.error('Error fetching repository stats:', error)
        }
    }

    const handleImport = async (e) => {
        e.preventDefault()
        if (!importFile) return

        const formData = new FormData()
        formData.append('file', importFile)

        try {
            await axios.post('/api/repository/courses/import', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            })
            alert('Import successful!')
            setShowImport(false)
            setImportFile(null)
            fetchCourses()
        } catch (error) {
            alert('Import error: ' + (error.response?.data?.detail || error.message))
        }
    }

    const handleGenerateCourses = async (e) => {
        e.preventDefault()
        if (!generateDomain.trim()) return
        setGenerating(true)
        setGenerateResult(null)
        try {
            const res = await axios.post('/api/repository/generate-courses', {
                domain: generateDomain.trim(),
                count: generateCount
            })
            setGenerateResult({ success: true, count: res.data.generated })
            fetchCourses()
        } catch (err) {
            setGenerateResult({ success: false, error: err.response?.data?.detail || err.message })
        } finally {
            setGenerating(false)
        }
    }

    const handleAddCourse = async (e) => {
        e.preventDefault()
        setAddSaving(true)
        try {
            await axios.post('/api/repository/courses', {
                ...addForm,
                credits: parseInt(addForm.credits),
                recommended_semester: parseInt(addForm.recommended_semester)
            })
            setShowAdd(false)
            setAddForm({ course_id: '', title: '', domain: '', credits: 4, cycle_component: 'elective', recommended_semester: 1, description: '' })
            fetchCourses()
        } catch (err) {
            alert('Error: ' + (err.response?.data?.detail || err.message))
        } finally {
            setAddSaving(false)
        }
    }

    const [showAutoReq, setShowAutoReq] = useState(false)
    const [autoReqDomain, setAutoReqDomain] = useState('')
    const [autoReqLoading, setAutoReqLoading] = useState(false)
    const [autoReqResult, setAutoReqResult] = useState(null)
    const [scopeIndexing, setScopeIndexing] = useState(false)
    const [scopeIndexResult, setScopeIndexResult] = useState(null)

    const handleReindexScope = async () => {
        if (!filter.direction_code && !filter.group_code) return
        setScopeIndexing(true)
        setScopeIndexResult(null)
        try {
            const response = await axios.post('/api/repository/reindex-epvo-scope', {
                direction_code: filter.direction_code || null,
                group_code: filter.group_code || null,
            })
            setScopeIndexResult(response.data)
            fetchCourses()
            fetchRepositoryStats()
        } catch (error) {
            setScopeIndexResult({ error: error.response?.data?.detail || error.message })
        } finally {
            setScopeIndexing(false)
        }
    }

    const handleAutoAssignRequisites = async () => {
        setAutoReqLoading(true)
        setAutoReqResult(null)
        try {
            const res = await axios.post('/api/repository/auto-assign-requisites', {
                domain: autoReqDomain,
                direction_code: filter.direction_code || null,
                group_code: filter.group_code || null,
            })
            setAutoReqResult({ success: true, data: res.data })
            fetchCourses()
        } catch (err) {
            setAutoReqResult({ success: false, error: err.response?.data?.detail || err.message })
        } finally {
            setAutoReqLoading(false)
        }
    }

    const [editingCourse, setEditingCourse] = useState(null)
    const [prereqSearch, setPrereqSearch] = useState('')

    const openEditCourse = async (course) => {
        try {
            const response = await axios.get(`/api/repository/courses/${course.id}`)
            setEditingCourse(response.data)
        } catch (error) {
            console.error('Error loading course details:', error)
            setEditingCourse(course)
        }
    }

    const handleDeleteCourse = async (courseId) => {
        if (!window.confirm('Are you sure you want to delete this course?')) return
        try {
            await axios.delete(`/api/repository/courses/${courseId}`)
            setCourses(courses.filter(c => c.id !== courseId))
            alert('Course deleted')
        } catch (error) {
            alert('Error deleting')
        }
    }

    const handleSaveEdit = async (e) => {
        e.preventDefault()
        try {
            const data = {
                title: editingCourse.title,
                domain: editingCourse.domain,
                credits: editingCourse.credits,
                prerequisite_exempt: Boolean(editingCourse.prerequisite_exempt),
                prerequisites: editingCourse.prerequisites?.map(p => p.id) || []
            }
            await axios.put(`/api/repository/courses/${editingCourse.id}`, data)
            alert('Changes saved')
            setEditingCourse(null)
            fetchCourses()
        } catch (error) {
            alert('Error saving')
        }
    }

    const togglePrereq = (targetCourse) => {
        const current = editingCourse.prerequisites || []
        const exists = current.find(p => p.id === targetCourse.id)
        if (exists) {
            setEditingCourse({
                ...editingCourse,
                prerequisites: current.filter(p => p.id !== targetCourse.id)
            })
        } else {
            setEditingCourse({
                ...editingCourse,
                prerequisites: [...current, targetCourse]
            })
        }
    }

    const filteredCourses = courses
    const domains = (repositoryStats.domains || []).map(item => item.domain).filter(Boolean)

    if (loading) {
        return <LoadingSpinner />
    }

    return (
        <div style={{ minHeight: '100vh', background: '#f5f7fa' }}>
            {/* Header omitted for brevity in chunk but assumed present */}
            <header style={{ background: 'white', borderBottom: '1px solid #e0e0e0', padding: '15px 0' }}>
                <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h1 style={{ margin: 0, fontSize: '24px', color: '#366092' }}>{t('repository')}</h1>
                    <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                        <LanguageSelector />
                        <Link to="/" style={{ textDecoration: 'none', color: '#366092' }}>{t('dashboard')}</Link>
                        <Link to="/versions" style={{ textDecoration: 'none', color: '#366092' }}>Версии</Link>
                        <span>{user?.full_name || user?.email}</span>
                        <button onClick={() => { logout(); navigate('/login'); }} className="btn btn-secondary">{t('logout')}</button>
                    </div>
                </div>
            </header>

            <div className="container" style={{ paddingTop: '30px' }}>
                <div className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                        <h2 style={{ margin: 0 }}>Courses ({filteredCourses.length}/{repositoryStats.total_courses || filteredCourses.length}) {coursesLoading && <small style={{ color: '#667' }}>loading…</small>}</h2>
                        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                            <button
                                onClick={() => { setShowGenerate(!showGenerate); setGenerateResult(null) }}
                                className="btn btn-primary"
                                style={{ background: '#6c3483', borderColor: '#6c3483' }}
                            >
                                🤖 Generate with AI
                            </button>
                            <button onClick={() => setShowAdd(true)} className="btn btn-primary" style={{ background: '#1a7a4a', borderColor: '#1a7a4a' }}>➕ Add Course</button>
                            <button onClick={() => { setShowAutoReq(true); setAutoReqResult(null) }} className="btn btn-primary" style={{ background: '#b7600a', borderColor: '#b7600a' }}>🔗 Auto Pre/Post-Req (AI)</button>
                            <button onClick={() => setShowImport(true)} className="btn btn-primary">📥 Import</button>
                        </div>
                    </div>

                    {/* AI Generate Panel */}
                    {showGenerate && (
                        <div style={{ background: 'linear-gradient(135deg, #f3e8ff, #ede0ff)', border: '1px solid #c39bd3', borderRadius: '12px', padding: '20px', marginBottom: '20px' }}>
                            <h3 style={{ margin: '0 0 15px', color: '#6c3483', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                🤖 Generate Courses with AI
                            </h3>
                            <form onSubmit={handleGenerateCourses}>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '12px', alignItems: 'flex-end' }}>
                                    <div className="form-group" style={{ margin: 0 }}>
                                        <label className="form-label" style={{ color: '#6c3483', fontWeight: 'bold' }}>Domain / Subject Area</label>
                                        <input
                                            type="text"
                                            className="form-control"
                                            placeholder='e.g. Information Security, Data Science, Medicine'
                                            value={generateDomain}
                                            onChange={e => setGenerateDomain(e.target.value)}
                                            required
                                            style={{ borderColor: '#c39bd3' }}
                                        />
                                    </div>
                                    <div className="form-group" style={{ margin: 0, minWidth: '120px' }}>
                                        <label className="form-label" style={{ color: '#6c3483', fontWeight: 'bold' }}>
                                            Number of courses: <strong>{generateCount}</strong>
                                        </label>
                                        <input
                                            type="range"
                                            min={1}
                                            max={50}
                                            value={generateCount}
                                            onChange={e => setGenerateCount(parseInt(e.target.value))}
                                            style={{ width: '100%', accentColor: '#6c3483' }}
                                        />
                                    </div>
                                    <button
                                        type="submit"
                                        disabled={generating || !generateDomain.trim()}
                                        style={{
                                            padding: '10px 20px',
                                            background: generating ? '#aaa' : '#6c3483',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: '8px',
                                            cursor: generating ? 'not-allowed' : 'pointer',
                                            fontWeight: 'bold',
                                            whiteSpace: 'nowrap',
                                            fontSize: '14px'
                                        }}
                                    >
                                        {generating ? '⏳ Generating...' : '✨ Generate'}
                                    </button>
                                </div>
                            </form>
                            {generateResult && (
                                <div style={{
                                    marginTop: '12px',
                                    padding: '10px 16px',
                                    borderRadius: '8px',
                                    background: generateResult.success ? '#d4edda' : '#f8d7da',
                                    color: generateResult.success ? '#155724' : '#721c24',
                                    fontWeight: 'bold'
                                }}>
                                    {generateResult.success
                                        ? `✅ Successfully generated ${generateResult.count} courses! Table has been refreshed.`
                                        : `❌ Error: ${generateResult.error}`}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Filters */}
                    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '15px', marginBottom: '20px' }}>
                        <div className="form-group">
                            <label className="form-label">{t('search')}</label>
                            <input type="text" className="form-control" placeholder={t('search') + "..."} value={filter.search} onChange={(e) => setFilter({ ...filter, search: e.target.value })} />
                        </div>
                        <div style={{ flex: 1 }}>
                            <label className="form-label">{t('direction_code')}</label>
                            <select className="form-select" value={filter.direction_code} onChange={(e) => setFilter({ ...filter, direction_code: e.target.value, group_code: '' })}>
                                <option value="">{t('select_direction')}</option>
                                {directions.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}
                            </select>
                        </div>
                        <div style={{ flex: 1 }}>
                            <label className="form-label">{t('group_code')}</label>
                            <select className="form-select" value={filter.group_code} disabled={!filter.direction_code} onChange={(e) => setFilter({ ...filter, group_code: e.target.value })}>
                                <option value="">{t('select_group')}</option>
                                {groups.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}
                            </select>
                        </div>
                    </div>
                    {(filter.direction_code || filter.group_code) && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', margin: '-6px 0 18px', color: '#40556b', fontSize: '13px' }}>
                            <span>Если в выбранном направлении нет дисциплин, добавьте нормализованные записи ЕПВО в утверждённый репозиторий.</span>
                            <button type="button" className="btn btn-secondary" disabled={scopeIndexing} onClick={handleReindexScope}>
                                {scopeIndexing ? 'Индексация ЕПВО…' : 'Индексировать ЕПВО'}
                            </button>
                            {scopeIndexResult && <span style={{ color: scopeIndexResult.error ? '#a33' : '#26734d' }}>
                                {scopeIndexResult.error || `Готово: добавлено ${scopeIndexResult.created}, связано ${scopeIndexResult.linked}`}
                            </span>}
                        </div>
                    )}

                    <table className="table">
                        <thead>
                            <tr>
                                <th>{t('course_code')}</th>
                                <th>{t('course_title')}</th>
                                <th>{t('course_domain')}</th>
                                <th>{t('credits')}</th>
                                <th>{t('cycle_component')}</th>
                                <th>{t('prerequisites')}</th>
                                <th>{t('postrequisites')}</th>
                                <th>{t('actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredCourses.map(course => (
                                <tr key={course.id}>
                                    <td><code>{course.course_id}</code></td>
                                    <td><strong>{localize(course.title_translations || course.title)}</strong>{course.translation_status === 'machine_reviewed' && <small style={{display:'block',color:'#9a5b00'}}>{t('ai_translation')}</small>}</td>
                                    <td>{course.domain}</td>
                                    <td>{course.credits}</td>
                                    <td>{t(course.cycle_component) || course.cycle_component}</td>
                                    <td style={{ fontSize: '11px', color: '#666', maxWidth: '120px' }}>
                                        {course.prerequisites?.map(p => p.course_id).join(', ') || '-'}
                                    </td>
                                    <td style={{ fontSize: '11px', color: '#366092', maxWidth: '120px' }}>
                                        {course.postrequisites?.map(p => p.course_id).join(', ') || '-'}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '5px' }}>
                                            <button onClick={() => openEditCourse(course)} className="btn btn-primary" style={{ padding: '4px 8px', fontSize: '12px' }}>{t('edit')}</button>
                                            <button onClick={() => handleDeleteCourse(course.id)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '12px', background: '#f8d7da', color: '#721c24' }}>{t('delete')}</button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Edit Modal */}
            {editingCourse && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div className="card" style={{ maxWidth: '600px', width: '100%', maxHeight: '90vh', overflowY: 'auto' }}>
                        <h3>{t('editing')}: {editingCourse.course_id}</h3>
                        <form onSubmit={handleSaveEdit}>
                            <div className="form-group">
                                <label className="form-label">{t('title')}</label>
                                <input type="text" className="form-control" value={editingCourse.title} onChange={e => setEditingCourse({ ...editingCourse, title: e.target.value })} />
                            </div>
                            <div className="form-group" style={{ marginTop: '12px' }}>
                                <label className="form-label">{localText('\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b \u2014 \u0440\u0443\u0441\u0441\u043a\u0438\u0439', '\u041f\u04d9\u043d \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430\u0441\u044b \u2014 \u043e\u0440\u044b\u0441\u0448\u0430', 'Course description \u2014 Russian')}</label>
                                <div style={{ whiteSpace: 'pre-wrap', background: '#f7f9fc', border: '1px solid #e1e7ef', padding: '10px', borderRadius: '7px', minHeight: '42px' }}>
                                    {editingCourse.description_translations?.ru || editingCourse.description || localText('\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043f\u043e\u043a\u0430 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442', '\u0421\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430 \u04d9\u0437\u0456\u0440\u0433\u0435 \u0436\u043e\u049b', 'Description is not available yet')}
                                </div>
                                <label className="form-label" style={{ marginTop: '9px' }}>{localText('\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b \u2014 \u043a\u0430\u0437\u0430\u0445\u0441\u043a\u0438\u0439', '\u041f\u04d9\u043d \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430\u0441\u044b \u2014 \u049b\u0430\u0437\u0430\u049b\u0448\u0430', 'Course description \u2014 Kazakh')}</label>
                                <div style={{ whiteSpace: 'pre-wrap', background: '#f7f9fc', border: '1px solid #e1e7ef', padding: '10px', borderRadius: '7px', minHeight: '42px' }}>
                                    {editingCourse.description_translations?.kk || localText('\u041a\u0430\u0437\u0430\u0445\u0441\u043a\u043e\u0435 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043f\u043e\u043a\u0430 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442', '\u049a\u0430\u0437\u0430\u049b\u0448\u0430 \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430 \u04d9\u0437\u0456\u0440\u0433\u0435 \u0436\u043e\u049b', 'Kazakh description is not available yet')}
                                </div>
                                <label className="form-label" style={{ marginTop: '9px' }}>{localText('\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b \u2014 \u0430\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439', '\u041f\u04d9\u043d \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430\u0441\u044b \u2014 \u0430\u0493\u044b\u043b\u0448\u044b\u043d\u0448\u0430', 'Course description \u2014 English')}</label>
                                <div style={{ whiteSpace: 'pre-wrap', background: '#f7f9fc', border: '1px solid #e1e7ef', padding: '10px', borderRadius: '7px', minHeight: '42px' }}>
                                    {editingCourse.description_translations?.en || localText('\u0410\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u043e\u0435 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043f\u043e\u043a\u0430 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442', '\u0410\u0493\u044b\u043b\u0448\u044b\u043d\u0448\u0430 \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430 \u04d9\u0437\u0456\u0440\u0433\u0435 \u0436\u043e\u049b', 'English description is not available yet')}
                                </div>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                                <div className="form-group">
                                    <label className="form-label">{t('domain')}</label>
                                    <input type="text" className="form-control" value={editingCourse.domain} onChange={e => setEditingCourse({ ...editingCourse, domain: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('credits')}</label>
                                    <input type="number" className="form-control" value={editingCourse.credits} onChange={e => setEditingCourse({ ...editingCourse, credits: parseInt(e.target.value) })} />
                                </div>
                            </div>
                            <div style={{ flex: 2 }}>
                                <label className="form-label">{t('cycle_component')}</label>
                                <select className="form-select" value={editingCourse.cycle_component} onChange={(e) => setEditingCourse({ ...editingCourse, cycle_component: e.target.value })}>
                                    <option value="обязательный компонент">{t('mandatory')}</option>
                                    <option value="вузовский компонент">{t('university')}</option>
                                    <option value="компонент по выбору">{t('elective')}</option>
                                </select>
                            </div>

                            <div className="form-group" style={{ marginTop: '15px' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', cursor: 'pointer' }}>
                                    <input
                                        type="checkbox"
                                        checked={Boolean(editingCourse.prerequisite_exempt)}
                                        onChange={e => setEditingCourse({
                                            ...editingCourse,
                                            prerequisite_exempt: e.target.checked,
                                            prerequisites: e.target.checked ? [] : editingCourse.prerequisites,
                                        })}
                                    />
                                    Для этой базовой дисциплины пререквизиты не требуются
                                </label>
                                <label className="form-label">{t('prerequisites')} ({t('selected')}: {editingCourse.prerequisites?.length || 0})</label>
                                <div style={{ marginBottom: '10px', fontSize: '13px', color: '#366092' }}>
                                    {editingCourse.prerequisites?.map(p => (
                                        <span key={p.id} style={{ background: '#eef2f7', padding: '2px 8px', borderRadius: '4px', marginRight: '5px', display: 'inline-block', marginBottom: '4px' }}>
                                            {p.course_id} <span style={{ cursor: 'pointer', color: 'red' }} onClick={() => togglePrereq(p)}>×</span>
                                        </span>
                                    ))}
                                </div>

                                <label className="form-label" style={{ color: '#666', fontSize: '12px' }}>{t('dependent_courses')}:</label>
                                <div style={{ marginBottom: '10px', fontSize: '13px', color: '#2c7a7b' }}>
                                    {editingCourse.postrequisites?.length > 0 ?
                                        editingCourse.postrequisites.map(p => (
                                            <span key={p.id} style={{ background: '#e6fffa', padding: '2px 8px', borderRadius: '4px', marginRight: '5px', display: 'inline-block', marginBottom: '4px' }}>
                                                {p.course_id}
                                            </span>
                                        )) : t('no_dependent_courses')
                                    }
                                </div>

                                <input
                                    type="text"
                                    className="form-control"
                                    placeholder={t('prerequisite_search_placeholder')}
                                    value={prereqSearch}
                                    onChange={e => setPrereqSearch(e.target.value)}
                                />
                                {prereqSearch && (
                                    <div style={{ border: '1px solid #ddd', borderRadius: '4px', marginTop: '5px', maxHeight: '150px', overflowY: 'auto', background: 'white' }}>
                                        {courses
                                            .filter(c => c.id !== editingCourse.id && (c.title.toLowerCase().includes(prereqSearch.toLowerCase()) || c.course_id.toLowerCase().includes(prereqSearch.toLowerCase())))
                                            .slice(0, 5)
                                            .map(c => (
                                                <div key={c.id} onClick={() => { togglePrereq(c); setPrereqSearch(''); }} style={{ padding: '8px', cursor: 'pointer', borderBottom: '1px solid #eee' }}>
                                                    {c.course_id} - {localize(c.title_translations || c.title)}
                                                </div>
                                            ))
                                        }
                                    </div>
                                )}
                            </div>

                            <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary">{t('save')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setEditingCourse(null)}>{t('cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Import Modal */}
            {showImport && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div className="card" style={{ maxWidth: '500px', width: '100%', margin: '20px' }}>
                        <h2>{t('import_courses')}</h2>
                        <form onSubmit={handleImport}>
                            <div className="form-group">
                                <label className="form-label">{t('file')} (XLSX, CSV, JSON)</label>
                                <input type="file" className="form-control" accept=".xlsx,.csv,.json" onChange={(e) => setImportFile(e.target.files[0])} required />
                            </div>
                            <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary">{t('import')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => { setShowImport(false); setImportFile(null); }}>{t('cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Add Course Modal */}
            {showAdd && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div className="card" style={{ maxWidth: '560px', width: '100%', margin: '20px', maxHeight: '90vh', overflowY: 'auto' }}>
                        <h2 style={{ marginBottom: '20px', color: '#1a7a4a' }}>＋ {t('add_course_manually')}</h2>
                        <form onSubmit={handleAddCourse}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                <div className="form-group">
                                    <label className="form-label">{t('course_code')} *</label>
                                    <input type="text" className="form-control" placeholder="e.g. CS301" value={addForm.course_id}
                                        onChange={e => setAddForm({ ...addForm, course_id: e.target.value })} required />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('domain')} *</label>
                                    <input type="text" className="form-control" placeholder="e.g. Data Science" value={addForm.domain}
                                        onChange={e => setAddForm({ ...addForm, domain: e.target.value })} required />
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('title')} *</label>
                                <input type="text" className="form-control" placeholder="e.g. Machine Learning Fundamentals" value={addForm.title}
                                    onChange={e => setAddForm({ ...addForm, title: e.target.value })} required />
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                                <div className="form-group">
                                    <label className="form-label">{t('credits')}</label>
                                    <input type="number" className="form-control" min={1} max={10} value={addForm.credits}
                                        onChange={e => setAddForm({ ...addForm, credits: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('semester')}</label>
                                    <input type="number" className="form-control" min={1} max={8} value={addForm.recommended_semester}
                                        onChange={e => setAddForm({ ...addForm, recommended_semester: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('cycle_component')}</label>
                                    <select className="form-select" value={addForm.cycle_component}
                                        onChange={e => setAddForm({ ...addForm, cycle_component: e.target.value })}>
                                        <option value="mandatory">{t('mandatory')}</option>
                                        <option value="elective">{t('elective')}</option>
                                        <option value="university">{t('university')}</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('description')}</label>
                                <textarea className="form-control" rows={3} placeholder={t('short_course_description')} value={addForm.description}
                                    onChange={e => setAddForm({ ...addForm, description: e.target.value })} style={{ resize: 'vertical' }} />
                            </div>
                            <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                                <button type="submit" disabled={addSaving} className="btn btn-primary"
                                    style={{ background: '#1a7a4a', borderColor: '#1a7a4a' }}>
                                    {addSaving ? t('saving') : t('add_course')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowAdd(false)}>{t('cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Auto Pre/Post-Req Modal */}
            {showAutoReq && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
                    <div className="card" style={{ maxWidth: '520px', width: '100%', margin: '20px' }}>
                        <h2 style={{ marginBottom: '8px', color: '#b7600a' }}>{t('auto_assign_requisites')}</h2>
                        <p style={{ color: '#666', fontSize: '14px', marginBottom: '20px' }}>
                            {t('auto_assign_requisites_description')}
                        </p>
                        <div className="form-group" style={{ marginBottom: '20px' }}>
                            <label className="form-label" style={{ fontWeight: 'bold' }}>{t('domain')}</label>
                            <select className="form-select" value={autoReqDomain} onChange={e => setAutoReqDomain(e.target.value)}>
                                <option value="">{t('all_domains')}</option>
                                {domains.map(d => <option key={d} value={d}>{d}</option>)}
                            </select>
                            <div style={{ fontSize: '12px', color: '#888', marginTop: '4px' }}>
                                {autoReqDomain
                                    ? t('will_process_courses').replace('{count}', courses.filter(c => c.domain === autoReqDomain).length)
                                    : t('will_process_courses').replace('{count}', courses.length)}
                            </div>
                        </div>
                        {autoReqResult && (
                            <div style={{
                                padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
                                background: autoReqResult.success ? '#d4edda' : '#f8d7da',
                                color: autoReqResult.success ? '#155724' : '#721c24',
                                fontWeight: 'bold'
                            }}>
                                {autoReqResult.success
                                    ? t('requisites_updated').replace('{updated}', autoReqResult.data.updated).replace('{total}', autoReqResult.data.total_courses)
                                    : `${t('error')}: ${autoReqResult.error}`}
                            </div>
                        )}
                        <div style={{ display: 'flex', gap: '10px' }}>
                            <button
                                onClick={handleAutoAssignRequisites}
                                disabled={autoReqLoading}
                                className="btn btn-primary"
                                style={{ background: autoReqLoading ? '#aaa' : '#b7600a', borderColor: '#b7600a', fontWeight: 'bold' }}
                            >
                                {autoReqLoading ? t('analyzing') : t('apply')}
                            </button>
                            <button className="btn btn-secondary" onClick={() => setShowAutoReq(false)}>{t('close')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
