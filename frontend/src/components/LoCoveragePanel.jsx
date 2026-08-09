export default function LoCoveragePanel({
    activeVariant,
    expandedLoCourses,
    loCoverageSources,
    loadLoCoverageSources,
    loadingLoCoverageSources,
    localText,
    setExpandedLoCourses,
    t,
}) {
    return (

        <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#f8fbff', border: '1px solid #dce9f7' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div>
        <strong>{localText('Источники покрытия LO', 'LO қамту көздері', 'LO coverage sources')}</strong>
        <div style={{ fontSize: 12, color: '#566', marginTop: 2 }}>
        {localText('Показывает, какие результаты закрыты реальными дисциплинами, а какие только bridge-модулями.', 'Қай нәтижелер нақты пәндермен, қайсысы bridge-модульдермен жабылғанын көрсетеді.', 'Shows which outcomes are covered by real courses and which only by bridge modules.')}
        </div>
        </div>
        <button className="btn btn-secondary" onClick={loadLoCoverageSources} disabled={loadingLoCoverageSources}>
        {loadingLoCoverageSources ? localText('Загрузка…', 'Жүктеу…', 'Loading…') : localText('Показать LO-источники', 'LO көздерін көрсету', 'Show LO sources')}
        </button>
        </div>
        {loCoverageSources?.variant === activeVariant && (
        <div style={{ marginTop: 10 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12 }}>
        <span>{localText('Всего LO', 'Барлық LO', 'Total LOs')}: <b>{loCoverageSources.summary?.los || 0}</b></span>
        <span style={{ color: '#2e7d32' }}>{localText('реальные дисциплины', 'нақты пәндер', 'real courses')}: <b>{loCoverageSources.summary?.real_confirmed || 0}</b></span>
        <span style={{ color: '#8a5a00' }}>bridge: <b>{loCoverageSources.summary?.bridge_supported || 0}</b></span>
        <span style={{ color: '#c62828' }}>{localText('слабые', 'әлсіз', 'weak')}: <b>{loCoverageSources.summary?.weak || 0}</b></span>
        </div>
        <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #dfeaf6' }}>
        <div style={{ fontWeight: 700, marginBottom: 6, color: '#17233b' }}>
        {localText('\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u043e\u0431\u0443\u0447\u0435\u043d\u0438\u044f \u0438 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u0438\u0445 \u043f\u043e\u043a\u0440\u044b\u0432\u0430\u044e\u0442', '\u041e\u049b\u0443 \u043d\u04d9\u0442\u0438\u0436\u0435\u043b\u0435\u0440\u0456 \u0436\u04d9\u043d\u0435 \u043e\u043b\u0430\u0440\u0434\u044b \u049b\u0430\u043c\u0442\u0438\u0442\u044b\u043d \u043f\u04d9\u043d\u0434\u0435\u0440', 'Learning outcomes and covering courses')}
        </div>
        <div style={{ fontSize: 12, color: '#566', marginBottom: 8 }}>
        {localText('\u041f\u043e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0433\u0430\u043b\u043e\u0447\u043a\u0443 \u043d\u0430\u043f\u0440\u043e\u0442\u0438\u0432 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430 \u043e\u0431\u0443\u0447\u0435\u043d\u0438\u044f, \u0447\u0442\u043e\u0431\u044b \u0443\u0432\u0438\u0434\u0435\u0442\u044c \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b \u043f\u043b\u0430\u043d\u0430, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u044e\u0442 \u0435\u0433\u043e \u0434\u043e\u0441\u0442\u0438\u0436\u0435\u043d\u0438\u0435.', '\u041e\u049b\u0443 \u043d\u04d9\u0442\u0438\u0436\u0435\u0441\u0456\u043d\u0456\u04a3 \u049b\u0430\u0441\u044b\u043d\u0430 \u0431\u0435\u043b\u0433\u0456 \u049b\u043e\u0439\u0441\u0430\u04a3\u044b\u0437, \u043e\u043d\u044b \u0440\u0430\u0441\u0442\u0430\u0439\u0442\u044b\u043d \u0436\u043e\u0441\u043f\u0430\u0440 \u043f\u04d9\u043d\u0434\u0435\u0440\u0456 \u043a\u04e9\u0440\u0441\u0435\u0442\u0456\u043b\u0435\u0434\u0456.', 'Tick a learning outcome to see the plan courses that support it.')}
        </div>
        {false && <div style={{ display: 'grid', gap: 7 }}>
        {(loCoverageSources.items || []).map(row => {
        const loKey = `${activeVariant}:${row.lo_code}`
        const checked = Boolean(expandedLoCourses[loKey])
        const real = row.real_sources || []
        const bridges = row.bridge_sources || []
        return <div key={`lo-course-map-${row.lo_code}`} style={{ padding: '8px 10px', borderRadius: 8, background: checked ? '#f8fbff' : '#fbfcfe', border: '1px solid #e4edf7' }}>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer' }}>
        <input
        type="checkbox"
        checked={checked}
        onChange={() => setExpandedLoCourses(current => ({ ...current, [loKey]: !current[loKey] }))}
        style={{ marginTop: 3 }}
        />
        <span>
        <strong>{row.lo_code}</strong> ? {Math.round((row.coverage || 0) * 100)}% ? {row.status === 'real_confirmed' ? localText('\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e \u0440\u0435\u0430\u043b\u044c\u043d\u044b\u043c\u0438 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u0430\u043c\u0438', '\u043d\u0430\u049b\u0442\u044b \u043f\u04d9\u043d\u0434\u0435\u0440\u043c\u0435\u043d \u0440\u0430\u0441\u0442\u0430\u043b\u0493\u0430\u043d', 'confirmed by real courses') : row.status === 'bridge_supported' ? localText('\u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0430\u043d\u043e bridge-\u043c\u043e\u0434\u0443\u043b\u0435\u043c', 'bridge-\u043c\u043e\u0434\u0443\u043b\u044c\u043c\u0435\u043d \u049b\u043e\u043b\u0434\u0430\u0443 \u0442\u0430\u043f\u049b\u0430\u043d', 'supported by a bridge module') : localText('\u043d\u0443\u0436\u043d\u043e \u0443\u0441\u0438\u043b\u0438\u0442\u044c', '\u043a\u04af\u0448\u0435\u0439\u0442\u0443 \u049b\u0430\u0436\u0435\u0442', 'needs strengthening')}
        <span style={{ display: 'block', marginTop: 2, color: '#667085', fontSize: 12 }}>{row.lo_text}</span>
        </span>
        </label>
        {checked && <div style={{ marginTop: 8, paddingLeft: 25, display: 'grid', gap: 5, fontSize: 12 }}>
        {real.length > 0 && real.map(src => (
        <div key={`lo-real-${row.lo_code}-${src.course_id}`} style={{ color: '#1b5e20' }}>
        ? {src.title} ? {src.credits} {t('credits')} ? AI {Math.round((src.score || 0) * 100)}% ? EPVO {Math.round((src.expert_score || 0) * 100)}%
        </div>
        ))}
        {bridges.length > 0 && bridges.map(src => (
        <div key={`lo-bridge-${row.lo_code}-${src.bridge_id || src.title}`} style={{ color: '#8a5a00' }}>
        ? bridge: {src.title} ? {src.credits} {t('credits')} ? {t('semester')} {src.semester}
        </div>
        ))}
        {real.length === 0 && bridges.length === 0 && <div style={{ color: '#b71c1c' }}>
        {localText('\u0412 \u0442\u0435\u043a\u0443\u0449\u0435\u043c \u043f\u043b\u0430\u043d\u0435 \u043d\u0435\u0442 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u0443\u0432\u0435\u0440\u0435\u043d\u043d\u043e \u043f\u043e\u043a\u0440\u044b\u0432\u0430\u044e\u0442 \u044d\u0442\u043e\u0442 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442.', '\u0410\u0493\u044b\u043c\u0434\u0430\u0493\u044b \u0436\u043e\u0441\u043f\u0430\u0440\u0434\u0430 \u0431\u04b1\u043b \u043d\u04d9\u0442\u0438\u0436\u0435\u043d\u0456 \u0441\u0435\u043d\u0456\u043c\u0434\u0456 \u049b\u0430\u043c\u0442\u0438\u0442\u044b\u043d \u043f\u04d9\u043d\u0434\u0435\u0440 \u0436\u043e\u049b.', 'No courses in the current plan confidently cover this outcome.')}
        </div>}
        </div>}
        </div>
        })}
        </div>}
        </div>
        <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
        {(loCoverageSources.items || []).map(row => (
        <details key={row.lo_code} style={{ padding: 8, borderRadius: 7, background: '#fff', border: '1px solid #e2edf7' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
        {row.lo_code}: {Math.round((row.coverage || 0) * 100)}%
        <span style={{
        marginLeft: 8,
        padding: '2px 7px',
        borderRadius: 999,
        fontSize: 11,
        background: row.status === 'real_confirmed' ? '#e8f5e9' : row.status === 'bridge_supported' ? '#fff8e1' : '#ffebee',
        color: row.status === 'real_confirmed' ? '#1b5e20' : row.status === 'bridge_supported' ? '#8a5a00' : '#b71c1c'
        }}>
        {row.status === 'real_confirmed' ? localText('реальная дисциплина', 'нақты пән', 'real course') : row.status === 'bridge_supported' ? 'bridge' : localText('слабое покрытие', 'әлсіз қамту', 'weak')}
        </span>
        </summary>
        <div style={{ marginTop: 6, fontSize: 12, color: '#455' }}>{row.lo_text}</div>
        <div style={{ marginTop: 5, padding: '6px 8px', borderRadius: 6, background: row.coverage_kind === 'bridge_target_assumption' ? '#fff8e1' : '#f5f8fb', fontSize: 11, color: '#5d6470' }}>
        {row.coverage_explanation || (row.status === 'bridge_supported'
        ? localText('75% — служебная оценка проектного bridge, а не экспертная оценка реальной дисциплины ЕПВО.', '75% — жобалық bridge қызметтік бағасы, нақты ЕПВО пәнінің сараптамалық бағасы емес.', '75% is a planning assumption for a proposed bridge, not an expert EPVO course score.')
        : '')}
        </div>
        <div style={{ marginTop: 8, display: 'grid', gap: 4, fontSize: 12 }}>
        {(row.real_sources || []).slice(0, 3).map(src => (
        <div key={`real-${row.lo_code}-${src.course_id}`}>✓ {src.title} · {src.credits} {t('credits')} · AI {Math.round((src.score || 0) * 100)}% · EPVO {Math.round((src.expert_score || 0) * 100)}%</div>
        ))}
        {(row.bridge_sources || []).slice(0, 3).map(src => (
        <div key={`bridge-${row.lo_code}-${src.bridge_id}`} style={{ color: '#8a5a00' }}>
        ↳ bridge в плане: {src.title} · {src.credits} {t('credits')} · {t('semester')} {src.semester}
        <button className="btn btn-secondary" style={{ marginLeft: 7, padding: '3px 7px', fontSize: 10 }} onClick={() => document.querySelector(`[data-plan-semester="${src.semester}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>
        {localText('Показать в плане', 'Жоспарда көрсету', 'Show in plan')}
        </button>
        </div>
        ))}
        </div>
        </details>
        ))}
        </div>
        </div>
        )}
        </div>
    )
}
