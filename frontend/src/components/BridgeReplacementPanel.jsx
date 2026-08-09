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
    localText,
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
            <strong>{localText('Bridge-модули требуют экспертного решения', 'Bridge-модульдер сараптамалық шешімді қажет етеді', 'Bridge modules require expert review')}: {currentPlan.metrics.num_bridge_modules}</strong>
            <div style={{ fontSize: 12, marginTop: 4 }}>
            {localText(
            'Это значит, что реальных дисциплин ЕПВО не хватило для части LO или нагрузки. Лучше перенастроить ЕПВО-направление или заменить bridge реальными дисциплинами.',
            'Бұл кейбір LO немесе жүктеме үшін нақты ЕПВО пәндері жеткіліксіз екенін білдіреді. ЕПВО бағытын қайта баптау немесе bridge орнына нақты пәндерді таңдау ұсынылады.',
            'This means real EPVO courses were insufficient for some LOs or workload. Reconfigure the EPVO scope or replace bridges with real courses.'
            )}
            </div>
            <button className="btn btn-secondary" onClick={loadBridgePreview} disabled={loadingBridgePreview} style={{ marginTop: 8 }}>
            {loadingBridgePreview ? localText('Поиск…', 'Іздеу…', 'Searching…') : localText('Найти реальные дисциплины вместо bridge', 'Bridge орнына нақты пәндерді табу', 'Find real courses instead of bridges')}
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
            ? localText('Замена…', 'Ауыстыру…', 'Replacing…')
            : Object.keys(selectedBridgeReplacements).length
            ? localText(`Подтвердить выбранные: ${Object.keys(selectedBridgeReplacements).length}`, `Таңдалғандарды растау: ${Object.keys(selectedBridgeReplacements).length}`, `Confirm selected: ${Object.keys(selectedBridgeReplacements).length}`)
            : localText('Заменить все подходящие bridge', 'Барлық қолайлы bridge-модульдерді ауыстыру', 'Replace all suitable bridges')}
            </button>
            )}
            {bridgePreview?.variant === activeVariant && (bridgePreview.suggestions || []).some(row => (row.candidates || []).some(c => c.quality_level === 'medium' || c.medium_candidate)) && (
            <button
            className="btn btn-secondary"
            onClick={selectMediumBridgeReplacements}
            disabled={replacingAllBridges || Boolean(replacingBridge)}
            style={{ marginTop: 8, marginLeft: 8, borderColor: '#c17b00', color: '#8a5a00' }}
            >
            {localText('Выбрать все средние замены', 'Барлық орташа ауыстыруларды таңдау', 'Select all medium replacements')}
            </button>
            )}
            {bridgePreview?.variant === activeVariant && (
            <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
            {bridgePreview.summary && (
            <div style={{ padding: '8px 10px', borderRadius: 8, background: '#fff3cd', border: '1px solid #ffecb5', color: '#6d4c00', fontSize: 12 }}>
            <strong>{localText('Итог поиска замен', 'Ауыстыру іздеу қорытындысы', 'Replacement search summary')}:</strong>{' '}
            {localText(
            `${bridgePreview.summary.bridge_count} bridge · ${bridgePreview.summary.bridge_credits} кредитов · сильных: ${bridgePreview.summary.with_strong_candidate} · средних: ${bridgePreview.summary.with_medium_candidate || 0} · без сильной: ${bridgePreview.summary.without_strong_candidate}.`,
            `${bridgePreview.summary.bridge_count} bridge · ${bridgePreview.summary.bridge_credits} кредит · күшті: ${bridgePreview.summary.with_strong_candidate} · орташа: ${bridgePreview.summary.with_medium_candidate || 0} · күштісіз: ${bridgePreview.summary.without_strong_candidate}.`,
            `${bridgePreview.summary.bridge_count} bridges · ${bridgePreview.summary.bridge_credits} credits · strong: ${bridgePreview.summary.with_strong_candidate} · medium: ${bridgePreview.summary.with_medium_candidate || 0} · without strong: ${bridgePreview.summary.without_strong_candidate}.`
            )}
            <div style={{ marginTop: 4 }}>
            {bridgePreview.summary.diagnosis}
            </div>
            </div>
            )}
            {bridgePreview.elapsed_seconds !== undefined && (
            <div style={{ fontSize: 12, color: '#6d4c41' }}>
            {localText(`Поиск замен выполнен за ${bridgePreview.elapsed_seconds}s.`, `Ауыстыруларды іздеу ${bridgePreview.elapsed_seconds}s ішінде орындалды.`, `Replacement search completed in ${bridgePreview.elapsed_seconds}s.`)}
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
            </label> · {c.credits} {t('credits')} · {c.quality_level === 'strong' ? localText('сильная', 'күшті', 'strong') : localText('средняя, нужно подтвердить', 'орташа, растау керек', 'medium, needs confirmation')} · AI {Math.round((c.model_score || 0) * 100)}% · EPVO {Math.round((c.expert_score || 0) * 100)}% · LO {Math.round((c.coverage_ratio || 0) * 100)}%
            <div style={{ marginTop: 3, color: '#5d6470', lineHeight: 1.35 }}>{c.description}</div>
            </span>
            <button
            className="btn btn-primary"
            style={{ padding: '5px 9px', fontSize: 11, whiteSpace: 'nowrap' }}
            disabled={Boolean(replacingBridge) || replacingAllBridges}
            onClick={() => applyBridgeReplacement(row.bridge_item_id, c.course_id)}
            >
            {replacingBridge === `${row.bridge_item_id}:${c.course_id}`
            ? localText('Добавление…', 'Қосу…', 'Adding…')
            : localText('Подтвердить замену', 'Ауыстыруды растау', 'Confirm replacement')}
            </button>
            </div>
            ))}
            </div>
            ) : (
            <div style={{ marginTop: 4, color: '#8a5a00' }}>{localText('Сильной замены пока нет. Автозамена требует подтверждение ЕПВО ≥ 50%, покрытие ≥ 75% профессиональных LO, близкие кредиты и область выбранного направления.', 'Әзірше күшті ауыстыру жоқ. Автоауыстыру үшін ЕПВО растауы ≥ 50%, кәсіби ОН қамтуы ≥ 75%, жақын кредиттер және таңдалған бағыт қажет.', 'No strong replacement yet. Automatic replacement requires EPVO evidence ≥ 50%, coverage of ≥ 75% of professional LOs, similar credits, and the selected programme scope.')}</div>
            )}
            <button
            className="btn btn-secondary"
            style={{ marginTop: 8, padding: '6px 10px', fontSize: 11 }}
            disabled={loadingAiBridge === row.bridge_item_id || Boolean(confirmingAiBridge)}
            onClick={() => loadAiBridgeCandidates(row.bridge_item_id)}
            >
            {loadingAiBridge === row.bridge_item_id
            ? localText('ИИ подбирает 3 варианта…', 'ЖИ 3 нұсқа таңдауда…', 'AI is generating 3 options…')
            : localText('Подобрать 3 дисциплины через ИИ', 'ЖИ арқылы 3 пән ұсыну', 'Generate 3 courses with AI')}
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
            ? localText('Подтверждение…', 'Растау…', 'Confirming…')
            : localText('Подтвердить и заменить bridge', 'Растау және bridge ауыстыру', 'Confirm and replace bridge')}
            </button>
            </div>
            ))}
            <div style={{ fontSize: 11, color: '#7a6570' }}>
            {localText('Это предложение ИИ. В план оно попадёт только после вашего подтверждения.', 'Бұл ЖИ ұсынысы. Жоспарға тек сіз растағаннан кейін енгізіледі.', 'This is an AI proposal. It enters the plan only after your confirmation.')}
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
            ? localText('Перестроение…', 'Қайта құру…', 'Rebuilding…')
            : localText('Перегенерировать A/B/C с изменениями', 'Өзгерістермен A/B/C қайта құру', 'Regenerate A/B/C with changes')}
            </button>
            )}
            </div>
            )}
        </>
    )
}
