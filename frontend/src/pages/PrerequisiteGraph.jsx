import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import axios from 'axios'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import LoadingSpinner from '../components/LoadingSpinner'

const neon = ['#64a8ff', '#9b8cff', '#5ac8a8', '#e4ae57', '#dc78a5', '#6fb7c9', '#8fbd63', '#b68ac9']
const stageHeight = 520
let cytoscapeLoader = null
let dagreAvailable = false

function loadCytoscape() {
    if (!cytoscapeLoader) {
        cytoscapeLoader = import('cytoscape').then(async cytoscapeModule => {
            const cytoscape = cytoscapeModule.default || cytoscapeModule
            // The optional dagre chunk can fail to load in a stale/partially
            // rebuilt frontend. Keep the graph usable with Cytoscape's
            // built-in layout instead of blanking the whole page.
            try {
                const dagreModule = await import('cytoscape-dagre')
                const dagre = dagreModule.default || dagreModule
                if (!cytoscape.__curriculumDagreRegistered) {
                    cytoscape.use(dagre)
                    cytoscape.__curriculumDagreRegistered = true
                }
                dagreAvailable = true
            } catch (_) {
                dagreAvailable = false
            }
            return cytoscape
        })
    }
    return cytoscapeLoader
}

export default function PrerequisiteGraph() {
    const { id } = useParams()
    const { t, localize, language } = useLanguage()
    const graphContainer = useRef(null)
    const cyRef = useRef(null)
    const [project, setProject] = useState(null)
    const [variants, setVariants] = useState([])
    const [variant, setVariant] = useState('A')
    const [graph, setGraph] = useState(null)
    const [competencies, setCompetencies] = useState(null)
    const [activeSemester, setActiveSemester] = useState(1)
    const [selected, setSelected] = useState(null)
    const [selectedEdge, setSelectedEdge] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [semesterInsights, setSemesterInsights] = useState({})
    const [insightLoading, setInsightLoading] = useState(null)

    useEffect(() => {
        axios.get('/api/projects/' + id).then(async response => {
            setProject(response.data)
            const versionId = response.data.latest_version?.id
            if (!versionId) throw new Error(t('graph_no_plan'))
            const variantsResponse = await axios.get('/api/planner/' + versionId + '/variants')
            setVariants(variantsResponse.data)
            const active = variantsResponse.data.find(item => item.is_active)
            setVariant(active?.variant_type || variantsResponse.data[0]?.variant_type || 'A')
        }).catch(err => { setError(err.response?.data?.detail || err.message); setLoading(false) })
    }, [id])

    useEffect(() => {
        const versionId = project?.latest_version?.id
        if (!versionId || !variant) return
        setLoading(true)
        Promise.all([
            axios.get('/api/planner/version/' + versionId + '/graph', { params: { variant } }),
            axios.get('/api/planner/version/' + versionId + '/semester-competencies', { params: { variant } })
        ]).then(([g, c]) => {
            setGraph(g.data); setCompetencies(c.data); setSelected(null); setSelectedEdge(null); setActiveSemester(1); setError(null)
        }).catch(err => setError(err.response?.data?.detail || err.message)).finally(() => setLoading(false))
    }, [project, variant])

    useEffect(() => {
        const update = () => {
            const stages = [...document.querySelectorAll('[data-semester-stage]')]
            const marker = window.innerHeight * 0.48
            let closest = stages[0], distance = Infinity
            stages.forEach(stage => {
                const value = Math.abs(stage.getBoundingClientRect().top - marker)
                if (value < distance) { distance = value; closest = stage }
            })
            if (closest) setActiveSemester(Number(closest.dataset.semesterStage))
        }
        window.addEventListener('scroll', update, { passive: true }); update()
        return () => window.removeEventListener('scroll', update)
    }, [graph])

    useEffect(() => {
        if (!graph || !graphContainer.current) return
        let cancelled = false
        cyRef.current?.destroy()
        loadCytoscape().then(cytoscape => {
            if (cancelled || !graphContainer.current) return
            const cy = cytoscape({
                container: graphContainer.current,
                elements: [
                    ...graph.nodes.map(node => ({ data: { ...node, label: node.code + '\n' + localize(node.title_translations || node.title) } })),
                    ...graph.edges.map(edge => ({ data: edge }))
                ],
                wheelSensitivity: 0.18, minZoom: 0.15, maxZoom: 2.2,
                style: [
                    { selector: 'node', style: {
                        'background-color': '#111b29', 'background-opacity': .98,
                        'border-color': element => neon[(Number(element.data('semester')) - 1) % neon.length],
                        'border-width': 2, 'label': 'data(label)', 'color': '#f5f7fa', 'text-wrap': 'wrap',
                        'text-max-width': 130, 'font-size': 9, 'font-weight': 600, 'text-valign': 'center',
                        'text-halign': 'center', 'width': 158, 'height': 62, 'shape': 'round-rectangle',
                        'shadow-blur': 14, 'shadow-color': '#000000',
                        'shadow-opacity': .24, 'shadow-offset-x': 0, 'shadow-offset-y': 6
                    }},
                    { selector: 'node[kind = "bridge"]', style: { 'shape': 'hexagon', 'border-color': '#ff40f5', 'shadow-color': '#ff40f5', 'background-color': '#240a2d' }},
                    { selector: 'edge', style: {
                        'width': 1.6, 'line-color': '#506276', 'target-arrow-color': '#7eb6ff',
                        'target-arrow-shape': 'triangle', 'arrow-scale': .85, 'curve-style': 'taxi',
                        'taxi-direction': 'rightward', 'taxi-turn': 24, 'opacity': .7
                    }},
                    { selector: 'edge[relation = "prerequisite"][origin = "plan_inferred"]', style: {
                        'line-style': 'dashed', 'line-dash-pattern': [10, 5],
                        'line-color': '#00c8ff', 'target-arrow-color': '#00e5ff',
                        'width': 2.2, 'opacity': .82
                    }},
                    { selector: 'edge[relation = "competency_flow"]', style: {
                        'line-style': 'dashed', 'line-dash-pattern': [8, 5],
                        'line-color': '#b388ff', 'target-arrow-color': '#ff80f6',
                        'curve-style': 'bezier', 'width': 2.4, 'opacity': .72
                    }},
                    { selector: 'edge[relation = "semantic_progression"]', style: {
                        'line-style': 'dotted', 'line-color': '#00e676',
                        'target-arrow-color': '#b2ff59', 'curve-style': 'bezier',
                        'width': 2, 'opacity': .58
                    }},
                    { selector: '.dimmed', style: { 'opacity': .07 } },
                    { selector: '.semesterNode', style: { 'border-width': 4, 'background-color': '#17283d', 'shadow-opacity': .5, 'z-index': 20 }},
                    { selector: '.flowPath', style: { 'opacity': 1, 'line-color': '#64a8ff', 'target-arrow-color': '#64a8ff', 'width': 3, 'z-index': 30 }},
                    { selector: 'node:selected', style: { 'border-color': '#ffffff', 'border-width': 4, 'shadow-color': '#64a8ff', 'shadow-opacity': .65 }}
                ],
                layout: dagreAvailable
                    ? { name: 'dagre', rankDir: 'LR', rankSep: 86, nodeSep: 20, edgeSep: 10, padding: 35 }
                    : { name: 'breadthfirst', directed: true, spacingFactor: 1.25, padding: 35, animate: false }
            })
            cy.on('tap', 'node', event => {
                const node = event.target
                setSelectedEdge(null)
                cy.elements().removeClass('dimmed flowPath').addClass('dimmed')
                node.predecessors().union(node.successors()).union(node).removeClass('dimmed').addClass('flowPath')
                setSelected(graph.nodes.find(item => item.id === node.id()))
            })
            cy.on('tap', 'edge', event => {
                setSelected(null)
                setSelectedEdge(graph.edges.find(item => item.id === event.target.id()) || null)
            })
            cy.on('tap', event => {
                if (event.target === cy) {
                    setSelected(null)
                    setSelectedEdge(null)
                }
            })
            cyRef.current = cy
        }).catch(err => setError(err.message || String(err)))
        return () => { cancelled = true; cyRef.current?.destroy() }
    }, [graph])

    useEffect(() => {
        const cy = cyRef.current
        if (!cy || selected) return
        cy.elements().removeClass('dimmed semesterNode flowPath').addClass('dimmed')
        const current = cy.nodes().filter(node => Number(node.data('semester')) === activeSemester)
        const context = current.union(current.predecessors()).union(current.successors())
        context.removeClass('dimmed')
        current.addClass('semesterNode')
        current.connectedEdges().addClass('flowPath')
        if (current.length) cy.animate({ fit: { eles: context, padding: 55 }, duration: 450 })
    }, [activeSemester, selected])

    const resetGraph = () => {
        setSelected(null)
        setSelectedEdge(null)
        cyRef.current?.elements().removeClass('dimmed semesterNode flowPath')
        cyRef.current?.fit(undefined, 35)
    }

    const analyzeSemester = async semester => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setInsightLoading(semester)
        try {
            const response = await axios.post(`/api/planner/version/${versionId}/semester-insight`, {
                semester, variant, language,
            })
            setSemesterInsights(current => ({ ...current, [semester]: response.data }))
        } catch (err) {
            setError(err.response?.data?.detail || err.message)
        } finally {
            setInsightLoading(null)
        }
    }

    if (loading) return <LoadingSpinner />
    const css = '.future-grid{background-color:#0a111c;background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:36px 36px}.stage-card{border:1px solid rgba(255,255,255,.09);background:rgba(15,25,38,.88);box-shadow:0 20px 55px rgba(0,0,0,.26),inset 0 1px 0 rgba(255,255,255,.035);border-radius:22px}.course-chip{border:1px solid rgba(255,255,255,.07);border-left:3px solid var(--neon);background:rgba(255,255,255,.035);padding:11px 12px;margin-bottom:8px;border-radius:12px;transition:.18s ease}.course-chip:hover{transform:translateY(-2px);background:rgba(255,255,255,.065)}.ability{padding:10px 12px;margin-bottom:8px;border:1px solid rgba(255,255,255,.075);background:rgba(255,255,255,.035);border-radius:12px;line-height:1.4}.semester-stage.active{border-color:var(--neon);box-shadow:0 18px 50px rgba(0,0,0,.32)}@media(max-width:1150px){.journey-grid{grid-template-columns:260px minmax(420px,1fr)!important}.right-rail{display:none}.graph-sticky{top:12px!important}}'

    return <div className="graph-page" style={{ minHeight: '100vh', color: '#dcefff', background: '#030912' }}>
        <style>{css}</style>
        <header style={{ position: 'sticky', top: 0, zIndex: 50, padding: '12px 0', background: 'rgba(3,9,18,.88)', backdropFilter: 'blur(16px)', borderBottom: '1px solid rgba(0,229,255,.16)' }}>
            <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
                <div><Link to={'/projects/' + id} style={{ color: '#7ddfff' }}>← {t('back')}</Link><h1 style={{ margin: '4px 0 0', fontSize: 22 }}>{t('learning_trajectory')}</h1></div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <select value={variant} onChange={event => setVariant(event.target.value)} style={selectStyle}>{variants.map(item => <option key={item.variant_type} value={item.variant_type}>{t('variant')} {item.variant_type}{item.is_active ? ' · ' + t('active') : ''}</option>)}</select>
                    <button onClick={resetGraph} style={futureButton}>{t('show_all_connections')}</button><LanguageSelector />
                </div>
            </div>
        </header>
        <main className="container" style={{ paddingTop: 18, paddingBottom: 80 }}>
            {error && <div className="stage-card" style={{ padding: 16, color: '#ff8a9a', marginBottom: 16 }}>
                <div>{error}</div>
                <button type="button" onClick={() => window.location.reload()} style={{ ...futureButton, marginTop: 10 }}>
                    {language === 'ru' ? 'Повторить загрузку графа' : language === 'kk' ? 'Графты қайта жүктеу' : 'Retry graph loading'}
                </button>
            </div>}
            {graph && competencies && <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'end', marginBottom: 18 }}>
                    <div><div style={{ color: '#64d8ff', fontSize: 11, letterSpacing: '.14em' }}>{project?.title}</div><h2 style={{ margin: '6px 0', fontSize: 28 }}>{t('scroll_through_program')}</h2><p style={{ margin: 0, color: '#89a4b9' }}>{t('scroll_graph_hint')}</p></div>
                    <div style={{ color: graph.has_cycles ? '#ff5577' : '#00e676', fontWeight: 700 }}>{graph.has_cycles ? t('graph_has_cycles') : '● ' + t('graph_no_cycles')}</div>
                </div>
                <div className="journey-grid" style={{ display: 'grid', gridTemplateColumns: '300px minmax(520px,1fr) 350px', gap: 16, alignItems: 'start' }}>
                    <div>{competencies.semesters.map(record => <CourseStage key={record.semester} record={record} graph={graph} active={activeSemester} t={t} onCourse={course => {
                        const node = cyRef.current?.getElementById(course.id)
                        if (node?.length) { node.select(); node.trigger('tap') }
                    }} localize={localize} />)}</div>
                    <div className="graph-sticky stage-card future-grid" style={{ position: 'sticky', top: 88, height: 'calc(100vh - 112px)', minHeight: 620, overflow: 'hidden' }}>
                        <div style={{ position: 'absolute', zIndex: 3, left: 18, top: 15, pointerEvents: 'none' }}><div style={{ color: neon[(activeSemester - 1) % neon.length], fontSize: 11, letterSpacing: '.16em' }}>{t('current_stage')}</div><div style={{ fontSize: 26, fontWeight: 800 }}>{activeSemester} {t('semester_short')}</div></div>
                        <div style={{ position: 'absolute', zIndex: 3, right: 16, top: 14, padding: '9px 11px', borderRadius: 10, background: 'rgba(2,10,18,.8)', fontSize: 10, lineHeight: 1.65, pointerEvents: 'none' }}>
                            <div><span style={{ color: '#00e5ff' }}>━━▶</span> {t('formal_prerequisite')} ({graph.formal_edge_count})</div>
                            <div style={{ color: '#7fcfff' }}>
                                {language === 'ru' ? 'репозиторий' : language === 'kk' ? 'репозиторий' : 'repository'}: {graph.edges.filter(edge => edge.relation === 'prerequisite' && edge.origin === 'catalogue').length}
                                {' · '}
                                {language === 'ru' ? 'выведено в плане' : language === 'kk' ? 'жоспарда шығарылды' : 'plan-inferred'}: {graph.edges.filter(edge => edge.relation === 'prerequisite' && edge.origin === 'plan_inferred').length}
                            </div>
                            <div><span style={{ color: '#d09cff' }}>┄┄▶</span> {t('competency_connection')} ({graph.competency_edge_count})</div>
                            <div><span style={{ color: '#00e676' }}>···▶</span> {t('semantic_progression')} ({graph.semantic_edge_count})</div>
                        </div>
                        <div ref={graphContainer} style={{ width: '100%', height: '100%' }} />
                        {selected && <SelectedCard selected={selected} graph={graph} t={t} id={id} onClose={() => setSelected(null)} />}
                        {selectedEdge && <EdgeCard edge={selectedEdge} graph={graph} language={language} localize={localize} onClose={() => setSelectedEdge(null)} />}
                    </div>
                    <div className="right-rail">{competencies.semesters.map(record => <ResultStage key={record.semester} record={record} active={activeSemester} t={t} language={language} insight={semesterInsights[record.semester]} loading={insightLoading === record.semester} onAnalyze={() => analyzeSemester(record.semester)} />)}</div>
                </div>
            </>}
        </main>
    </div>
}

