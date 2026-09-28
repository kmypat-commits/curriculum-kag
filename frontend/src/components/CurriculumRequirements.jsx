import { useEffect, useState } from 'react'

const emptyRequirements = () => ({ enabled: false, schema_version: 1, required_course_ids: [], core_blocks: [] })

export default function CurriculumRequirements({ value, onSave, searchCourses, disabled = false }) {
    const [draft, setDraft] = useState(() => ({ ...emptyRequirements(), ...value }))
    const [query, setQuery] = useState('')
    const [blockTitle, setBlockTitle] = useState('')
    const [results, setResults] = useState([])
    const [searching, setSearching] = useState(false)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState('')
    const [notice, setNotice] = useState('')

    useEffect(() => setDraft({ ...emptyRequirements(), ...value }), [value])

    const search = async () => {
        if (query.trim().length < 2) return
        setSearching(true)
        setError('')
        try { setResults(await searchCourses(query.trim())) }
        catch { setError('Не удалось найти дисциплины. Повторите поиск.') }
        finally { setSearching(false) }
    }

    const save = async () => {
        setSaving(true)
        setError('')
        setNotice('')
        try {
            await onSave(draft)
            setNotice('Требования сохранены. Новый план будет учитывать их при следующем построении.')
        } catch (reason) {
            setError(reason?.response?.data?.detail?.message || 'Не удалось сохранить требования. Проверьте выбранные дисциплины и повторите.')
        } finally { setSaving(false) }
    }

    const addBlock = () => {
        const title = blockTitle.trim()
        if (!title || draft.core_blocks.length >= 12) return
        setDraft(current => ({ ...current, core_blocks: [...current.core_blocks, {
            id: crypto.randomUUID(), title, description: '', lo_codes: [],
            requirement: 'preferred', origin: 'methodist', min_courses: 1,
            min_credits: 0, accepted_course_ids: [],
        }] }))
        setBlockTitle('')
        setNotice('')
    }

    return <section className="card" aria-label="Профильные требования">
        <div className="section-head"><h2>Профильные требования</h2></div>
        <label style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <input type="checkbox" checked={Boolean(draft.enabled)} disabled={disabled || saving}
                onChange={event => { setDraft(current => ({ ...current, enabled: event.target.checked })); setNotice('') }} />
            Учитывать профильные блоки и обязательные дисциплины
        </label>
        <p style={{ marginTop: 8, color: 'var(--muted)', fontSize: 13 }}>
            Режим необязателен. Пока он выключен, сохранённые требования не влияют на построение. Изменения применятся после сохранения и нового построения.
        </p>
        {draft.enabled && <div style={{ marginTop: 20 }}>
            <h3 style={{ fontSize: 16 }}>Обязательные дисциплины</h3>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <label className="sr-only" htmlFor="required-course-search">Найти дисциплину</label>
                <input id="required-course-search" className="form-control" style={{ flex: '1 1 220px' }}
                    value={query} onChange={event => setQuery(event.target.value)} placeholder="Название или код ЕПВО" />
                <button className="btn btn-secondary" disabled={disabled || searching || query.trim().length < 2} onClick={search}>
                    {searching ? 'Ищем…' : 'Искать в каталоге'}
                </button>
            </div>
            {results.length > 0 && <ul style={{ listStyle: 'none', marginTop: 8 }}>
                {results.map(course => <li key={course.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                    <span>{course.title} · {course.course_id} · {course.credits} кр.</span>
                    <button className="btn btn-secondary" disabled={disabled || draft.required_course_ids.includes(course.id) || draft.required_course_ids.length >= 30}
                        onClick={() => setDraft(current => ({ ...current, required_course_ids: [...current.required_course_ids, course.id] }))}>
                        Сделать обязательной
                    </button>
                </li>)}
            </ul>}
            {draft.required_course_ids.length > 0 && <p style={{ marginTop: 8, fontSize: 13 }}>
                Выбраны внутренние ID: {draft.required_course_ids.join(', ')}
                <button className="btn btn-secondary" style={{ marginLeft: 8 }} onClick={() => setDraft(current => ({ ...current, required_course_ids: [] }))}>Очистить список</button>
            </p>}
            <h3 style={{ fontSize: 16, marginTop: 20 }}>Профильные блоки</h3>
            <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 6 }}>Блок сначала предпочтительный. Обязательным его можно сделать после подтверждения содержания подходящих дисциплин.</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <label className="sr-only" htmlFor="core-block-title">Название профильного блока</label>
                <input id="core-block-title" className="form-control" style={{ flex: '1 1 220px' }} value={blockTitle}
                    onChange={event => setBlockTitle(event.target.value)} placeholder="Например, технологии обработки древесины" />
                <button className="btn btn-secondary" disabled={disabled || !blockTitle.trim() || draft.core_blocks.length >= 12} onClick={addBlock}>Добавить блок</button>
            </div>
            {draft.core_blocks.map(block => <div key={block.id} style={{ marginTop: 12, padding: 12, border: '1px solid var(--line)', borderRadius: 12 }}>
                <strong>{block.title}</strong>
                <span style={{ marginLeft: 10, color: 'var(--muted)', fontSize: 13 }}>
                    {block.requirement === 'required' ? 'обязательный' : 'предпочтительный'} · нужно подтверждение содержания
                </span>
                <button className="btn btn-secondary" style={{ marginLeft: 10 }} disabled={disabled}
                    onClick={() => setDraft(current => ({ ...current, core_blocks: current.core_blocks.filter(item => item.id !== block.id) }))}>Убрать блок</button>
            </div>)}
            <div style={{ marginTop: 18 }}><button className="btn btn-primary" disabled={disabled || saving} onClick={save}>
                {saving ? 'Сохраняем…' : 'Сохранить требования'}
            </button></div>
        </div>}
        {!draft.enabled && value?.enabled && <button className="btn btn-secondary" style={{ marginTop: 12 }} disabled={disabled || saving} onClick={save}>Сохранить отключение</button>}
        {error && <p role="alert" style={{ color: 'var(--red)', marginTop: 10 }}>{error}</p>}
        {notice && <p role="status" style={{ color: 'var(--green)', marginTop: 10 }}>{notice}</p>}
    </section>
}
