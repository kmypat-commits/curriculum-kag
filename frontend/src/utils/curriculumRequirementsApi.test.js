import { describe, expect, it, vi } from 'vitest'

import { saveCurriculumRequirements } from './curriculumRequirementsApi'

describe('curriculum requirement persistence', () => {
    it('preserves unrelated constraints and never sends client confirmations', async () => {
        const patch = vi.fn().mockResolvedValue({ data: { constraints: {
            total_credits: 240, curriculum_requirements: { enabled: true, required_course_ids: [17] },
        } } })
        const result = await saveCurriculumRequirements(patch, 15, {
            total_credits: 240, excluded_course_ids: [8],
            curriculum_confirmations: [{ actor_user_id: 999 }],
        }, { enabled: true, required_course_ids: [17], core_blocks: [] })
        expect(patch).toHaveBeenCalledWith('/api/projects/15/constraints', {
            constraints: {
                total_credits: 240, excluded_course_ids: [8],
                curriculum_requirements: { enabled: true, required_course_ids: [17], core_blocks: [] },
            },
        })
        expect(result.curriculum_requirements.required_course_ids).toEqual([17])
    })
})
