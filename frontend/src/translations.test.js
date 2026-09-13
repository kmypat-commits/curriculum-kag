import { describe, expect, it } from 'vitest'
import { translations } from './translations'
import generatedKk from './translations_kk_generated.json'


describe('translation catalog contract', () => {
    it('keeps every Russian UI key available in English and effective Kazakh catalog', () => {
        const ruKeys = Object.keys(translations.ru || {})
        const missingEn = ruKeys.filter(key => !translations.en?.[key])
        const missingKk = ruKeys.filter(key => !translations.kk?.[key] && !generatedKk?.[key])

        expect(missingEn, `missing English keys: ${missingEn.join(', ')}`).toEqual([])
        expect(missingKk, `missing Kazakh keys: ${missingKk.join(', ')}`).toEqual([])
    })

    it('does not contain empty catalog values', () => {
        for (const [language, catalog] of Object.entries(translations)) {
            const empty = Object.entries(catalog || {})
                .filter(([, value]) => typeof value !== 'string' || !value.trim())
                .map(([key]) => `${language}.${key}`)
            expect(empty, `empty values: ${empty.join(', ')}`).toEqual([])
        }
    })

    it('keeps doctorate track labels available in all supported languages', () => {
        for (const language of ['ru', 'kk', 'en']) {
            expect(translations[language].doctorate_track).toBeTruthy()
            expect(translations[language].doctorate_scientific).toBeTruthy()
            expect(translations[language].doctorate_professional).toBeTruthy()
        }
    })
})
