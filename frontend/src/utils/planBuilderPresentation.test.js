import { describe, expect, it } from 'vitest'

import {
    localizeQualityEvidenceText,
    planBuildElapsedLabel,
    planBuildStageLabel,
} from './planBuilderPresentation'


describe('plan builder presentation', () => {
    it('keeps build-stage labels available in all interface languages', () => {
        expect(planBuildStageLabel('variant_B', 'ru')).toContain('вариант B')
        expect(planBuildStageLabel('variant_B', 'kk')).toContain('B')
        expect(planBuildStageLabel('variant_B', 'en')).toBe('Checking variant B')
    })

    it('localises quality evidence without changing its numeric meaning', () => {
        const text = '14/14 learning outcomes meet the coverage threshold.'
        expect(localizeQualityEvidenceText(text, 'ru')).toBe('14/14 результатов обучения достигли порога покрытия.')
        expect(localizeQualityEvidenceText(text, 'kk')).toBe('14/14 оқу нәтижесі қамту шегіне жетті.')
        expect(localizeQualityEvidenceText(text, 'en')).toBe(text)
    })

    it('formats elapsed build time for RU, KK and EN', () => {
        expect(planBuildElapsedLabel({ elapsed_seconds: 65 }, 'ru')).toBe('Прошло: 1 мин 5 сек')
        expect(planBuildElapsedLabel({ elapsed_seconds: 65 }, 'kk')).toBe('Өткен уақыт: 1 мин 5 сек')
        expect(planBuildElapsedLabel({ elapsed_seconds: 65 }, 'en')).toBe('Elapsed: 1 min 5 sec')
    })
})
