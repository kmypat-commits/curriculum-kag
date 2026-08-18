export default function LoCoveragePanel({
    activeVariant,
    loCoverageSources,
    loadLoCoverageSources,
    loadingLoCoverageSources,
    localText,
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
        </div>
        )}
        </div>
    )
}
