const statusLabels = {
    covered: 'покрыт',
    unconfirmed: 'не подтверждён',
    gap: 'нет покрытия',
}

export default function CoreCoveragePanel({ coverage }) {
    if (!coverage?.enabled) return null

    const blocks = coverage.core_coverage || []
    const required = coverage.required_courses || {}
    const missing = required.missing || []

    return <section aria-label="Покрытие профильного ядра" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Покрытие профильного ядра</h3>
        <p style={{ margin: '0 0 8px', fontSize: 13 }}>
            Подтверждённые профильные кредиты: {coverage.unique_core_credits || 0}
            {' · '}Обязательные курсы: {(required.included || []).length}/{(required.requested || []).length}
        </p>
        {blocks.length === 0 && <p style={{ margin: '0 0 8px', color: 'var(--muted)' }}>Профильные блоки не заданы.</p>}
        {blocks.length > 0 && <ul style={{ margin: '0 0 8px', paddingLeft: 20, lineHeight: 1.6 }}>
            {blocks.map(block => <li key={block.block_id}>
                {block.title} — {statusLabels[block.status] || block.status}
                {' · '}{block.requirement === 'required' ? 'обязательный' : 'предпочтительный'}
                {block.status === 'covered' && ` · ${block.supported_credits} кр.`}
                {(block.unconfirmed_course_ids || []).length > 0 &&
                    <span> · выбранные, но не подтверждённые: {block.unconfirmed_course_ids.map(id => `ID ${id}`).join(', ')}</span>}
            </li>)}
        </ul>}
        {missing.length > 0 && <p role="alert">Не включены обязательные курсы: {missing.map(id => `ID ${id}`).join(', ')}</p>}
        <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)' }}>
            Не является предметной экспертизой или разрешением на внедрение. Неподтверждённые курсы не засчитываются в профильное покрытие.
        </p>
    </section>
}
