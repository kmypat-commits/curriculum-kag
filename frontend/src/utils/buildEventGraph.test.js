import { describe, it, expect } from 'vitest'
import { buildEventGraph } from './buildEventGraph'

describe('real build event graph', () => {
    it('caps nodes and aggregates omitted real candidates', () => {
        const graph = buildEventGraph([{ sequence: 1, type: 'candidates', data: {
            count: 1000, nodes: Array.from({ length: 200 }, (_, i) => ({ course_id: i + 1, title: `Course ${i + 1}` })),
            learning_outcomes: [{ code: 'ON1', text: 'Outcome' }],
        } }], 'Programme')
        expect(graph.filter(x => !x.data.source).length).toBeLessThanOrEqual(150)
        expect(graph.some(x => x.data.omittedCount > 0)).toBe(true)
    })
    it('a verified selection is not marked published until the complete event', () => {
        const events = [{ sequence: 1, type: 'selected', data: {
            course_ids: [8], schedule: { 1: [{ course_id: 8, title: 'Real course' }] }, verified: true,
        } }]
        let graph = buildEventGraph(events, 'Programme')
        expect(graph.find(x => x.data.id === 'course-8').data.state).toBe('selected')
        graph = buildEventGraph([...events, { sequence: 2, type: 'stage', data: { state: 'complete' } }], 'Programme')
        expect(graph.find(x => x.data.id === 'course-8').data.state).toBe('published')
    })
    it('a rejected alternative remains uncommitted after partial publication', () => {
        const events = [
            {type: 'candidates', data: {variant: 'C', count: 1, nodes: [{course_id: 8}]}},
            {type: 'selected', data: {variant: 'C', course_ids: [8], schedule: {1: [{course_id: 8}]}}},
            {type: 'stage', data: {state: 'complete', published_variants: ['A'], publication_status: 'partial'}},
        ]
        expect(buildEventGraph(events, 'Programme').find(x => x.data.id === 'course-8').data.state).toBe('selected')
    })
})
