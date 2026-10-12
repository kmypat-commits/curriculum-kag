export function buildLabLayout(elements) {
    const raw = elements.filter(e => !e.data.source).map(e => e.data)
    const edges = elements.filter(e => e.data.source).map(e => e.data)
    const outcomes = raw.filter(n => n.state === 'outcome')
    const courses = raw.filter(n => n.courseId != null)
    const semesters = raw.filter(n => n.state === 'semester')
    const selectedIds = new Set(raw.filter(n => ['selected', 'published'].includes(n.state)).map(n => n.id))
    const covered = new Set(edges.filter(e => e.kind === 'evidence' && selectedIds.has(e.target)).map(e => e.source))
    const groupCount = Math.min(6, Math.max(1, outcomes.length || Math.ceil(courses.length / 24)))
    const groups = Array.from({ length: groupCount }, () => [])
    courses.forEach((n, index) => {
        const lo = edges.find(e => e.kind === 'evidence' && e.target === n.id)?.source
        const loIndex = outcomes.findIndex(o => o.id === lo)
        groups[loIndex >= 0 ? loIndex % groupCount : index % groupCount].push(n)
    })
    const positions = new Map([['profile', { x: 500, y: 548 }]])
    outcomes.forEach((n, i) => positions.set(n.id, {
        x: 65 + (i + .5) * 870 / outcomes.length,
        y: 405 + Math.sin(i * 1.7) * 22,
    }))
    semesters.forEach((n, i) => positions.set(n.id, { x: 65 + (i + .5) * 870 / semesters.length, y: 36 }))
    const clusters = []
    groups.forEach((group, i) => {
        if (!group.length) return
        const x = 65 + (i + .5) * 870 / groupCount
        const rx = Math.min(125, 410 / groupCount)
        group.forEach((n, j) => {
            const angle = j * 2.399963229728653
            const radius = Math.sqrt((j + .5) / group.length)
            positions.set(n.id, { x: x + Math.cos(angle) * rx * .88 * radius, y: 208 + Math.sin(angle) * 76 * radius })
        })
        clusters.push({ x, y: 208, rx, ry: 88, count: group.length,
            label: outcomes.filter((_, j) => j % groupCount === i).map(o => o.label).join(' / '),
            selectedCount: group.filter(n => selectedIds.has(n.id)).length })
    })
    raw.filter(n => n.state === 'aggregate').forEach(n => positions.set(n.id, { x: 920, y: 330 }))
    const labelled = new Set(groups.map(group => group.find(n => selectedIds.has(n.id))?.id).filter(Boolean))
    const nodes = raw.map(n => ({ ...n, ...(positions.get(n.id) || { x: 500, y: 330 }),
        revealStep: n.state === 'profile' ? 0 : n.state === 'outcome' ? 1 : n.state === 'semester' ? 3 : 2,
        showLabel: labelled.has(n.id), selected: selectedIds.has(n.id) || covered.has(n.id) }))
    const byId = new Map(nodes.map(n => [n.id, n]))
    let flows = 0
    const paths = edges.filter(e => byId.has(e.source) && byId.has(e.target)).map(e => {
        const a = byId.get(e.source), b = byId.get(e.target)
        const selected = e.kind === 'profile' ? covered.has(e.target)
            : selectedIds.has(e.target) && (e.kind !== 'prerequisite' || selectedIds.has(e.source))
                || e.kind === 'placement' && selectedIds.has(e.source)
        const middle = (a.y + b.y) / 2
        const d = e.kind === 'prerequisite'
            ? `M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${Math.min(a.y, b.y) - 45} ${b.x} ${b.y}`
            : `M ${a.x} ${a.y} C ${a.x} ${middle}, ${b.x} ${middle}, ${b.x} ${b.y}`
        return { ...e, d, selected, flow: e.kind !== 'aggregate' && flows++ < 24 }
    })
    return { nodes, paths, clusters }
}