function EdgeCard({ edge, graph, language, localize, onClose }) {
    const source = graph.nodes.find(node => node.id === edge.source)
    const target = graph.nodes.find(node => node.id === edge.target)
    const explanation = localize(edge.explanation_translations || edge.explanation)
    const relation = edge.relation === 'prerequisite'
        ? (language === 'ru' ? 'Пререквизит' : language === 'kk' ? 'Пререквизит' : 'Prerequisite')
        : edge.relation
    const origin = edge.origin === 'catalogue'
        ? (language === 'ru' ? 'Подтверждено репозиторием' : language === 'kk' ? 'Репозиториймен расталған' : 'Repository-confirmed')
        : edge.origin === 'plan_inferred'
            ? (language === 'ru' ? 'Выведено алгоритмом для этого плана' : language === 'kk' ? 'Осы жоспар үшін алгоритм шығарған' : 'Inferred for this plan')
            : ''
    return <div style={{ position: 'absolute', left: 14, right: 14, bottom: 14, zIndex: 5, padding: 14, border: '1px solid rgba(0,200,255,.42)', borderRadius: 14, background: 'rgba(2,10,18,.96)' }}>
        <button onClick={onClose} style={{ float: 'right', ...futureButton }}>×</button>
        <div style={{ color: '#00e5ff', fontSize: 11 }}>{relation}{origin ? ` · ${origin}` : ''}</div>
        <strong>{localize(source?.title_translations || source?.title)} → {localize(target?.title_translations || target?.title)}</strong>
        {explanation && <div style={{ marginTop: 8, color: '#b8cddd', fontSize: 11 }}>{explanation}</div>}
        {edge.shared_los?.length > 0 && <div style={{ marginTop: 7, color: '#d5b7ff', fontSize: 11 }}>LO: {edge.shared_los.join(', ')}</div>}
    </div>
}

