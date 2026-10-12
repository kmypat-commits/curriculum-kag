import { expect, it } from 'vitest'
import { buildLabLayout } from './buildLabLayout'
import { buildEventGraph } from './buildEventGraph'

const events = [
    { type: 'candidates', data: { variant: 'A', count: 3,
        learning_outcomes: [{ code: 'ON1', text: 'Design' }, { code: 'ON2', text: 'Build' }],
        nodes: [{ course_id: 1, title: 'Structures', lo_codes: ['ON1'] },
            { course_id: 2, title: 'Materials', lo_codes: ['ON2'], prerequisites: [1] },
            { course_id: 3, title: 'Alternative', lo_codes: ['ON1'] }] } },
    { type: 'selected', data: { variant: 'A', course_ids: [1, 2],
        schedule: { 1: [{ course_id: 1, title: 'Structures', credits: 5 }],
            2: [{ course_id: 2, title: 'Materials', credits: 5 }] } } },
]

it('places the real goal below outcomes, candidates and actual semester destinations', () => {
    const layout = buildLabLayout(buildEventGraph(events, 'Programme'))
    const at = id => layout.nodes.find(n => n.id === id)
    expect(at('profile').y).toBeGreaterThan(at('lo-ON1').y)
    expect(at('lo-ON1').y).toBeGreaterThan(at('course-1').y)
    expect(at('course-1').y).toBeGreaterThan(at('semester-1').y)
    expect(layout.nodes).toHaveLength(8)
    expect(layout.clusters.map(c => c.count)).toEqual([2, 1])
    expect(layout.paths.every(p => at(p.source) && at(p.target))).toBe(true)
    expect(at('profile').revealStep).toBe(0)
    expect(at('lo-ON1').revealStep).toBe(1)
    expect(at('course-1').revealStep).toBe(2)
    expect(at('semester-1').revealStep).toBe(3)
})

it('highlights only recorded selected relationships, never an unselected alternative', () => {
    const { paths } = buildLabLayout(buildEventGraph(events, 'Programme'))
    expect(paths.find(p => p.source === 'lo-ON1' && p.target === 'course-1').selected).toBe(true)
    expect(paths.find(p => p.target === 'course-3').selected).toBe(false)
    expect(paths.find(p => p.source === 'profile' && p.target === 'lo-ON1').selected).toBe(true)
    expect(paths.find(p => p.kind === 'prerequisite').selected).toBe(true)
})

it('keeps the empty network truthful and caps animated trails on a dense real graph', () => {
    const empty = buildLabLayout(buildEventGraph([], 'Programme'))
    expect(empty.nodes).toHaveLength(1)
    expect(empty.paths).toEqual([])
    expect(empty.clusters).toEqual([])
    const graph = buildEventGraph([{ type: 'candidates', data: { count: 300,
        nodes: Array.from({ length: 300 }, (_, i) => ({ course_id: i + 1, title: `C${i}` })) } }], 'Programme')
    const layout = buildLabLayout(graph)
    expect(layout.nodes.length).toBeLessThanOrEqual(150)
    expect(layout.paths.filter(p => p.flow)).toHaveLength(24)
    expect(buildLabLayout(graph)).toEqual(layout)
})

it('limits permanent course labels without hiding inspectable course nodes', () => {
    const nodes = Array.from({ length: 60 }, (_, i) => ({ data: {
        id: `course-${i}`, courseId: i, label: `Course ${i}`, state: 'selected',
    } }))
    const layout = buildLabLayout(nodes)
    expect(layout.nodes).toHaveLength(60)
    expect(layout.nodes.filter(n => n.showLabel)).toHaveLength(3)
})
