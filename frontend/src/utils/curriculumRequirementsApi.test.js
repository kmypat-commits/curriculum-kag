import { describe, expect, it, vi } from 'vitest'

import { saveCurriculumRequirements, loadCoreEvidencePreview, confirmCoreMatch } from './curriculumRequirementsApi'

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

describe('core evidence API', () => {
    it('loads evidence for the current project version without changing state', async () => {
        const get = vi.fn().mockResolvedValue({ data: { expected_course_hash: 'a'.repeat(64) } })
        const data = await loadCoreEvidencePreview(get, 15, 8, 'wood', 17)
        expect(get).toHaveBeenCalledWith('/api/projects/15/curriculum-confirmations/preview', {
            params: { project_version_id: 8, block_id: 'wood', course_id: 17 },
        })
        expect(data.expected_course_hash).toBe('a'.repeat(64))
    })

    it('submits only reviewed evidence with server-bound version', async () => {
        const post = vi.fn().mockResolvedValue({ data: { confirmation: { status: 'confirmed' } } })
        const reviewed = { block_id: 'wood', course_id: 17, source_field: 'description',
            source_excerpt: 'обработка древесины', rationale: 'Проверено',
            expected_course_hash: 'a'.repeat(64), expected_block_hash: 'b'.repeat(64) }
        const record = await confirmCoreMatch(post, 15, 8, reviewed)
        expect(post).toHaveBeenCalledWith('/api/projects/15/curriculum-confirmations', {
            project_version_id: 8, ...reviewed,
        })
        expect(record.status).toBe('confirmed')
    })
})
