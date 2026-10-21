import { render, screen, fireEvent, act } from '@testing-library/react'
import { vi, it, expect } from 'vitest'
import axios from 'axios'
import ContentEvaluationPanel from './ContentEvaluationPanel'

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

it('blocks requests against the previous plan during publication and refresh', async () => {
    axios.get.mockReset().mockImplementation(() => new Promise(() => {}))
    const view = render(<ContentEvaluationPanel versionId={3} planId={9} unavailable t={x => x} />)
    const button = screen.getByRole('button', {name: 'content_evaluation_open'})
    expect(button).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('content_evaluation_wait_for_plan')
    fireEvent.click(button)
    expect(axios.get).not.toHaveBeenCalled()
    view.rerender(<ContentEvaluationPanel versionId={3} planId={10} unavailable={false} t={x => x} />)
    fireEvent.click(screen.getByRole('button', {name: 'content_evaluation_open'}))
    expect(axios.get).toHaveBeenLastCalledWith('/api/planner/3/content-evaluation',
        expect.objectContaining({params: {plan_id: 10}}))
})

it('discards an old plan response after navigation to another plan', async () => {
    let completeOld
    axios.get.mockImplementationOnce(() => new Promise(resolve => { completeOld = resolve }))
    const view = render(<ContentEvaluationPanel versionId={3} planId={9} t={x => x} />)
    fireEvent.click(screen.getByRole('button', {name: 'content_evaluation_open'}))
    view.rerender(<ContentEvaluationPanel versionId={4} planId={10} t={x => x} />)
    await act(async () => { completeOld({data: {report: {indicators: {}, core_coverage: [], courses: [], duplicate_groups: [], sequence_findings: [], evaluator_version: 'OLD'}}}) })
    axios.get.mockImplementationOnce(() => new Promise(() => {}))
    fireEvent.click(screen.getByRole('button', {name: 'content_evaluation_open'}))
    expect(screen.queryByText('OLD')).not.toBeInTheDocument()
    expect(axios.get).toHaveBeenLastCalledWith('/api/planner/4/content-evaluation', expect.objectContaining({params: {plan_id: 10}}))
})

it('shows evidence diagnostics needed for substantive review', async () => {
    axios.get.mockReset().mockResolvedValue({data: {report: {
        indicators: {reviewed_courses: 1},
        core_coverage: [],
        courses: [],
        duplicate_groups: [{course_ids: [11, 12], reason: 'similar_content_embedding', similarity: 0.9471, embedding_model: 'model-v1'}],
        sequence_findings: [],
        embedding_findings: [{course_id: 11, reason: 'non_semantic_embedding', model: 'feature-hash-v1'}],
        evaluator_version: 'v1'
    }}})
    render(<ContentEvaluationPanel versionId={3} planId={9} t={x => x} />)
    fireEvent.click(screen.getByRole('button', {name: 'content_evaluation_open'}))
    await screen.findAllByText((_, node) => node?.textContent?.includes('similar_content_embedding'))
    expect(screen.getByText(/0\.9471/)).toBeInTheDocument()
    expect(screen.getByText(/model-v1/)).toBeInTheDocument()
    expect(screen.getByText(/non_semantic_embedding/)).toBeInTheDocument()
    expect(screen.getByText(/feature-hash-v1/)).toBeInTheDocument()
})
