import { Link } from 'react-router-dom'

import BridgeReplacementPanel from './BridgeReplacementPanel'
import CompactSection from './CompactSection'
import CoreCoveragePanel from './CoreCoveragePanel'
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
    onShowSemester,
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
            <CoreCoveragePanel coverage={currentPlan?.metrics?.core_coverage} />
            {currentPlan && currentPlan.metrics_current === false && (
            <div style={{ marginBottom: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082', color: '#6d4c41' }}>
                <strong>{t('metrics_refresh')}</strong>
                <div style={{ marginTop: 4, fontSize: 13 }}>
                    {t('metrics_refresh_desc')}
                </div>
                <button className="btn btn-secondary" style={{ marginTop: 8 }} onClick={handleBuild} disabled={building}>
                    {t('rebuild_verify')}
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
            {applyingQuality ? t('applying_quality_improvements') : t('fix_quality')}
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
            <strong>{t('epvo_courses')}: {currentPlan.epvo_plan_quality.match_percentage}%</strong>
            <span style={{ color: '#566' }}>
            {t('typical_courses')}: {currentPlan.epvo_plan_quality.matched_courses}/{currentPlan.epvo_plan_quality.course_count}
            </span>
            <span style={{ color: '#566' }}>
            {t('expert_links_label')}: {currentPlan.epvo_plan_quality.expert_links}
            </span>
            </div>
            <Link to={`/projects/${id}/epvo`} className="btn btn-secondary" style={{ padding: '7px 12px', whiteSpace: 'nowrap' }}>
            {t('full_epvo_analysis')}
            </Link>
            </div>
            </div>
            )}
            <LoCoveragePanel
            activeVariant={activeVariant}
            loCoverageSources={loCoverageSources}
            loadLoCoverageSources={loadLoCoverageSources}
            loadingLoCoverageSources={loadingLoCoverageSources}
            onShowSemester={onShowSemester}
            t={t}
            />
            {currentPlan.suspicious_courses?.length > 0 && (
            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082' }}>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}>
            <strong>{t('suspicious_courses')}: {currentPlan.suspicious_courses.length}</strong>
            <button
            className="btn btn-secondary"
            style={{ padding: '5px 9px', fontSize: 11, borderColor: '#c17b00' }}
            disabled={loadingCourseReplacement === 'all'}
            onClick={loadAllVisibleCourseReplacements}
            >
            {loadingCourseReplacement === 'all'
            ? t('searching_replacements')
            : t('find_all_replacements')}
            </button>
            </div>
            <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
            {currentPlan.suspicious_courses.slice(0, 6).map((row, idx) => (
            <div key={`${row.course_id}-${idx}`} style={{ fontSize: 12, color: '#6d4c41' }}>
            <strong>{row.title}</strong> · {t('semester')} {row.semester} · {Math.round((row.max_score || 0) * 100)}%
            <span style={{ marginLeft: 6 }}>
            {row.reasons?.map(reason => t(reason === 'wrong_education_level' ? 'reason_wrong_level' : reason === 'not_core_for_program' ? 'reason_not_core' : reason === 'weak_lo_evidence' ? 'reason_weak_evidence' : 'reason_too_early')).join('; ')}
            </span>
            {row.top_lo_code && <div style={{ marginTop: 4, color: '#5d6470' }} title={row.top_lo_text || row.top_lo_code}>
            {t('best_link')}: {row.top_lo_code} · {Math.round((row.max_score || 0) * 100)}%
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
            {t('confirm_link')}
            </button>}
            <button
            className="btn btn-secondary"
            style={{ padding: '5px 8px', fontSize: 11, borderColor: '#2e7d32', color: '#2e7d32' }}
            onClick={() => confirmSuspiciousCourse(row.course_id, row.title)}
            >
            {t('keep_in_plan')}
            </button>
            <button
            className="btn btn-secondary"
            style={{ padding: '5px 8px', fontSize: 11, borderColor: '#c17b00' }}
            onClick={() => toggleCourseExclusion(row.course_id, row.title)}
            >
            {excludedCourses[row.course_id]
            ? t('replace_on_regeneration_checked')
            : t('mark_replacement')}
            </button>
            <button
            className="btn btn-primary"
            style={{ padding: '5px 8px', fontSize: 11 }}
            disabled={loadingCourseReplacement === row.course_id}
            onClick={() => loadCourseReplacements(row.course_id)}
            >
            {loadingCourseReplacement === row.course_id
            ? t('search_replacements')
            : t('find_replacements')}
            </button>
            </div>
            {courseReplacementPreviews[row.course_id] && <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
            {courseReplacementPreviews[row.course_id].elapsed_seconds !== undefined && (
            <div style={{ color: '#6d4c41', fontSize: 12 }}>
            {t('replacement_preview_done').replace('{seconds}', courseReplacementPreviews[row.course_id].elapsed_seconds)}
            </div>
            )}
            {(courseReplacementPreviews[row.course_id].candidates || []).length ? (courseReplacementPreviews[row.course_id].candidates || []).map(candidate => (
            <div key={candidate.course_id} style={{ padding: 8, borderRadius: 7, background: '#fff', border: '1px solid #ead49e' }}>
            <strong>{localize(candidate.title_translations || candidate.title)}</strong> · {candidate.credits} {t('credits')}
            <div style={{ color: '#667', marginTop: 3 }}>{t('ai_short')} {Math.round((candidate.model_score || 0) * 100)}% · {t('epvo_short')} {Math.round((candidate.expert_score || 0) * 100)}% · LO {candidate.covered_lo_count}</div>
            {candidate.covered_los?.length > 0 && <div style={{ color: '#46566a', marginTop: 3 }}>
            {t('professional_los')}: {candidate.covered_los.join(', ')}
            {candidate.recommended_semester ? ` · ${t('recommended_semester')} ${candidate.recommended_semester}` : ''}
            </div>}
            {candidate.selection_reason && <div style={{ color: '#39704c', marginTop: 3 }}>{localize(candidate.selection_reason_translations || candidate.selection_reason)}</div>}
            {candidate.description && <div style={{ color: '#667', marginTop: 3 }}>{candidate.description}</div>}
            <button className="btn btn-primary" style={{ marginTop: 6, padding: '5px 8px', fontSize: 11 }} disabled={Boolean(applyingCourseReplacement)} onClick={() => applyCourseReplacement(row.course_id, candidate.course_id)}>
            {applyingCourseReplacement === `${row.course_id}:${candidate.course_id}` ? t('replacing') : t('confirm_replacement')}
            </button>
            </div>
            )) : <div style={{ color: '#8a5a00' }}>{courseReplacementPreviews[row.course_id].no_candidate_reason || t('no_equivalent')}</div>}
            </div>}
            </div>
            ))}
            </div>
            <div style={{ marginTop: 6, fontSize: 12, color: '#795548' }}>
            {t('system_not_blocking')}
            </div>
            </div>
            )}
            </CompactSection>
            )}
        </>
    )
}
