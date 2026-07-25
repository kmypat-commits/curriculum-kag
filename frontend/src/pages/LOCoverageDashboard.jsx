import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage as useI18n } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'

export default function LOCoverageDashboard() {
    const { id } = useParams()
    const { t, language } = useI18n()
    const [project, setProject] = useState(null)
    const [coverage, setCoverage] = useState(null)
    const [planVariants, setPlanVariants] = useState([])
    const [selectedVariant, setSelectedVariant] = useState('A')
    const [loSources, setLoSources] = useState(null)
    const [loading, setLoading] = useState(true)
    const [coverageLoading, setCoverageLoading] = useState(false)
    const [error, setError] = useState(null)
    const [loWeights, setLoWeights] = useState({})
    const [saving, setSaving] = useState(false)
    const [saveSuccess, setSaveSuccess] = useState(false)

    // Knowledge Graph
    const [graphStats, setGraphStats] = useState(null)
    const [buildingGraph, setBuildingGraph] = useState(false)
    const [graphError, setGraphError] = useState(null)
    const [systemStatus, setSystemStatus] = useState(null)
    const [reindexing, setReindexing] = useState(false)

    // Feature 2 — Bridge Modules
    const [bridgeModules, setBridgeModules] = useState(null)
    const [generatingBridge, setGeneratingBridge] = useState(false)
    const [bridgeError, setBridgeError] = useState(null)
    const [promotingBridge, setPromotingBridge] = useState({})
    const [workflowNotice, setWorkflowNotice] = useState(null)

    // Feature 3 — LO Achievability
    const [achievability, setAchievability] = useState(null)
    const [analyzingAchievability, setAnalyzingAchievability] = useState(false)
    const [achievabilityError, setAchievabilityError] = useState(null)

    useEffect(() => {
        fetchData()
        fetchGraphStats()
    }, [id])

    const fetchData = async () => {
        try {
            setLoading(true)
            const projRes = await axios.get(`/api/projects/${id}`)
            setProject(projRes.data)

            const weights = {}
            projRes.data.latest_version?.learning_outcomes?.forEach(lo => {
                weights[lo.id] = lo.weight || 1.0
            })
            setLoWeights(weights)

            if (projRes.data.latest_version?.id) {
                const variantsRes = await axios.get(`/api/planner/${projRes.data.latest_version.id}/variants`)
                const available = variantsRes.data || []
                const preferred = available.find(item => item.is_active)?.variant_type || available[0]?.variant_type || 'A'
                setPlanVariants(available)
                setSelectedVariant(preferred)
                await fetchCoverage(projRes.data.latest_version.id, preferred)
            }
        } catch (err) {
            console.error('Error fetching project:', err)
            setError('Error loading project data')
        } finally {
            setLoading(false)
        }
    }

    const fetchCoverage = async (versionId, variant = selectedVariant) => {
        try {
            setCoverageLoading(true)
            const [covRes, sourceRes] = await Promise.all([
                axios.get(`/api/kag/${versionId}/coverage`, { params: { variant } }),
                axios.get(`/api/planner/${versionId}/lo-coverage-sources`, { params: { variant } }),
            ])
            setCoverage(covRes.data)
            setLoSources(sourceRes.data)
        } catch (err) {
            console.error('Error fetching coverage:', err)
            setError(err.response?.data?.detail || 'Error loading analytics')
        } finally {
            setCoverageLoading(false)
        }
    }

    const handleWeightChange = (loId, newWeight) => {
        setLoWeights(prev => ({ ...prev, [loId]: newWeight }))
        setSaveSuccess(false)
    }

    const handleSaveWeights = async () => {
        try {
            setSaving(true)
            const updates = Object.entries(loWeights).map(([id, weight]) => ({
                lo_id: parseInt(id),
                weight: weight
            }))
            await axios.post('/api/projects/lo/weights', updates)
            setSaveSuccess(true)
            setTimeout(() => setSaveSuccess(false), 5000)
        } catch (err) {
            alert('Error saving weights')
        } finally {
            setSaving(false)
        }
    }

    const fetchGraphStats = async () => {
        try {
            const res = await axios.get('/api/kag/graph/stats')
            setGraphStats(res.data)
        } catch (err) {
            // Graph not built yet — silently ignore
        }
    }

    const fetchSystemStatus = async () => {
        try {
            const res = await axios.get('/api/kag/system/status')
            setSystemStatus(res.data)
        } catch (err) {
            console.error('Error fetching system status:', err)
        }
    }

    const handleReindex = async () => {
        setReindexing(true)
        try {
            const res = await axios.post('/api/kag/system/reindex')
            setGraphStats(res.data.graph)
            await fetchSystemStatus()
            if (project?.latest_version?.id) await fetchCoverage(project.latest_version.id)
        } catch (err) {
            setGraphError(err.response?.data?.detail || err.message)
        } finally {
            setReindexing(false)
        }
    }
    const handleBuildGraph = async () => {
        const versionId = project?.latest_version?.id
        setBuildingGraph(true)
        setGraphError(null)
        try {
            const res = await axios.post('/api/kag/graph/build', { project_version_id: versionId || null })
            setGraphStats(res.data)
            setWorkflowNotice({
                type: 'info',
                title: t('graph_rebuilt_title'),
                text: t('graph_rebuilt_text')
            })
        } catch (err) {
            setGraphError(err.response?.data?.detail || err.message)
        } finally {
            setBuildingGraph(false)
        }
    }

    const handleGenerateBridge = async (forceEnrichment = false) => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setGeneratingBridge(true)
        setBridgeError(null)
        setBridgeModules(null)
        try {
            const res = await axios.post(`/api/kag/${versionId}/generate-bridge`, { force_enrichment: forceEnrichment })
            setBridgeModules(res.data.generated_modules || [])
            setWorkflowNotice({
                type: 'warning',
                title: forceEnrichment ? 'Дополнительный модуль создан' : t('bridge_generated_title'),
                text: forceEnrichment ? 'Это необязательный модуль углубления. Добавляйте его в репозиторий только после экспертной проверки.' : t('bridge_generated_text')
            })
        } catch (err) {
            setBridgeError(err.response?.data?.detail || err.message)
        } finally {
            setGeneratingBridge(false)
        }
    }

    const handlePromoteBridge = async (mod, i) => {
        if (!mod.id) {
            alert(t('Bridge module ID not found. Please regenerate.'))
            return
        }
        setPromotingBridge(prev => ({ ...prev, [i]: 'loading' }))
        try {
            const res = await axios.post(`/api/kag/bridge/${mod.id}/promote`, {})
            setPromotingBridge(prev => ({ ...prev, [i]: 'done' }))
            setWorkflowNotice({
                type: 'success',
                title: t('kb_updated_title'),
                text: t('kb_updated_text')
            })
            // Refresh graph stats since the knowledge base grew
            fetchGraphStats()
            if (project?.latest_version?.id) fetchCoverage(project.latest_version.id)
        } catch (err) {
            setPromotingBridge(prev => ({ ...prev, [i]: 'error' }))
            alert(t('promotion_error') + ': ' + (err.response?.data?.detail || err.message))
        }
    }

    const handleAnalyzeAchievability = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setAnalyzingAchievability(true)
        setAchievabilityError(null)
        setAchievability(null)
        try {
            const res = await axios.post(`/api/kag/${versionId}/lo-achievability`, { language })
            setAchievability(res.data)
            setWorkflowNotice({
                type: 'info',
                title: t('analysis_completed_title'),
                text: t('analysis_completed_text')
            })
        } catch (err) {
            setAchievabilityError(err.response?.data?.detail || err.message)
        } finally {
            setAnalyzingAchievability(false)
        }
    }

    if (loading) return <LoadingSpinner />

    const planCoverage = coverage?.plan_coverage
    const threshold = planCoverage?.coverage_threshold || coverage?.gaps?.threshold || 0.65
    const coverageByLo = planCoverage?.coverage_by_lo
    const coveragePercent = planCoverage
        ? Math.round(planCoverage.coverage_percentage || 0)
        : (coverage?.matches?.lo_coverage
            ? Math.round(
                Object.values(coverage.matches.lo_coverage).filter(v => v.max_score >= threshold).length /
                Math.max(Object.keys(coverage.matches.lo_coverage).length, 1) * 100
            )
            : 0)
    const uncoveredLoCount = planCoverage
        ? Math.max(0, (planCoverage.total_los || 0) - (planCoverage.covered_los || 0))
        : (coverage?.gaps?.gap_count || 0)
    const enrichmentLabel = language === 'kk' ? 'Қосымша тереңдетілген модуль құру' : language === 'en' ? 'Create optional enrichment module' : 'Создать дополнительный модуль'
    const bridgeButtonLabel = uncoveredLoCount > 0 ? `✨ ${t('generate_bridge')}` : `✨ ${enrichmentLabel}`
    const bridgeHelperText = uncoveredLoCount > 0
        ? t('bridge_description')
        : language === 'kk'
            ? 'Ашық LO жоқ, сондықтан жүйе міндетті түзету емес, қосымша тереңдетілген bridge-модуль ұсынады.'
            : language === 'en'
                ? 'There are no uncovered LOs, so the system will create an optional enrichment bridge module rather than a required gap fix.'
                : 'Непокрытых LO нет, поэтому система создаст не обязательное исправление, а дополнительный bridge-модуль для усиления программы.'

    const verdictColor = {
        'Ready': { bg: '#d4edda', color: '#155724', icon: '✅' },
        'Needs Improvement': { bg: '#fff3cd', color: '#856404', icon: '⚠️' },
        'Critical Gaps': { bg: '#f8d7da', color: '#721c24', icon: '🚨' }
    }

    const statusColor = {
        'on_track': '#155724',
        'needs_courses': '#856404',
        'too_vague': '#856404',
        'critical': '#721c24'
    }

    const statusBg = {
        'on_track': '#d4edda',
        'needs_courses': '#fff3cd',
        'too_vague': '#fff3cd',
        'critical': '#f8d7da'
    }

    const changeVariant = async variant => {
        setSelectedVariant(variant)
        if (project?.latest_version?.id) await fetchCoverage(project.latest_version.id, variant)
    }

    const achievabilityNeedsCourses = achievability?.recommendations?.some(
        rec => rec.status === 'needs_courses' || rec.status === 'critical'
    )
    const achievabilityNeedsLoRevision = achievability?.recommendations?.some(
        rec => rec.status === 'too_vague'
    )

    return (
        <div className="workspace-page analysis-page" style={{ minHeight: '100vh', background: '#f5f7fa' }}>
            <header className="workspace-header" style={{ background: 'white', borderBottom: '1px solid #e0e0e0', padding: '15px 0' }}>
                <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                        <Link to={`/projects/${id}`} style={{ textDecoration: 'none', color: '#666' }}>← {t('back')}</Link>
                        <h1 style={{ margin: 0, fontSize: '24px', color: '#366092' }}>{t('check_coverage')}</h1>
                    </div>
                    <LanguageSelector />
                </div>
            </header>

            <main className="container workspace-main" style={{ paddingTop: '30px' }}>
                {workflowNotice && (
                    <div
                        className="card"
                        style={{
                            marginBottom: '24px',
                            borderLeft: `5px solid ${workflowNotice.type === 'success' ? '#2e7d32' : workflowNotice.type === 'warning' ? '#e67e22' : '#1565c0'}`,
                            background: workflowNotice.type === 'success' ? '#f0fff4' : workflowNotice.type === 'warning' ? '#fff8e1' : '#eef7ff'
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' }}>
                            <div>
                                <h3 style={{ margin: '0 0 6px', color: '#333' }}>{workflowNotice.title}</h3>
                                <p style={{ margin: 0, color: '#555', lineHeight: 1.5 }}>{workflowNotice.text}</p>
                                <div style={{ marginTop: '12px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                                    <Link
                                        to={`/projects/${id}/plan`}
                                        className="btn btn-primary"
                                        style={{ textDecoration: 'none' }}
                                    >
                                        {t('open_regenerate')}
                                    </Link>
                                    <button className="btn btn-secondary" onClick={() => setWorkflowNotice(null)}>
                                        {t('hide')}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Analytics Summary */}
                <div className="card" style={{ marginBottom: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                        <div>
                            <h2 style={{ margin: 0 }}>{language === 'ru' ? 'Какие РО нужно усилить' : language === 'kk' ? 'Қай ОН күшейту керек' : 'Which outcomes need strengthening'}</h2>
                            <div style={{ marginTop: 5, color: '#667', fontSize: 13 }}>
                                {language === 'ru' ? 'Сравнивайте A/B/C: полоса показывает силу покрытия, а ниже — реальные дисциплины и bridge-источники.' : language === 'kk' ? 'A/B/C салыстырыңыз: жолақ қамту күшін, төменде нақты пәндер мен bridge көздерін көрсетеді.' : 'Compare A/B/C: bars show coverage strength; real courses and bridge sources are listed below.'}
                            </div>
                        </div>
                        <select className="form-control" value={selectedVariant} onChange={event => changeVariant(event.target.value)} style={{ width: 210 }}>
                            {planVariants.map(item => <option key={item.variant_type} value={item.variant_type}>{t('variant')} {item.variant_type}{item.is_active ? ` · ${t('active')}` : ''}</option>)}
                        </select>
                    </div>
                    {coverageLoading && (
                        <div style={{ marginTop: 12, color: '#667', fontSize: 13 }}>
                            {language === 'ru' ? 'Обновляю покрытие и источники LO…' : language === 'kk' ? 'LO қамтуы мен көздерін жаңартып жатырмын…' : 'Refreshing LO coverage and sources…'}
                        </div>
                    )}
                    {loSources?.elapsed_seconds !== undefined && !coverageLoading && (
                        <div style={{ marginTop: 12, color: '#667', fontSize: 13 }}>
                            {language === 'ru' ? `Источники покрытия рассчитаны за ${loSources.elapsed_seconds}s.` : language === 'kk' ? `Қамту көздері ${loSources.elapsed_seconds}s ішінде есептелді.` : `Coverage sources calculated in ${loSources.elapsed_seconds}s.`}
                        </div>
                    )}
                    <div style={{ display: 'flex', gap: '40px', marginTop: '20px' }}>
                        <div>
                            <div style={{ fontSize: '36px', fontWeight: 'bold', color: '#366092' }}>
                                {coveragePercent}%
                            </div>
                            <div style={{ color: '#666' }}>{t('coverage_percent')}</div>
                            {planCoverage && (
                                <div style={{ color: '#777', fontSize: '12px', marginTop: '4px' }}>
                                    {t('plan_label')} {planCoverage.variant_type}, {t('min_lo_label')} {Math.round((planCoverage.min_lo_coverage || 0) * 100)}%
                                </div>
                            )}
                        </div>
                        <div>
                            <div style={{ fontSize: '36px', fontWeight: 'bold', color: '#e67e22' }}>
                                {uncoveredLoCount}
                            </div>
                            <div style={{ color: '#666' }}>{t('uncovered_los')}</div>
                        </div>
                    </div>
                    {loSources?.items?.length > 0 && <div style={{ marginTop: 22, padding: 16, borderRadius: 12, background: 'linear-gradient(145deg,#f7fbff,#eef4fb)', border: '1px solid #d9e6f3' }}>
                        <div style={{ display: 'grid', gap: 11 }}>
                            {loSources.items.map(row => {
                                const percent = Math.round((row.coverage || 0) * 100)
                                const color = percent >= 75 ? '#1d8f62' : percent >= 60 ? '#d69020' : '#c43b4d'
                                return <div key={row.lo_code} title={row.lo_text} style={{ display: 'grid', gridTemplateColumns: '105px 1fr 52px', gap: 10, alignItems: 'center' }}>
                                    <strong style={{ color: '#29445f' }}>{row.lo_code}</strong>
                                    <div style={{ height: 14, borderRadius: 99, overflow: 'hidden', background: '#dfe8f1' }}>
                                        <div style={{ width: `${Math.max(2, percent)}%`, height: '100%', borderRadius: 99, background: `linear-gradient(90deg,${color},${color}cc)` }} />
                                    </div>
                                    <strong style={{ color, textAlign: 'right' }}>{percent}%</strong>
                                </div>
                            })}
                        </div>
                    </div>}
                </div>

                {coverage?.matches?.prediction?.source === 'epvo_sbert_ai' && (
                    <div className="card" style={{ marginBottom: '24px', borderLeft: '5px solid #7b1fa2', background: '#f8f3ff' }}>
                        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                            <span style={{ background: '#7b1fa2', color: 'white', borderRadius: '999px', padding: '5px 10px', fontSize: '12px', whiteSpace: 'nowrap' }}>
                                {language === 'ru' ? 'Прогноз ИИ' : language === 'kz' ? 'ЖИ болжамы' : 'AI prediction'}
                            </span>
                            <div>
                                <strong>
                                    {language === 'ru' ? 'Связи дисциплин и результатов обучения предложены моделью ЕПВО' : language === 'kz' ? 'Пәндер мен оқу нәтижелерінің байланыстарын ЕПВО моделі ұсынды' : 'Course–outcome links are suggested by the EPVO model'}
                                </strong>
                                <p style={{ margin: '6px 0 0', color: '#555', lineHeight: 1.5 }}>
                                    {language === 'ru' ? 'Это рекомендация, а не решение эксперта. Перед утверждением программы подтвердите или исправьте связи.' : language === 'kz' ? 'Бұл сарапшы шешімі емес, ұсыныс. Бағдарламаны бекітпес бұрын байланыстарды растаңыз немесе түзетіңіз.' : 'This is a recommendation, not an expert decision. Confirm or correct the links before approval.'}
                                </p>
                            </div>
                        </div>
                    </div>
                )}

                <div className="card" style={{ marginBottom: '24px', borderLeft: '4px solid #366092', background: '#f8fbff' }}>
                    <h3 style={{ marginTop: 0 }}>{t('page_effect')}</h3>
                    <ol style={{ margin: '8px 0 0 20px', color: '#444', lineHeight: 1.7 }}>
                        <li>{t('graph_effect')}</li>
                        <li>{t('bridge_effect')}</li>
                        <li>{t('promote_effect')}</li>
                        <li>{t('regenerate_effect')}</li>
                    </ol>
                </div>

                {/* Knowledge Graph Section */}
                <div className="card" style={{ marginBottom: '24px', borderLeft: '4px solid #7b1fa2' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                        <h2 style={{ margin: 0, color: '#7b1fa2' }}>🧠 {t('knowledge_graph')}</h2>
                        <button
                            onClick={handleBuildGraph}
                            disabled={buildingGraph}
                            className="btn btn-primary"
                            style={{ background: '#7b1fa2', borderColor: '#7b1fa2' }}
                        >
                            {buildingGraph ? t('loading') : graphStats?.graph_built ? `🔄 ${t('rebuild_graph')}` : `⚡ ${t('build_graph')}`}
                        </button>
                    </div>
                    <p style={{ color: '#666', fontSize: '14px', margin: '0 0 14px' }}>
                        {t('graph_description')}
                    </p>
                    <div style={{ padding: 14, borderRadius: 10, background: '#f8f3ff', border: '1px solid #e3d5f4', marginBottom: 14, color: '#49365e', fontSize: 13, lineHeight: 1.55 }}>
                        <strong>{language === 'ru' ? 'Для чего это нужно простыми словами' : language === 'kk' ? 'Қарапайым тілмен не үшін керек' : 'What this does, in plain language'}</strong>
                        <div style={{ marginTop: 6 }}>
                            {language === 'ru'
                                ? 'Граф связывает дисциплины, пререквизиты и РО. После нажатия система заново пересчитает связи для поиска, объяснений и рекомендаций; существующий учебный план не изменится автоматически.'
                                : language === 'kk'
                                    ? 'Граф пәндерді, пререквизиттерді және ОН байланыстырады. Батырмадан кейін жүйе іздеу, түсіндіру және ұсыныстар үшін байланыстарды қайта есептейді; оқу жоспары автоматты түрде өзгермейді.'
                                    : 'The graph connects courses, prerequisites, and outcomes. Clicking rebuild recalculates links for search, explanations, and recommendations; it does not automatically change the curriculum.'}
                        </div>
                        <Link to={`/projects/${id}/graph`} className="btn btn-secondary" style={{ display: 'inline-block', marginTop: 10, textDecoration: 'none' }}>
                            {language === 'ru' ? `Открыть красивый граф плана ${selectedVariant}` : language === 'kk' ? `${selectedVariant} жоспарының графын ашу` : `Open visual graph for plan ${selectedVariant}`}
                        </Link>
                    </div>
                    {systemStatus && (
                        <div style={{ background: systemStatus.mixed_embedding_models ? '#fff3cd' : '#eef7ff', padding: '10px 12px', borderRadius: '6px', marginBottom: '12px', fontSize: '13px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
                            <span>
                                <strong>{t('embedding_mode')}:</strong> {systemStatus.embedding?.mode} · {systemStatus.embedding?.model_name}
                                {systemStatus.mixed_embedding_models && ` · ${t('mixed_index')}`}
                            </span>
                            <button className="btn btn-secondary" onClick={handleReindex} disabled={reindexing}>
                                {reindexing ? t('reindexing') : t('reindex_all')}
                            </button>
                        </div>
                    )}                    {graphError && (
                        <div style={{ background: '#f8d7da', color: '#721c24', padding: '10px', borderRadius: '6px', marginBottom: '10px' }}>
                            ❌ {graphError}
                        </div>
                    )}
                    {graphStats && (
                        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                            {[
                                { label: t('courses_label'), value: graphStats.total_courses, color: '#1565c0' },
                                { label: t('total_edges'), value: graphStats.total_edges, color: '#7b1fa2' },
                                { label: t('prerequisite_links'), value: graphStats.prerequisite_edges, color: '#2e7d32' },
                                { label: t('similarity_links'), value: graphStats.similarity_edges, color: '#e65100' },
                                { label: t('lo_coverage_links'), value: graphStats.lo_coverage_edges ?? graphStats.lo_edges ?? 0, color: '#00838f' },
                            ].map(stat => (
                                <div key={stat.label} style={{ textAlign: 'center' }}>
                                    <div style={{ fontSize: '28px', fontWeight: 'bold', color: stat.color }}>{stat.value ?? 0}</div>
                                    <div style={{ fontSize: '12px', color: '#666' }}>{stat.label}</div>
                                </div>
                            ))}
                            <div style={{ textAlign: 'center' }}>
                                <div style={{ fontSize: '28px', fontWeight: 'bold', color: graphStats.graph_built ? '#2e7d32' : '#999' }}>
                                    {graphStats.graph_built ? '✅' : '⬜'}
                                </div>
                                <div style={{ fontSize: '12px', color: '#666' }}>{t('graph_built')}</div>
                            </div>
                        </div>
                    )}
                    {!graphStats && !buildingGraph && (
                        <div style={{ color: '#999', fontSize: '14px' }}>
                            {t('graph_not_built')}
                        </div>
                    )}
                </div>

                {/* Feature 2 — Bridge Module Suggestions */}
                <div className="card" style={{ marginBottom: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h2 style={{ margin: 0 }}>🌉 {t('bridge_suggestions')}</h2>
                        <button
                            onClick={() => handleGenerateBridge(!(uncoveredLoCount > 0))}
                            data-bridge-generate="true"
                            disabled={generatingBridge}
                            className="btn btn-primary"
                            style={{ background: '#1a7a4a', borderColor: '#1a7a4a' }}
                        >
                            {generatingBridge ? t('generating') : bridgeButtonLabel}
                        </button>
                        <button
                            onClick={() => handleGenerateBridge(true)}
                            disabled={generatingBridge}
                            className="btn btn-secondary"
                            style={{ marginLeft: '8px' }}
                        >
                            {enrichmentLabel}
                        </button>
                    </div>
                    <p style={{ color: '#666', margin: '0 0 16px', fontSize: '14px' }}>
                        {bridgeHelperText}
                    </p>

                    {bridgeError && (
                        <div style={{ background: '#f8d7da', color: '#721c24', padding: '12px', borderRadius: '8px' }}>
                            ❌ {bridgeError}
                        </div>
                    )}

                    {bridgeModules !== null && bridgeModules.length === 0 && (
                        <div style={{ background: '#d4edda', color: '#155724', padding: '12px', borderRadius: '8px' }}>
                            ✅ {t('no_gaps')}
                        </div>
                    )}

                    {bridgeModules && bridgeModules.length > 0 && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            {bridgeModules.map((mod, i) => (
                                <div key={i} style={{ border: '1px solid #a9dfbf', background: '#f0fff4', borderRadius: '10px', padding: '16px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
                                        <div>
                                            <div style={{ fontWeight: 'bold', fontSize: '16px', color: '#1a7a4a' }}>{mod.content?.title || mod.title}</div>
                                            <div style={{ fontSize: '13px', color: '#666', marginTop: '4px' }}>{mod.course_id} · {mod.content?.credits || mod.credits} credits</div>
                                        </div>
                                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', maxWidth: '200px', justifyContent: 'flex-end' }}>
                                            {(mod.target_los || []).map(lo => (
                                                <span key={lo} style={{ background: '#c6efce', color: '#1a7a4a', padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: 'bold' }}>{lo}</span>
                                            ))}
                                        </div>
                                    </div>
                                    <p style={{ fontSize: '14px', color: '#444', margin: '0 0 12px' }}>{mod.content?.goal || 'Interdisciplinary bridge module'}</p>

                                    {mod.content?.topics && mod.content.topics.length > 0 && (
                                        <div>
                                            <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#1a7a4a', marginBottom: '6px' }}>📋 {t('topics')}:</div>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                                                {mod.content.topics.slice(0, 8).map((topic, j) => (
                                                    <span key={j} style={{ background: '#e8f5e9', color: '#2e7d32', padding: '2px 8px', borderRadius: '4px', fontSize: '12px' }}>{topic}</span>
                                                ))}
                                                {mod.content.topics.length > 8 && <span style={{ fontSize: '12px', color: '#666' }}>+{mod.content.topics.length - 8} more</span>}
                                            </div>
                                        </div>
                                    )}

                                    {mod.content?.assessment_methods && (
                                        <div style={{ marginTop: '10px', fontSize: '13px', color: '#555' }}>
                                            <strong>{t('assessment')}:</strong> {mod.content.assessment_methods.join(' | ')}
                                        </div>
                                    )}

                                    {/* Promote to Course button */}
                                    <div style={{ marginTop: '12px', borderTop: '1px solid #c8e6c9', paddingTop: '10px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                                        {promotingBridge[i] === 'done' ? (
                                            <span style={{ color: '#155724', fontWeight: 'bold', fontSize: '13px' }}>
                                                ✅ {t('promoted')}
                                            </span>
                                        ) : (
                                            <button
                                                onClick={() => handlePromoteBridge(mod, i)}
                                                disabled={promotingBridge[i] === 'loading'}
                                                style={{
                                                    padding: '6px 16px', fontSize: '13px', fontWeight: 'bold',
                                                    background: '#7b1fa2', color: 'white', border: 'none',
                                                    borderRadius: '6px', cursor: 'pointer'
                                                }}
                                            >
                                                {promotingBridge[i] === 'loading' ? t('loading') : `🚀 ${t('promote_course')}`}
                                            </button>
                                        )}
                                        <span style={{ fontSize: '12px', color: '#888' }}>
                                            {t('promote_desc')}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Feature 3 — LO Achievability Analysis */}
                <div className="card" style={{ marginBottom: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h2 style={{ margin: 0 }}>🎯 {t('lo_achievability')}</h2>
                        <button
                            onClick={handleAnalyzeAchievability}
                            disabled={analyzingAchievability}
                            className="btn btn-primary"
                            style={{ background: '#1565c0', borderColor: '#1565c0' }}
                        >
                            {analyzingAchievability ? t('analyzing') : `🤖 ${t('analyze_ai')}`}
                        </button>
                    </div>
                    <p style={{ color: '#666', margin: '0 0 16px', fontSize: '14px' }}>
                        {t('achievability_description')}
                    </p>

                    {achievabilityError && (
                        <div style={{ background: '#f8d7da', color: '#721c24', padding: '12px', borderRadius: '8px' }}>
                            ❌ {achievabilityError}
                        </div>
                    )}

                    {achievability && (
                        <div>
                            {/* Verdict badge */}
                            <div style={{
                                display: 'inline-flex', alignItems: 'center', gap: '10px',
                                padding: '12px 20px', borderRadius: '10px', marginBottom: '16px',
                                background: verdictColor[achievability.verdict]?.bg || '#eee',
                                color: verdictColor[achievability.verdict]?.color || '#333'
                            }}>
                                <span style={{ fontSize: '24px' }}>{verdictColor[achievability.verdict]?.icon}</span>
                                <div>
                                    <div style={{ fontWeight: 'bold', fontSize: '18px' }}>{t(achievability.verdict)}</div>
                                    <div style={{ fontSize: '13px' }}>{t('achievability_score')}: <strong>{achievability.score}/100</strong></div>
                                </div>
                            </div>

                            {/* Progress bar */}
                            <div style={{ background: '#eee', borderRadius: '4px', height: '8px', marginBottom: '16px' }}>
                                <div style={{
                                    height: '8px', borderRadius: '4px',
                                    background: achievability.score >= 70 ? '#28a745' : achievability.score >= 40 ? '#ffc107' : '#dc3545',
                                    width: `${achievability.score}%`,
                                    transition: 'width 0.6s ease'
                                }} />
                            </div>

                            <p style={{ color: '#444', marginBottom: '16px', fontSize: '14px', lineHeight: '1.6' }}>{achievability.summary}</p>

                            {achievability.recommendations && achievability.recommendations.length > 0 && (
                                <div>
                                    <h4 style={{ marginBottom: '12px', color: '#333' }}>{t('per_lo_recommendations')}:</h4>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                        {achievability.recommendations.map((rec, i) => (
                                            <div key={i} style={{
                                                border: `1px solid ${statusBg[rec.status]}`,
                                                background: statusBg[rec.status] || '#fff',
                                                borderRadius: '8px',
                                                padding: '12px 16px'
                                            }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                                                    <code style={{ fontWeight: 'bold', color: statusColor[rec.status] || '#333', fontSize: '14px' }}>{rec.lo_code}</code>
                                                    <span style={{
                                                        fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                                                        background: 'rgba(0,0,0,0.08)', color: statusColor[rec.status] || '#555',
                                                        textTransform: 'uppercase', fontWeight: 'bold'
                                                    }}>
                                                        {t(rec.status?.replace('_', ' '))}
                                                    </span>
                                                </div>
                                                <div style={{ fontSize: '13px', color: '#555', marginBottom: '4px' }}>⚠️ {rec.issue}</div>
                                                <div style={{ fontSize: '13px', color: '#333', fontWeight: '500' }}>💡 {rec.suggestion}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {achievability.recommendations?.length > 0 && (
                                <div style={{
                                    marginTop: '18px', padding: '16px', borderRadius: '10px',
                                    border: '1px solid #90caf9', background: '#eef7ff'
                                }}>
                                    <h4 style={{ margin: '0 0 10px', color: '#0d47a1' }}>{t('what_next')}</h4>
                                    <ol style={{ margin: '0 0 14px', paddingLeft: '22px', color: '#333', lineHeight: '1.7', fontSize: '14px' }}>
                                        {achievabilityNeedsLoRevision && (
                                            <li>{t('clarify_vague_los')}</li>
                                        )}
                                        {achievabilityNeedsCourses && (
                                            <li>{t('generate_missing_los')}</li>
                                        )}
                                        <li>{t('review_promote')}</li>
                                        <li>{t('regenerate_variants_hint')}</li>
                                    </ol>
                                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                                        {achievabilityNeedsCourses && (
                                            <button
                                                onClick={async () => {
                                                    await handleGenerateBridge()
                                                    const bridgeButton = document.querySelector('[data-bridge-generate="true"]')
                                                    bridgeButton?.closest('.card')?.scrollIntoView({ behavior: 'smooth' })
                                                }}
                                                disabled={generatingBridge || !(uncoveredLoCount > 0)}
                                                className="btn btn-primary"
                                                style={{ background: '#1a7a4a', borderColor: '#1a7a4a' }}
                                            >
                                                {generatingBridge ? t('generating') : t('generate_missing_modules')}
                                            </button>
                                        )}
                                        {achievabilityNeedsLoRevision && (
                                            <Link to={`/projects/${id}`} className="btn btn-secondary" style={{ textDecoration: 'none' }}>
                                                {t('edit_los')}
                                            </Link>
                                        )}
                                        <Link to={`/projects/${id}/plan`} className="btn btn-secondary" style={{ textDecoration: 'none' }}>
                                            {t('open_plan_builder')}
                                        </Link>
                                    </div>
                                </div>
                            )}

                            {achievability.recommendations?.length === 0 && (
                                <div style={{ background: '#d4edda', color: '#155724', padding: '12px', borderRadius: '8px' }}>
                                    ✅ {t('all_los_good')}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* LO List with Priorities */}
                <div className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                        <h2 style={{ margin: 0 }}>{t('learning_outcomes')} Analysis</h2>
                        <button
                            onClick={handleSaveWeights}
                            className="btn btn-primary"
                            disabled={saving}
                        >
                            {saving ? '...' : `💾 ${t('save_priorities')}`}
                        </button>
                    </div>

                    {saveSuccess && (
                        <div style={{ background: '#d4edda', color: '#155724', padding: '10px', borderRadius: '4px', marginBottom: '15px', fontSize: '14px' }}>
                            {t('priorities_saved')}
                        </div>
                    )}

                    <div style={{ marginTop: '20px' }}>
                        {project?.latest_version?.learning_outcomes?.map(lo => {
                            const planStats = coverageByLo?.[lo.lo_code]
                            const repoStats = coverage?.matches?.lo_coverage?.[lo.lo_code]
                            const score = planStats?.coverage ?? repoStats?.max_score ?? 0
                            const stats = { max_score: score }
                            const isCovered = score >= threshold
                            const currentWeight = loWeights[lo.id] || 1.0
                            const sourceRow = (loSources?.items || []).find(item => item.lo_code === lo.lo_code)

                            return (
                                <div key={lo.id} style={{
                                    padding: '20px',
                                    borderBottom: '1px solid #eee',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '15px'
                                }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontWeight: 'bold', color: '#366092', marginBottom: '5px' }}>{lo.lo_code}</div>
                                            <div style={{ fontSize: '15px' }}>{lo.lo_text}</div>
                                        </div>
                                        <div style={{ textAlign: 'right', minWidth: '150px' }}>
                                            <span style={{
                                                padding: '6px 15px',
                                                borderRadius: '20px',
                                                fontSize: '13px',
                                                background: isCovered ? '#d4edda' : '#f8d7da',
                                                color: isCovered ? '#155724' : '#721c24',
                                                fontWeight: 'bold'
                                            }}>
                                                {isCovered ? `${t('covered')} (${Math.round(stats.max_score * 100)}%)` : t('not_covered')}
                                            </span>
                                        </div>
                                    </div>

                                    <div style={{ display: 'grid', gap: 6, padding: '10px 12px', borderRadius: 8, background: '#f7fafc', border: '1px solid #e1e8ef', fontSize: 13 }}>
                                        {(sourceRow?.real_sources || []).length > 0 ? sourceRow.real_sources.slice(0, 5).map(source => (
                                            <div key={source.course_id} style={{ color: '#285d47' }}>✓ {source.title} · {Math.round((source.score || 0) * 100)}% AI · {Math.round((source.expert_score || 0) * 100)}% ЕПВО</div>
                                        )) : <div style={{ color: '#a33' }}>{language === 'ru' ? 'Нет подтверждённой реальной дисциплины — эту РО нужно усилить.' : language === 'kk' ? 'Расталған нақты пән жоқ — осы ОН күшейту керек.' : 'No confirmed real course — strengthen this outcome.'}</div>}
                                        {(sourceRow?.bridge_sources || []).map(source => (
                                            <div key={source.bridge_id} style={{ color: '#8a5a00' }}>◇ bridge в плане, {t('semester')} {source.semester}: {source.title}</div>
                                        ))}
                                    </div>

                                    {/* Priority Slider */}
                                    <div style={{ background: '#f8f9fa', padding: '10px 15px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '20px' }}>
                                        <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#666', minWidth: '150px' }}>
                                            Priority: {currentWeight.toFixed(1)}x
                                        </div>
                                        <input
                                            type="range"
                                            min="0.5"
                                            max="2.0"
                                            step="0.1"
                                            value={currentWeight}
                                            onChange={(e) => handleWeightChange(lo.id, parseFloat(e.target.value))}
                                            style={{ flex: 1, accentColor: '#366092' }}
                                        />
                                        <div style={{ display: 'flex', gap: '5px' }}>
                                            <button
                                                onClick={() => handleWeightChange(lo.id, Math.max(0.5, currentWeight - 0.1))}
                                                style={{ border: '1px solid #ddd', background: 'white', borderRadius: '4px', width: '30px', cursor: 'pointer' }}
                                            >-</button>
                                            <button
                                                onClick={() => handleWeightChange(lo.id, Math.min(2.0, currentWeight + 0.1))}
                                                style={{ border: '1px solid #ddd', background: 'white', borderRadius: '4px', width: '30px', cursor: 'pointer' }}
                                            >+</button>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            </main>
        </div>
    )
}


