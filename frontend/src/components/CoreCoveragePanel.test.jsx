import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import CoreCoveragePanel from './CoreCoveragePanel'
import PlanQualityPanel from './PlanQualityPanel'

describe('methodist core coverage', () => {
    it('shows confirmed coverage separately from an unconfirmed preferred gap', () => {
        render(<CoreCoveragePanel coverage={{
            enabled: true,
            passed: true,
            unique_core_credits: 5,
            required_courses: { requested: [17], included: [17], missing: [] },
            core_coverage: [
                { block_id: 'wood', title: 'Обработка древесины', requirement: 'required', status: 'covered', selected_course_ids: [17], unconfirmed_course_ids: [], supported_credits: 5 },
                { block_id: 'design', title: 'Проектирование мебели', requirement: 'preferred', status: 'unconfirmed', selected_course_ids: [], unconfirmed_course_ids: [42], supported_credits: 0 },
            ],
        }} />)

        expect(screen.getByText(/Подтверждённые профильные кредиты: 5/)).toBeInTheDocument()
        expect(screen.getByText(/Обработка древесины.*покрыт/)).toBeInTheDocument()
        expect(screen.getByText(/Проектирование мебели.*не подтверждён/)).toBeInTheDocument()
        expect(screen.getByText(/ID 42/)).toBeInTheDocument()
        expect(screen.getByText(/Не является предметной экспертизой/)).toBeInTheDocument()
    })

    it('does not invent coverage for a legacy plan without a snapshot', () => {
        const { container } = render(<CoreCoveragePanel coverage={undefined} />)
        expect(container).toBeEmptyDOMElement()
    })

    it('reads the frozen coverage from the selected plan metrics', () => {
        render(<PlanQualityPanel currentPlan={{ metrics: {
            core_coverage: {
                enabled: true, unique_core_credits: 5,
                required_courses: { requested: [], included: [], missing: [] },
                core_coverage: [{ block_id: 'wood', title: 'Обработка древесины', requirement: 'preferred', status: 'covered', supported_credits: 5 }],
            },
        } }} />)
        expect(screen.getByRole('region', { name: 'Покрытие профильного ядра' })).toHaveTextContent('Обработка древесины')
    })
})
