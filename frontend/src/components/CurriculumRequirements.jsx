import { useEffect, useState } from 'react'

const emptyRequirements = () => ({ enabled: false, schema_version: 1, required_course_ids: [], core_blocks: [] })

export default function CurriculumRequirements({ value, confirmations = [], versionId, onSave, searchCourses, loadPreview, confirmMatch, disabled = false }) {
    const [draft, setDraft] = useState(() => ({ ...emptyRequirements(), ...value }))
    const [query, setQuery] = useState('')
    const [blockTitle, setBlockTitle] = useState('')
    const [selectedBlockId, setSelectedBlockId] = useState('')
    const [results, setResults] = useState([])
    const [searching, setSearching] = useState(false)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState('')
    const [notice, setNotice] = useState('')
    const [preview, setPreview] = useState(null)
    const [sourceField, setSourceField] = useState('description')
    const [excerpt, setExcerpt] = useState('')
    const [rationale, setRationale] = useState('')
    const [confirming, setConfirming] = useState(false)
    const [confirmedKeys, setConfirmedKeys] = useState([])

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

    const addCandidate = (courseId) => {
        const blockId = selectedBlockId || draft.core_blocks[0]?.id
        if (!blockId) return
        setDraft(current => ({ ...current, core_blocks: current.core_blocks.map(block =>
            block.id === blockId && !(block.accepted_course_ids || []).includes(courseId)
                ? { ...block, accepted_course_ids: [...(block.accepted_course_ids || []), courseId] }
                : block
        ) }))
        setNotice('Кандидат добавлен. Сохраните блок, затем проверьте его содержание.')
    }

    const inspectCourse = async (blockId, courseId) => {
        setError('')
        setPreview(null)
        try {
            const evidence = await loadPreview(blockId, courseId)
            setPreview({ ...evidence, block_id: blockId, course_id: courseId })
            setSourceField('description')
            setExcerpt('')
            setRationale('')
        } catch { setError('Не удалось открыть актуальное содержание. Сохраните блок и повторите.') }
    }

    const confirm = async () => {
        if (!preview || !excerpt.trim() || !rationale.trim()) return
        setConfirming(true)
        setError('')
        try {
            await confirmMatch({
                block_id: preview.block_id, course_id: preview.course_id,
                source_field: sourceField, source_excerpt: excerpt.trim(), rationale: rationale.trim(),
                expected_course_hash: preview.expected_course_hash,
                expected_block_hash: preview.expected_block_hash,
            })
            setConfirmedKeys(current => [...current, `${preview.block_id}:${preview.course_id}`])
            setNotice('Соответствие подтверждено. При построении система повторно проверит источник и допуск курса.')
            setPreview(null)
        } catch { setError('Подтверждение не сохранено. Проверьте точный фрагмент источника и актуальность курса.') }
        finally { setConfirming(false) }
    }

    const sourceText = preview?.source_fields?.[sourceField]
    const visibleSource = Array.isArray(sourceText) ? sourceText.join('; ') : String(sourceText || '')

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
                    {draft.core_blocks.length > 0 && <button className="btn btn-secondary" disabled={disabled}
                        onClick={() => addCandidate(course.id)}>Предложить для блока</button>}
                </li>)}
            </ul>}
            {draft.required_course_ids.length > 0 && <p style={{ marginTop: 8, fontSize: 13 }}>
                Выбраны внутренние ID: {draft.required_course_ids.join(', ')}
                <button className="btn btn-secondary" style={{ marginLeft: 8 }} onClick={() => setDraft(current => ({ ...current, required_course_ids: [] }))}>Очистить список</button>
            </p>}
            <h3 style={{ fontSize: 16, marginTop: 20 }}>Профильные блоки</h3>
            <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 6 }}>Блок сначала предпочтительный. Если сделать его обязательным, подтвердите содержание подходящих курсов до построения. Изменение статуса аннулирует прежнее подтверждение.</p>
            {draft.core_blocks.length > 0 && <label style={{ display: 'block', marginTop: 10 }}>
                Добавлять найденные курсы в блок
                <select className="form-control" value={selectedBlockId || draft.core_blocks[0].id}
                    onChange={event => setSelectedBlockId(event.target.value)}>
                    {draft.core_blocks.map(block => <option key={block.id} value={block.id}>{block.title}</option>)}
                </select>
            </label>}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <label className="sr-only" htmlFor="core-block-title">Название профильного блока</label>
                <input id="core-block-title" className="form-control" style={{ flex: '1 1 220px' }} value={blockTitle}
                    onChange={event => setBlockTitle(event.target.value)} placeholder="Например, технологии обработки древесины" />
                <button className="btn btn-secondary" disabled={disabled || !blockTitle.trim() || draft.core_blocks.length >= 12} onClick={addBlock}>Добавить блок</button>
            </div>
            {draft.core_blocks.map(block => <div key={block.id} style={{ marginTop: 12, padding: 12, border: '1px solid var(--line)', borderRadius: 12 }}>
                <strong>{block.title}</strong>
                <label style={{ display: 'block', marginTop: 8, fontSize: 13 }}>
                    Статус блока {block.title}
                    <select className="form-control" value={block.requirement} disabled={disabled}
                        onChange={event => setDraft(current => ({ ...current, core_blocks: current.core_blocks.map(item =>
                            item.id === block.id ? { ...item, requirement: event.target.value } : item
                        ) }))}>
                        <option value="preferred">Предпочтительный</option>
                        <option value="required">Обязательный</option>
                    </select>
                </label>
                <span style={{ color: 'var(--muted)', fontSize: 13 }}>Нужно подтверждение содержания</span>
                <button className="btn btn-secondary" style={{ marginLeft: 10 }} disabled={disabled}
                    onClick={() => setDraft(current => ({ ...current, core_blocks: current.core_blocks.filter(item => item.id !== block.id) }))}>Убрать блок</button>
                {(block.accepted_course_ids || []).map(courseId => <div key={courseId} style={{ marginTop: 8, fontSize: 13 }}>
                    Курс #{courseId} · {confirmedKeys.includes(`${block.id}:${courseId}`) || confirmations.some(record =>
                        record.block_id === block.id && record.course_id === courseId
                        && record.project_version_id === versionId && record.status === 'confirmed'
                    ) ? 'подтверждение сохранено; будет перепроверено при построении' : 'выбранный кандидат, не подтверждён по содержанию'}
                    {value?.core_blocks?.some(saved => saved.id === block.id && saved.accepted_course_ids?.includes(courseId)) && loadPreview && <button
                        className="btn btn-secondary" style={{ marginLeft: 8 }} disabled={disabled || confirming}
                        onClick={() => inspectCourse(block.id, courseId)}>Проверить содержание</button>}
                </div>)}
            </div>)}
            {preview && <div style={{ marginTop: 16, padding: 16, border: '1px solid var(--line)', borderRadius: 12 }}>
                <strong>{preview.course?.title} · {preview.course?.course_id}</strong>
                <p style={{ margin: '8px 0', fontSize: 13 }}>Проверьте реальный текст курса. Названия недостаточно для подтверждения профильного блока.</p>
                <label className="form-label" htmlFor="core-source-field">Источник содержания</label>
                <select id="core-source-field" className="form-control" value={sourceField} onChange={event => setSourceField(event.target.value)}>
                    {Object.entries(preview.source_fields || {}).filter(([, text]) => Boolean(text?.length)).map(([field]) =>
                        <option key={field} value={field}>{field}</option>)}
                </select>
                <p style={{ margin: '10px 0', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{visibleSource}</p>
                <label className="form-label" htmlFor="core-source-excerpt">Фрагмент источника</label>
                <input id="core-source-excerpt" className="form-control" maxLength={1000} value={excerpt}
                    onChange={event => setExcerpt(event.target.value)} placeholder="Скопируйте точный фрагмент из текста выше" />
                <label className="form-label" htmlFor="core-source-rationale" style={{ marginTop: 10 }}>Почему курс подходит</label>
                <textarea id="core-source-rationale" className="form-control" maxLength={1000} value={rationale}
                    onChange={event => setRationale(event.target.value)} />
                <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={disabled || confirming || !excerpt.trim() || !rationale.trim()}
                    onClick={confirm}>{confirming ? 'Проверяем…' : 'Подтвердить соответствие'}</button>
            </div>}
            <div style={{ marginTop: 18 }}><button className="btn btn-primary" disabled={disabled || saving} onClick={save}>
                {saving ? 'Сохраняем…' : 'Сохранить требования'}
            </button></div>
        </div>}
        {!draft.enabled && value?.enabled && <button className="btn btn-secondary" style={{ marginTop: 12 }} disabled={disabled || saving} onClick={save}>Сохранить отключение</button>}
        {error && <p role="alert" style={{ color: 'var(--red)', marginTop: 10 }}>{error}</p>}
        {notice && <p role="status" style={{ color: 'var(--green)', marginTop: 10 }}>{notice}</p>}
    </section>
}