function SelectedCard({ selected, graph, t, id, onClose }) {
    const [feedbackState, setFeedbackState] = useState({})
    const incoming = graph.edges.filter(edge => edge.target === selected.id)
    const outgoing = graph.edges.filter(edge => edge.source === selected.id)
    const deep = [...incoming, ...outgoing].filter(edge => edge.relation !== 'prerequisite')
    const why = selected.why_selected || {}
    return <div style={{ position: 'absolute', left: 14, right: 14, bottom: 14, zIndex: 4, padding: 14, border: '1px solid rgba(0,229,255,.35)', borderRadius: 14, background: 'rgba(2,10,18,.94)', maxHeight: 330, overflow: 'auto' }}>
        <button onClick={onClose} style={{ float: 'right', ...futureButton }}>×</button>
        <div style={{ color: '#00e5ff', fontSize: 11 }}>{selected.code} · {selected.credits} {t('credits')} · {why.role || selected.kind}</div>
        <strong>{selected.title}</strong>
        <div style={{ marginTop: 7, color: '#c8d6e5', fontSize: 11 }}>{selected.selection_reason}</div>
        <div style={{ marginTop: 8, padding: 8, borderRadius: 10, background: 'rgba(255,255,255,.04)', color: '#9cb7ca', fontSize: 11 }}>
            <div>{why.semester_reason}</div>
            <div>{why.domain_reason}</div>
            {why.epvo_reason && <div>{why.epvo_reason}</div>}
            {why.expert_reason && <div>{why.expert_reason}</div>}
            {why.prerequisites?.length > 0 && <div>{t('prerequisites')}: {why.prerequisites.slice(0, 4).join('; ')}</div>}
            {why.postrequisites?.length > 0 && <div>{t('postrequisites')}: {why.postrequisites.slice(0, 4).join('; ')}</div>}
        </div>
        {selected.lo_evidence?.length > 0 && <div style={{ marginTop: 8 }}>
            {selected.lo_evidence.slice(0, 6).map(item => (
                <div key={item.lo_code} title={item.lo_text || item.lo_code} style={{ marginBottom: 7, padding: 8, borderRadius: 10, background: 'rgba(100,168,255,.09)' }}>
                    <div style={{ color: '#9ec5ff', fontSize: 10 }}>{item.lo_code} · {Math.round(item.score * 100)}% · {item.source === 'epvo_expert' ? 'ЕПВО эксперт' : item.source === 'bridge_target' ? t('bridge_label') : t('ai_prediction')}{item.expert_feedback ? ` · expert: ${item.expert_feedback.verdict}` : ''}</div>
                    {item.lo_text && <div style={{ fontSize: 10, color: '#dbeafe', marginTop: 4 }}>{item.lo_text}</div>}
                    {item.evidence?.reasoning?.length > 0 && <div style={{ fontSize: 10, color: '#b8c7d8', marginTop: 4 }}>{item.evidence.reasoning.join('; ')}</div>}
                    {item.evidence?.epvo_expert_score > 0 && <div style={{ fontSize: 10, color: '#b7f7c8', marginTop: 4 }}>ЕПВО эксперт: {Math.round(item.evidence.epvo_expert_score * 100)}%</div>}
                    {item.chunk?.text && <div style={{ fontSize: 10, color: '#8aa3b8', marginTop: 4 }}>Evidence: {item.chunk.text}</div>}
                    {item.lo_id && <div style={{ display: 'flex', gap: 5, marginTop: 6 }}>
                        {['confirmed', 'weak', 'incorrect'].map(verdict => <button key={verdict} disabled={Boolean(feedbackState[item.lo_id])} style={{ ...futureButton, padding: '3px 7px', fontSize: 9 }} onClick={async () => { await axios.post('/api/kag/match-feedback', { project_version_id: graph.project_version_id, course_id: selected.entity_id, lo_id: item.lo_id, verdict }); setFeedbackState(current => ({ ...current, [item.lo_id]: verdict })) }}>{feedbackState[item.lo_id] === verdict ? '✓ ' : ''}{t(`feedback_${verdict}`)}</button>)}
                    </div>}
                </div>
            ))}
        </div>}
        <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11, color: '#9cb7ca' }}>
            <span>{t('incoming_connections')}: {incoming.length}</span><span>{t('outgoing_connections')}: {outgoing.length}</span>
        </div>
        {deep.length > 0 && <div style={{ marginTop: 8, color: '#d5b7ff', fontSize: 11 }}>
            {t('deep_connections')}: {deep.length}
            {[...new Set(deep.flatMap(edge => edge.shared_los || []))].length > 0 && ' · ' + t('connected_through_lo') + ': ' + [...new Set(deep.flatMap(edge => edge.shared_los || []))].join(', ')}
        </div>}
        <div style={{ marginTop: 8 }}><Link style={{ color: '#ff80f6' }} to={'/projects/' + id + '/syllabus/' + selected.kind + '/' + selected.entity_id}>{t('create_thematic_plan')} →</Link></div>
    </div>
}

