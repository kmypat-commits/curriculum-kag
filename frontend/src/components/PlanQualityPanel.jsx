import { Link } from 'react-router-dom'

import BridgeReplacementPanel from './BridgeReplacementPanel'
import CompactSection from './CompactSection'
import LoCoveragePanel from './LoCoveragePanel'


export default function PlanQualityPanel({
    activeVariant,
    aiBridgeCandidates,
    applyAllBridgeReplacements,
    applyBridgeReplacement,
    applyCourseReplacement,
    applyingCourseReplacement,
    applyingQuality,
    bridgePreview,
    building,
    compactToggleLabel,
    confirmAiBridgeCandidate,
    confirmSuspiciousCourse,
    confirmingAiBridge,
    courseReplacementPreviews,
    currentPlan,
    currentPlanHasHardViolations,
    excludedCourses,
    handleApplyQualityImprovements,
    handleBuild,
    handleMatchFeedback,
    id,
    loCoverageSources,
    loadAiBridgeCandidates,
    loadAllVisibleCourseReplacements,
    loadBridgePreview,
    loadCourseReplacements,
    loadLoCoverageSources,
    loadingAiBridge,
    loadingBridgePreview,
    loadingCourseReplacement,
    loadingLoCoverageSources,
    localText,
    localize,
    localizeDomain,
    localizedCourseField,
    matchFeedbackState,
    replacingAllBridges,
    replacingBridge,
    requiresRegeneration,
    selectMediumBridgeReplacements,
    selectedBridgeReplacements,
    setSelectedBridgeReplacements,
    t,
    toggleCourseExclusion,
}) {
    return (
        <>
            {currentPlan && currentPlan.metrics_current === false && (
            <div style={{ marginBottom: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082', color: '#6d4c41' }}>
                <strong>{localText('Метрики плана требуют обновления', 'Жоспар метрикаларын жаңарту қажет', 'Plan metrics need refresh')}</strong>
                <div style={{ marginTop: 4, fontSize: 13 }}>
                    {localText(
                        'Этот вариант создан предыдущей версией валидатора. Перестройте вариант, чтобы заново проверить кредиты, нагрузку, пререквизиты и доказательства LO.',
                        'Бұл нұсқа валидатордың алдыңғы нұсқасымен жасалған. Кредиттерді, жүктемені, пререквизиттерді және LO дәлелдерін қайта тексеру үшін нұсқаны қайта құрыңыз.',
                        'This variant was created by an earlier validator. Rebuild it to recheck credits, workload, prerequisites, and LO evidence.',
                    )}
                </div>
                <button className="btn btn-secondary" style={{ marginTop: 8 }} onClick={handleBuild} disabled={building}>
                    {localText('Перестроить и проверить', 'Қайта құрып, тексеру', 'Rebuild and verify')}
                </button>
            </div>
            )}
            {currentPlan?.metrics?.verification && (
            <CompactSection title={t('verification')} toggleLabel={compactToggleLabel} accent={currentPlan.metrics.verification.feasible ? '#2e7d32' : '#c62828'} defaultOpen={false}>
            <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
            <span>{t('feasible')}: <strong>{currentPlan.metrics.verification.feasible ? t('yes') : t('no')}</strong></span>
            <span>{t('total_credits')}: <strong>{currentPlan.metrics.total_credits}/{currentPlan.metrics.target_credits}</strong></span>
            <span>{t('prerequisite_violations')}: <strong>{currentPlan.metrics.prerequisite_violations}</strong></span>
            <span>{t('load_violations')}: <strong>{currentPlan.metrics.semester_load_violations}</strong></span>
            <span>{t('min_lo_coverage')}: <strong>{Math.round((currentPlan.metrics.min_lo_coverage || 0) * 100)}%</strong></span>
            <span>{t('evidence_count')}: <strong>{currentPlan.metrics.evidence_count || 0}</strong></span>
            <span>{t('redundancy')}: <strong>{currentPlan.metrics.redundancy || 0}</strong></span>
            </div>
            {currentPlanHasHardViolations && (
            <button
            className="btn btn-primary"
            onClick={handleApplyQualityImprovements}
            disabled={applyingQuality || building}
            style={{ marginTop: 12 }}
            >
            {applyingQuality ? t('applying_quality_improvements') : localText('Исправить порядок, нагрузку и кредиты', 'Ретті, жүктемені және кредиттерді түзету', 'Fix order, load, and credits')}
            </button>
            )}
            <BridgeReplacementPanel
            activeVariant={activeVariant}
            aiBridgeCandidates={aiBridgeCandidates}
            applyAllBridgeReplacements={applyAllBridgeReplacements}
            applyBridgeReplacement={applyBridgeReplacement}
            bridgePreview={bridgePreview}
            building={building}
            confirmAiBridgeCandidate={confirmAiBridgeCandidate}
            confirmingAiBridge={confirmingAiBridge}
            currentPlan={currentPlan}
            handleBuild={handleBuild}
            loadAiBridgeCandidates={loadAiBridgeCandidates}
            loadBridgePreview={loadBridgePreview}
            loadingAiBridge={loadingAiBridge}
            loadingBridgePreview={loadingBridgePreview}
            localText={localText}
            localizedCourseField={localizedCourseField}
            replacingAllBridges={replacingAllBridges}
            replacingBridge={replacingBridge}
            requiresRegeneration={requiresRegeneration}
            selectMediumBridgeReplacements={selectMediumBridgeReplacements}
            selectedBridgeReplacements={selectedBridgeReplacements}
            setSelectedBridgeReplacements={setSelectedBridgeReplacements}
            t={t}
            />
            {currentPlan.domain_breakdown && (
            <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8 }}>
            {Object.entries(currentPlan.domain_breakdown).filter(([, item]) => item.credits > 0 || item.min_percent > 0).map(([key, item]) => (
            <div key={key} style={{ padding: '8px 10px', borderRadius: 8, background: '#f6f9fc', border: '1px solid #e1e8f0' }}>
            <div style={{ fontSize: 12, color: '#667' }}>{localizeDomain(item.label || key)}</div>
            <strong>{item.credits} {t('credits')}</strong>
            <span style={{ marginLeft: 6, color: '#666', fontSize: 12 }}>{item.percent}%</span>
            {item.min_percent > 0 && <div style={{ fontSize: 11, color: item.percent + 0.01 >= item.min_percent ? '#2e7d32' : '#c62828' }}>{t('minimum')}: {item.min_percent}%</div>}
            </div>
            ))}
            </div>
            )}
            {currentPlan.epvo_plan_quality && (
            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#f5fbff', border: '1px solid #d7ecfb' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <strong>{localText('Дисциплины плана из ЕПВО', 'Жоспардағы ЕПВО пәндері', 'Plan courses from EPVO')}: {currentPlan.epvo_plan_quality.match_percentage}%</strong>
            <span style={{ color: '#566' }}>
            {localText('типовых дисциплин', 'типтік пәндер', 'typical courses')}: {currentPlan.epvo_plan_quality.matched_courses}/{currentPlan.epvo_plan_quality.course_count}
            </span>
            <span style={{ color: '#566' }}>
            {localText('экспертных связей', 'сараптамалық байланыстар', 'expert links')}: {currentPlan.epvo_plan_quality.expert_links}
            </span>
            </div>
            <Link to={`/projects/${id}/epvo`} className="btn btn-secondary" style={{ padding: '7px 12px', whiteSpace: 'nowrap' }}>
            {localText('Полный анализ ЕПВО', 'ЕПВО толық талдауы', 'Full EPVO analysis')}
            </Link>
            </div>
            </div>
            )}
            <LoCoveragePanel
            activeVariant={activeVariant}
            loCoverageSources={loCoverageSources}
            loadLoCoverageSources={loadLoCoverageSources}
            loadingLoCoverageSources={loadingLoCoverageSources}
            localText={localText}
            t={t}
            />
            {currentPlan.suspicious_courses?.length > 0 && (
            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082' }}>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}>
            <strong>{localText('Сомнительные дисциплины', 'Күмәнді пәндер', 'Suspicious courses')}: {currentPlan.suspicious_courses.length}</strong>
            <button
            className="btn btn-secondary"
            style={{ padding: '5px 9px', fontSize: 11, borderColor: '#c17b00' }}
            disabled={loadingCourseReplacement === 'all'}
            onClick={loadAllVisibleCourseReplacements}
            >
            {loadingCourseReplacement === 'all'
            ? localText('Ищем замены…', 'Ауыстырулар ізделуде…', 'Searching replacements…')
            : localText('Подобрать замены для всех видимых', 'Көрінетіндердің бәріне ауыстыру табу', 'Find replacements for all visible')}
            </button>
            </div>
            <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
            {currentPlan.suspicious_courses.slice(0, 6).map((row, idx) => (
            <div key={`${row.course_id}-${idx}`} style={{ fontSize: 12, color: '#6d4c41' }}>
            <strong>{row.title}</strong> · {t('semester')} {row.semester} · {Math.round((row.max_score || 0) * 100)}%
            <span style={{ marginLeft: 6 }}>
            {row.reasons?.map(reason => localText(
            reason === 'wrong_education_level' ? 'не соответствует уровню образования' : reason === 'not_core_for_program' ? 'не ядро программы' : reason === 'weak_lo_evidence' ? 'слабое LO-доказательство' : 'слишком рано',
            reason === 'wrong_education_level' ? 'білім деңгейіне сәйкес емес' : reason === 'not_core_for_program' ? 'бағдарлама өзегі емес' : reason === 'weak_lo_evidence' ? 'LO дәлелі әлсіз' : 'тым ерте',
            reason === 'wrong_education_level' ? 'wrong degree level' : reason === 'not_core_for_program' ? 'not programme core' : reason === 'weak_lo_evidence' ? 'weak LO evidence' : 'too early',
            )).join('; ')}
            </span>
            {row.top_lo_code && <div style={{ marginTop: 4, color: '#5d6470' }} title={row.top_lo_text || row.top_lo_code}>
            {localText('Лучшая связь', 'Ең жақсы байланыс', 'Best link')}: {row.top_lo_code} · {Math.round((row.max_score || 0) * 100)}%
            </div>}
            {row.reason_details?.length > 0 && (
            <div style={{ marginTop: 4, color: '#6d4c41', lineHeight: 1.35 }}>
            {row.reason_details.map((reason, reasonIndex) => (
            <div key={reasonIndex}>• {reason}</div>
            ))}
            </div>
            )}
            {row.recommendation && (
            <div style={{ marginTop: 4, color: '#39704c', lineHeight: 1.35 }}>
            {row.recommendation}
            </div>
            )}
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 6 }}>
            {row.top_lo_id && <button
            className="btn btn-secondary"
            style={{ padding: '5px 8px', fontSize: 11 }}
            disabled={matchFeedbackState[`${row.course_id}:${row.top_lo_id}`] === 'saving'}
            onClick={() => handleMatchFeedback(row.course_id, row.top_lo_id, 'confirmed')}
            >
            {matchFeedbackState[`${row.course_id}:${row.top_lo_id}`] === 'confirmed' ? '✓ ' : ''}
            {localText('Подтвердить связь', 'Байланысты растау', 'Confirm link')}
            </button>}
            <button
            className="btn btn-secondary"
            style={{ padding: '5px 8px', fontSize: 11, borderColor: '#2e7d32', color: '#2e7d32' }}
            onClick={() => confirmSuspiciousCourse(row.course_id, row.title)}
            >
            {localText('Оставить в плане', 'Жоспарда қалдыру', 'Keep in plan')}
            </button>
            <button
            className="btn btn-secondary"
            style={{ padding: '5px 8px', fontSize: 11, borderColor: '#c17b00' }}
            onClick={() => toggleCourseExclusion(row.course_id, row.title)}
            >
            {excludedCourses[row.course_id]
            ? localText('✓ Заменить при перегенерации', '✓ Қайта құруда ауыстыру', '✓ Replace on regeneration')
            : localText('Отметить на замену', 'Ауыстыруға белгілеу', 'Mark for replacement')}
            </button>
            <button
            className="btn btn-primary"
            style={{ padding: '5px 8px', fontSize: 11 }}
            disabled={loadingCourseReplacement === row.course_id}
            onClick={() => loadCourseReplacements(row.course_id)}
            >
            {loadingCourseReplacement === row.course_id
            ? localText('Поиск…', 'Іздеу…', 'Searching…')
            : localText('Подобрать 3 замены', '3 ауыстыруды таңдау', 'Find 3 replacements')}
            </button>
            </div>
            {courseReplacementPreviews[row.course_id] && <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
            {courseReplacementPreviews[row.course_id].elapsed_seconds !== undefined && (
            <div style={{ color: '#6d4c41', fontSize: 12 }}>
            {localText(`Подбор замен выполнен за ${courseReplacementPreviews[row.course_id].elapsed_seconds}s.`, `Ауыстыруды таңдау ${courseReplacementPreviews[row.course_id].elapsed_seconds}s ішінде орындалды.`, `Replacement preview completed in ${courseReplacementPreviews[row.course_id].elapsed_seconds}s.`)}
            </div>
            )}
            {(courseReplacementPreviews[row.course_id].candidates || []).length ? (courseReplacementPreviews[row.course_id].candidates || []).map(candidate => (
            <div key={candidate.course_id} style={{ padding: 8, borderRadius: 7, background: '#fff', border: '1px solid #ead49e' }}>
            <strong>{localize(candidate.title_translations || candidate.title)}</strong> · {candidate.credits} {t('credits')}
            <div style={{ color: '#667', marginTop: 3 }}>AI {Math.round((candidate.model_score || 0) * 100)}% · ЕПВО {Math.round((candidate.expert_score || 0) * 100)}% · LO {candidate.covered_lo_count}</div>
            {candidate.covered_los?.length > 0 && <div style={{ color: '#46566a', marginTop: 3 }}>
            {localText('Профессиональные LO', 'Кәсіби ОН', 'Professional LOs')}: {candidate.covered_los.join(', ')}
            {candidate.recommended_semester ? ` · ${localText('рекомендуемый семестр', 'ұсынылатын семестр', 'recommended semester')} ${candidate.recommended_semester}` : ''}
            </div>}
            {candidate.selection_reason && <div style={{ color: '#39704c', marginTop: 3 }}>{localize(candidate.selection_reason_translations || candidate.selection_reason)}</div>}
            {candidate.description && <div style={{ color: '#667', marginTop: 3 }}>{candidate.description}</div>}
            <button className="btn btn-primary" style={{ marginTop: 6, padding: '5px 8px', fontSize: 11 }} disabled={Boolean(applyingCourseReplacement)} onClick={() => applyCourseReplacement(row.course_id, candidate.course_id)}>
            {applyingCourseReplacement === `${row.course_id}:${candidate.course_id}` ? localText('Замена…', 'Ауыстыру…', 'Replacing…') : localText('Подтвердить замену', 'Ауыстыруды растау', 'Confirm replacement')}
            </button>
            </div>
            )) : <div style={{ color: '#8a5a00' }}>{courseReplacementPreviews[row.course_id].no_candidate_reason || localText('Подходящей равноценной замены пока нет.', 'Сәйкес балама әлі жоқ.', 'No equivalent replacement found yet.')}</div>}
            </div>}
            </div>
            ))}
            </div>
            <div style={{ marginTop: 6, fontSize: 12, color: '#795548' }}>
            {localText('Система не блокирует просмотр, но такие дисциплины нужно заменить или подтвердить экспертом.', 'Жүйе қарауды бұғаттамайды, бірақ мұндай пәндерді ауыстыру немесе сарапшымен растау керек.', 'The system does not block viewing, but these courses should be replaced or expert-confirmed.')}
            </div>
            </div>
            )}
            </CompactSection>
            )}
        </>
    )
}
