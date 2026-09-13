export default function BridgeReplacementPanel({
    activeVariant,
    aiBridgeCandidates,
    applyAllBridgeReplacements,
    applyBridgeReplacement,
    bridgePreview,
    building,
    confirmAiBridgeCandidate,
    confirmingAiBridge,
    currentPlan,
    handleBuild,
    loadAiBridgeCandidates,
    loadBridgePreview,
    loadingAiBridge,
    loadingBridgePreview,
    localizedCourseField,
    replacingAllBridges,
    replacingBridge,
    requiresRegeneration,
    selectMediumBridgeReplacements,
    selectedBridgeReplacements,
    setSelectedBridgeReplacements,
    t,
}) {
    return (
        <>

            {(currentPlan.metrics.num_bridge_modules || 0) > 0 && (
            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082', color: '#6d4c41' }}>
            <strong>{t('bridge_review')}: {currentPlan.metrics.num_bridge_modules}</strong>
            <div style={{ fontSize: 12, marginTop: 4 }}>
            {t('bridge_review_desc')}
            </div>
            <button className="btn btn-secondary" onClick={loadBridgePreview} disabled={loadingBridgePreview} style={{ marginTop: 8 }}>
            {loadingBridgePreview ? t('search_replacements') : t('find_real_courses')}
            </button>
            {bridgePreview?.variant === activeVariant && (
            Object.keys(selectedBridgeReplacements).length > 0
            || (bridgePreview.suggestions || []).some(row =>
            (row.candidates || []).some(c => c.strong_candidate)
            )
            ) && (
            <button
            className="btn btn-primary"
            onClick={applyAllBridgeReplacements}
            disabled={replacingAllBridges || Boolean(replacingBridge)}
            style={{ marginTop: 8, marginLeft: 8 }}
            >
            {replacingAllBridges
            ? t('replacing')
            : Object.keys(selectedBridgeReplacements).length
            ? `${t('confirm_replacement')}: ${Object.keys(selectedBridgeReplacements).length}`
            : t('replace_all_bridges')}
            </button>
            )}
            {bridgePreview?.variant === activeVariant && (bridgePreview.suggestions || []).some(row => (row.candidates || []).some(c => c.quality_level === 'medium' || c.medium_candidate)) && (
            <button
            className="btn btn-secondary"
            onClick={selectMediumBridgeReplacements}
            disabled={replacingAllBridges || Boolean(replacingBridge)}
            style={{ marginTop: 8, marginLeft: 8, borderColor: '#c17b00', color: '#8a5a00' }}
            >
            {t('select_medium')}
            </button>
            )}
            {bridgePreview?.variant === activeVariant && (
            <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
            {bridgePreview.summary && (
            <div style={{ padding: '8px 10px', borderRadius: 8, background: '#fff3cd', border: '1px solid #ffecb5', color: '#6d4c00', fontSize: 12 }}>
            <strong>{t('replacement_summary')}:</strong>{' '}
            {t('replacement_summary_text').replace('{count}', bridgePreview.summary.bridge_count).replace('{credits}', bridgePreview.summary.bridge_credits).replace('{strong}', bridgePreview.summary.with_strong_candidate).replace('{medium}', bridgePreview.summary.with_medium_candidate || 0).replace('{without}', bridgePreview.summary.without_strong_candidate)}
            <div style={{ marginTop: 4 }}>
            {bridgePreview.summary.diagnosis}
            </div>
            </div>
            )}
            {bridgePreview.elapsed_seconds !== undefined && (
            <div style={{ fontSize: 12, color: '#6d4c41' }}>
            {t('replacement_search_done').replace('{seconds}', bridgePreview.elapsed_seconds)}
            </div>
            )}
            {(bridgePreview.suggestions || []).map(row => {
            const good = (row.candidates || []).filter(c => c.strong_candidate || c.medium_candidate)
            return (
            <div key={row.bridge_item_id} style={{ fontSize: 12, padding: 8, borderRadius: 6, background: '#fff', border: '1px solid #f3d27a' }}>
            <b>{row.bridge_title}</b> · {row.credits} {t('credits')} · LO: {(row.target_los || []).join(', ')}
            {good.length > 0 ? (
            <div style={{ marginTop: 4 }}>
            {good.slice(0, 3).map(c => (
            <div key={c.course_id} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', padding: '8px 0', borderTop: '1px solid #f3ead2' }}>
            <span>
            <label style={{ display: 'flex', gap: 7, alignItems: 'flex-start', cursor: 'pointer' }}>
            <input
            type="radio"
            name={`bridge-replacement-${row.bridge_item_id}`}
            checked={Number(selectedBridgeReplacements[row.bridge_item_id]) === Number(c.course_id)}
            onChange={() => setSelectedBridgeReplacements(current => ({ ...current, [row.bridge_item_id]: c.course_id }))}
            />
            <strong>→ {localizedCourseField(c.title_translations, c.title)}</strong>
            </label> · {c.credits} {t('credits')} · {c.quality_level === 'strong' ? t('strong_quality') : t('medium_quality')} · {t('ai_short')} {Math.round((c.model_score || 0) * 100)}% · {t('epvo_short')} {Math.round((c.expert_score || 0) * 100)}% · LO {Math.round((c.coverage_ratio || 0) * 100)}%
            <div style={{ marginTop: 3, color: '#5d6470', lineHeight: 1.35 }}>{c.description}</div>
            </span>
            <button
            className="btn btn-primary"
            style={{ padding: '5px 9px', fontSize: 11, whiteSpace: 'nowrap' }}
            disabled={Boolean(replacingBridge) || replacingAllBridges}
            onClick={() => applyBridgeReplacement(row.bridge_item_id, c.course_id)}
            >
            {replacingBridge === `${row.bridge_item_id}:${c.course_id}`
            ? t('adding')
            : t('confirm_replacement')}
            </button>
            </div>
            ))}
            </div>
            ) : (
            <div style={{ marginTop: 4, color: '#8a5a00' }}>{t('no_strong_replacement')}</div>
            )}
            <button
            className="btn btn-secondary"
            style={{ marginTop: 8, padding: '6px 10px', fontSize: 11 }}
            disabled={loadingAiBridge === row.bridge_item_id || Boolean(confirmingAiBridge)}
            onClick={() => loadAiBridgeCandidates(row.bridge_item_id)}
            >
            {loadingAiBridge === row.bridge_item_id
            ? t('ai_generating')
            : t('generate_ai_courses')}
            </button>
            {aiBridgeCandidates[row.bridge_item_id] && (
            <div style={{ marginTop: 8, display: 'grid', gap: 7 }}>
            {(aiBridgeCandidates[row.bridge_item_id].candidates || []).map(candidate => (
            <div key={candidate.candidate_id} style={{ padding: 8, borderRadius: 6, background: '#f7f9fc', border: '1px solid #dce5ef' }}>
            <strong>{localizedCourseField({ ru: candidate.title_ru, kk: candidate.title_kk, en: candidate.title_en }, candidate.title_ru)}</strong> · {row.credits} {t('credits')}
            <div style={{ marginTop: 3, color: '#5d6470', lineHeight: 1.35 }}>{localizedCourseField({ ru: candidate.description_ru, kk: candidate.description_kk, en: candidate.description_en }, candidate.description_ru)}</div>
            <div style={{ marginTop: 4, color: '#53657a' }}>LO: {(candidate.target_los || []).join(', ')}</div>
            <button
            className="btn btn-primary"
            style={{ marginTop: 6, padding: '5px 9px', fontSize: 11 }}
            disabled={Boolean(confirmingAiBridge)}
            onClick={() => confirmAiBridgeCandidate(row.bridge_item_id, candidate)}
            >
            {confirmingAiBridge === `${row.bridge_item_id}:${candidate.candidate_id}`
            ? t('confirming')
            : t('confirm_replace_bridge')}
            </button>
            </div>
            ))}
            <div style={{ fontSize: 11, color: '#7a6570' }}>
            {t('ai_proposal')}
            </div>
            </div>
            )}
            </div>
            )
            })}
            </div>
            )}
            {requiresRegeneration && (
            <button className="btn btn-primary" onClick={handleBuild} disabled={building} style={{ marginTop: 10 }}>
            {building
            ? t('rebuilding')
            : t('regenerate_changes')}
            </button>
            )}
            </div>
            )}
        </>
    )
}