function CourseStage({ record, graph, active, t, onCourse, localize }) {
    const color = neon[(record.semester - 1) % neon.length]
    const courses = (graph.nodes || []).filter(node => Number(node.semester) === record.semester)
    return <section data-semester-stage={record.semester} className={'semester-stage stage-card ' + (active === record.semester ? 'active' : '')} style={{ '--neon': color, minHeight: stageHeight, padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 14 }}><div><span style={{ color, fontSize: 12 }}>{t('stage')} {String(record.semester).padStart(2, '0')}</span><h3 style={{ margin: '3px 0 0' }}>{record.semester} {t('semester_short')}</h3></div><div style={{ color, fontSize: 22, fontWeight: 800 }}>{record.credits}</div></div>
        {courses.map(course => <div className="course-chip" style={{ '--neon': color, cursor: 'pointer' }} key={course.id} onClick={() => onCourse(course)}><div style={{ color: '#67dfff', fontSize: 10 }}>{course.code} · {course.credits} {t('credits')}</div><div style={{ fontSize: 13, marginTop: 3 }}>{localize(course.title_translations || course.title)}</div></div>)}
    </section>
}

function ResultStage({ record, active, t, language, insight, loading, onAnalyze }) {
    const color = neon[(record.semester - 1) % neon.length]
    return <section className={'semester-stage stage-card ' + (active === record.semester ? 'active' : '')} style={{ '--neon': color, minHeight: stageHeight, padding: 16, marginBottom: 16 }}>
        <div style={{ color, fontSize: 11 }}>{t('result_of_stage')}</div><h3 style={{ margin: '5px 0 12px' }}>{t('student_can_now')}</h3>
        {(record.new_course_outcomes || []).slice(0, 7).map((outcome, index) => <div className="ability" key={index}>{outcome}</div>)}
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,.08)' }}><div style={{ fontSize: 11, color: '#89a4b9' }}>{t('confirmed_program_los')}</div><div style={{ color, fontWeight: 700 }}>{record.cumulative_program_los.join(' · ') || '—'}</div></div>
        <div style={{ marginTop: 12 }}><div style={{ fontSize: 11, color: '#89a4b9' }}>{t('next_unlocked_courses')}</div><div style={{ fontSize: 12, lineHeight: 1.45 }}>{(record.next_unlocked_courses || []).slice(0, 5).map(item => localize(item.title_translations || item.title)).join('; ') || t('none')}</div></div>
        <button onClick={onAnalyze} disabled={loading} style={{ ...futureButton, marginTop: 14, width: '100%' }}>
            {loading ? (language === 'ru' ? 'ИИ анализирует…' : language === 'kk' ? 'ЖИ талдап жатыр…' : 'AI is analysing…') : (language === 'ru' ? '✨ Объяснить итог семестра через ИИ' : language === 'kk' ? '✨ Семестр нәтижесін ЖИ арқылы түсіндіру' : '✨ Explain semester outcome with AI')}
        </button>
        {insight && <div style={{ marginTop: 10, padding: 11, borderRadius: 12, background: 'rgba(100,168,255,.10)', border: '1px solid rgba(100,168,255,.22)', fontSize: 11, lineHeight: 1.5 }}>
            <strong style={{ color }}>{insight.summary}</strong>
            {(insight.skills || []).map((skill, index) => <div key={index} style={{ marginTop: 6 }}>✓ {skill}</div>)}
            <div style={{ marginTop: 7, color: '#7895aa' }}>{insight.source === 'ai' ? (language === 'ru' ? 'Сформировано ИИ по дисциплинам и РО' : 'AI + course/LO evidence') : (language === 'ru' ? 'Локальное объяснение по подтверждённым РО' : 'Local evidence-based explanation')}</div>
        </div>}
    </section>
}

const futureButton = { color: '#bdefff', background: 'rgba(0,229,255,.08)', border: '1px solid rgba(0,229,255,.35)', borderRadius: 9, padding: '8px 12px', cursor: 'pointer' }
const selectStyle = { ...futureButton, background: '#071525' }
