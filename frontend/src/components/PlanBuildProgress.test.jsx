import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import PlanBuildProgress from './PlanBuildProgress'


describe('PlanBuildProgress', () => {
    it('keeps a cancellation explanation visible without a live progress bar', () => {
        render(<PlanBuildProgress active={false} progress={5}
            status={{state:'cancelled', stage:'cancelled'}} title="Построение плана"
            stageLabel={() => 'Отменено'} stageDetail="Новый результат не опубликован."
            longRunningHint="Подождите завершения" />)
        expect(screen.getByRole('status')).toHaveTextContent('Отменено')
        expect(screen.getByText('Новый результат не опубликован.')).toBeInTheDocument()
        expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
        expect(screen.queryByText('Подождите завершения')).not.toBeInTheDocument()
    })
    it('renders live progress and bounds an invalid value', () => {
        render(
            <PlanBuildProgress
                active
                progress={150}
                status={{ stage: 'scoring' }}
                title="Generating plan"
                stageLabel={() => 'Scoring course–LO links'}
                stageDetail="LO 2/9"
                elapsedLabel="Elapsed: 10 sec"
                longRunningHint="The old plan is safe."
            />,
        )

        expect(screen.getByText('Generating plan')).toBeInTheDocument()
        expect(screen.getByText('Scoring course–LO links')).toBeInTheDocument()
        expect(screen.getAllByText('LO 2/9')).toHaveLength(2)
        expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    })

    it('does not occupy space outside an active build', () => {
        const { container } = render(
            <PlanBuildProgress active={false} progress={0} status={{}} stageLabel={() => ''} />,
        )
        expect(container).toBeEmptyDOMElement()
    })

    it('shows the current stage detail instead of a misleading frozen percentage', () => {
        render(
            <PlanBuildProgress
                active
                progress={5}
                status={{ stage: 'matching', lo_index: 8, lo_total: 17, lo_code: 'LO8', candidate_count: 157 }}
                title="Построение плана"
                stageLabel={() => 'Сопоставление'}
                stageDetail="LO 8/17 — LO8, кандидатов: 157"
                longRunningHint="Подождите"
            />,
        )

        expect(screen.getAllByText('LO 8/17 — LO8, кандидатов: 157')).toHaveLength(2)
        expect(screen.queryByText('5%')).not.toBeInTheDocument()
    })
})
