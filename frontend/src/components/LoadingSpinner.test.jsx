import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LanguageProvider } from '../contexts/LanguageContext'
import LoadingSpinner from './LoadingSpinner'

describe('contextual loading status', () => {
    it('explains a saved-plan read without a blocking full-page overlay', () => {
        render(<LanguageProvider><LoadingSpinner fullPage={false}
            message="Загружаем сохранённый план"
            detail="Повторное построение не запускается." /></LanguageProvider>)
        const status = screen.getByRole('status')
        expect(status).toHaveAccessibleName('Загружаем сохранённый план')
        expect(screen.getByText('Повторное построение не запускается.')).toBeVisible()
        expect(status).not.toHaveClass('full-page')
    })
})
