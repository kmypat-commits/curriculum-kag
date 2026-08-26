import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import PlanBuildProgress from './PlanBuildProgress'


describe('PlanBuildProgress', () => {
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
        expect(screen.getByText('LO 2/9')).toBeInTheDocument()
        expect(screen.getByText('100%')).toBeInTheDocument()
    })

    it('does not occupy space outside an active build', () => {
        const { container } = render(
            <PlanBuildProgress active={false} progress={0} status={{}} stageLabel={() => ''} />,
        )
        expect(container).toBeEmptyDOMElement()
    })
})
