import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import CurriculumRequirements from './CurriculumRequirements'

const course = { id: 17, course_id: 'EPVO-8087', title: 'Биоинформатика', credits: 5 }

describe('optional curriculum requirements', () => {
    it('starts disabled and leaves ordinary generation unchanged until saved', async () => {
        const save = vi.fn()
        render(<CurriculumRequirements value={undefined} onSave={save} searchCourses={vi.fn()} />)
        expect(screen.getByRole('checkbox', { name: /Учитывать профильные/ })).not.toBeChecked()
        expect(screen.queryByRole('button', { name: /Сохранить требования/ })).not.toBeInTheDocument()
        expect(save).not.toHaveBeenCalled()
    })

    it('selects a real internal course id and persists only after explicit save', async () => {
        const user = userEvent.setup()
        const save = vi.fn().mockResolvedValue(undefined)
        const search = vi.fn().mockResolvedValue([course])
        render(<CurriculumRequirements value={{ enabled: false }} onSave={save} searchCourses={search} />)
        await user.click(screen.getByRole('checkbox', { name: /Учитывать профильные/ }))
        await user.type(screen.getByRole('textbox', { name: /Найти дисциплину/ }), 'Биоинформатика')
        await user.click(screen.getByRole('button', { name: /Искать в каталоге/ }))
        expect(await screen.findByText(/EPVO-8087/)).toBeInTheDocument()
        await user.click(screen.getByRole('button', { name: /Сделать обязательной/ }))
        expect(save).not.toHaveBeenCalled()
        await user.click(screen.getByRole('button', { name: /Сохранить требования/ }))
        await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({
            enabled: true, required_course_ids: [17],
        })))
        expect(search).toHaveBeenCalledWith('Биоинформатика')
    })

    it('marks a course in a required block as unconfirmed, never as coverage', async () => {
        const user = userEvent.setup()
        const save = vi.fn().mockResolvedValue(undefined)
        render(<CurriculumRequirements value={{ enabled: true, core_blocks: [] }} onSave={save} searchCourses={vi.fn()} />)
        await user.type(screen.getByRole('textbox', { name: /Название профильного блока/ }), 'Деревообработка')
        await user.click(screen.getByRole('button', { name: /Добавить блок/ }))
        expect(screen.getByText(/нужно подтверждение содержания/i)).toBeInTheDocument()
        await user.click(screen.getByRole('button', { name: /Сохранить требования/ }))
        await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({
            core_blocks: [expect.objectContaining({ title: 'Деревообработка', requirement: 'preferred' })],
        })))
    })

    it('can save turning an already-enabled profile mode off', async () => {
        const user = userEvent.setup()
        const save = vi.fn().mockResolvedValue(undefined)
        render(<CurriculumRequirements value={{ enabled: true }} onSave={save} searchCourses={vi.fn()} />)
        await user.click(screen.getByRole('checkbox', { name: /Учитывать профильные/ }))
        await user.click(screen.getByRole('button', { name: /Сохранить отключение/ }))
        await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ enabled: false })))
    })

    it('shows source evidence before submitting a server-bound confirmation', async () => {
        const user = userEvent.setup()
        const loadPreview = vi.fn().mockResolvedValue({
            course: { id: 17, course_id: 'EPVO-17', title: 'Технология деревообработки' },
            source_fields: { description: 'Проектирование и обработка изделий из древесины.' },
            expected_course_hash: 'a'.repeat(64), expected_block_hash: 'b'.repeat(64),
        })
        const confirmMatch = vi.fn().mockResolvedValue({ status: 'confirmed' })
        render(<CurriculumRequirements value={{ enabled: true, core_blocks: [{
            id: 'wood', title: 'Деревообработка', requirement: 'preferred',
            accepted_course_ids: [17], min_courses: 1, min_credits: 0,
        }] }} onSave={vi.fn()} searchCourses={vi.fn()} loadPreview={loadPreview} confirmMatch={confirmMatch} />)
        await user.click(screen.getByRole('button', { name: /Проверить содержание/ }))
        expect(await screen.findByText(/Проектирование и обработка изделий из древесины/)).toBeInTheDocument()
        expect(confirmMatch).not.toHaveBeenCalled()
        await user.type(screen.getByRole('textbox', { name: /Фрагмент источника/ }), 'обработка изделий из древесины')
        await user.type(screen.getByRole('textbox', { name: /Почему курс подходит/ }), 'Соответствует профильному блоку')
        await user.click(screen.getByRole('button', { name: /Подтвердить соответствие/ }))
        await waitFor(() => expect(confirmMatch).toHaveBeenCalledWith({
            block_id: 'wood', course_id: 17, source_field: 'description',
            source_excerpt: 'обработка изделий из древесины', rationale: 'Соответствует профильному блоку',
            expected_course_hash: 'a'.repeat(64), expected_block_hash: 'b'.repeat(64),
        }))
        expect(await screen.findByText(/подтверждение сохранено; будет перепроверено/i)).toBeInTheDocument()
    })

    it('adds a catalogue candidate to a block and can require it before confirmation', async () => {
        const user = userEvent.setup()
        const save = vi.fn().mockResolvedValue(undefined)
        render(<CurriculumRequirements value={{ enabled: true, core_blocks: [{
            id: 'wood', title: 'Деревообработка', requirement: 'preferred',
            accepted_course_ids: [], min_courses: 1, min_credits: 0,
        }] }} onSave={save} searchCourses={vi.fn().mockResolvedValue([course])} />)
        await user.type(screen.getByRole('textbox', { name: /Найти дисциплину/ }), 'Биоинформатика')
        await user.click(screen.getByRole('button', { name: /Искать в каталоге/ }))
        await user.click(await screen.findByRole('button', { name: /Предложить для блока/ }))
        await user.selectOptions(screen.getByRole('combobox', { name: /Статус блока Деревообработка/ }), 'required')
        await user.click(screen.getByRole('button', { name: /Сохранить требования/ }))
        await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({
            core_blocks: [expect.objectContaining({ requirement: 'required', accepted_course_ids: [17] })],
        })))
        expect(screen.getByText(/не подтверждён по содержанию/)).toBeInTheDocument()
    })
})
