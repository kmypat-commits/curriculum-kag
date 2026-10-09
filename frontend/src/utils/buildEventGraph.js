export function buildEventGraph(events, title, aggregateLabel = '…') {
    const latestCandidates = [...events].reverse().find(e => e.type === 'candidates')
    const variant = latestCandidates?.data?.variant
    const selection = [...events].reverse().find(e => e.type === 'selected' && (!variant || e.data.variant === variant))
    const lastStage = [...events].reverse().find(e => e.type === 'stage')
    const publication = lastStage?.data
    const published = publication?.state === 'complete' &&
        (Array.isArray(publication.published_variants)
            ? publication.published_variants.includes(selection?.data?.variant)
            : publication.publication_status !== 'partial')
    const candidateData = latestCandidates?.data || {}
    const los = (candidateData.learning_outcomes || []).slice(0, 12)
    const schedule = selection?.data?.schedule || {}
    const semesters = Object.keys(schedule).slice(0, 16)
    const selectedIds = new Set(selection?.data?.course_ids || [])
    const selectedNodes = Object.values(schedule).flat().filter(c => c.course_id != null)
    const byId = new Map((candidateData.nodes || []).map(c => [c.course_id, c]))
    for (const c of selectedNodes) byId.set(c.course_id, { ...byId.get(c.course_id), ...c })
    const ordered = [...byId.values()].sort((a, b) => Number(selectedIds.has(b.course_id)) - Number(selectedIds.has(a.course_id)))
    const budget = 150 - 1 - los.length - semesters.length - 1
    const visible = ordered.slice(0, budget)
    const candidateIds = new Set((candidateData.nodes || []).map(c => c.course_id))
    const visibleCandidates = visible.filter(c => candidateIds.has(c.course_id)).length
    const omitted = Math.max(0, (candidateData.count || 0) - visibleCandidates)
    const nodes = [{ data: { id: 'profile', label: title, state: 'profile' } },
        ...los.map(lo => ({ data: { id: `lo-${lo.code}`, label: lo.code, detail: lo.text, state: 'outcome' } })),
        ...semesters.map(sem => ({ data: { id: `semester-${sem}`, label: sem, state: 'semester' } })),
        ...visible.map(c => ({ data: { id: `course-${c.course_id}`, courseId: c.course_id,
            label: c.title || `ID ${c.course_id}`, state: selectedIds.has(c.course_id) ? (published ? 'published' : 'selected') : 'candidate' } }))]
    if (omitted) nodes.push({ data: { id: 'aggregate', label: `${aggregateLabel} ${omitted}`, omittedCount: omitted, state: 'aggregate' } })
    const ids = new Set(nodes.map(n => n.data.id))
    const edges = []
    const connect = (source, target, kind) => {
        if (ids.has(source) && ids.has(target)) edges.push({ data: { id: `${kind}-${source}-${target}`, source, target, kind } })
    }
    los.forEach(lo => connect('profile', `lo-${lo.code}`, 'profile'))
    for (const c of visible) {
        const linked = (c.lo_codes || []).filter(code => ids.has(`lo-${code}`))
        if (!linked.length) connect('profile', `course-${c.course_id}`, 'candidate')
        linked.forEach(code => connect(`lo-${code}`, `course-${c.course_id}`, 'evidence'))
        ;(c.prerequisites || []).forEach(id => connect(`course-${id}`, `course-${c.course_id}`, 'prerequisite'))
    }
    for (const sem of semesters) (schedule[sem] || []).forEach(c => connect(`course-${c.course_id}`, `semester-${sem}`, 'placement'))
    if (omitted) connect('profile', 'aggregate', 'aggregate')
    return [...nodes, ...edges]
}
