import CompactSection from './CompactSection'

/** Compact, language-aware verification cards kept outside the page controller. */
export default function PlanVerificationPanels({ currentPlan, compactToggleLabel, t }) {
    const verification = currentPlan?.metrics?.verification
    if (!verification) return null
    const goso = verification.goso_compliance
    const audit = verification.pedagogical_audit
    return <>
        {goso?.applicable && (
            <CompactSection
                title={t('goso_compliance_title')}
                toggleLabel={compactToggleLabel}
                accent={goso.compliant ? '#2e7d32' : '#c62828'}
                defaultOpen={false}
            >
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 13 }}>
                    <span>{t('status_label')}: <strong>{goso.compliant ? t('goso_compliant') : t('goso_violations')}</strong></span>
                    <span>{t('mandatory_credits')}: <strong>{goso.mandatory_credits}</strong></span>
                    <span>{t('education_level')}: <strong>{goso.education_level}</strong></span>
                    {goso.regulatory_profile && <span>{t('regulatory_profile')}: <strong>{goso.regulatory_profile}</strong></span>}
                    {goso.ruleset_version && <span>{t('ruleset_version')}: <strong>{goso.ruleset_version}</strong></span>}
                </div>
                {(goso.violations || []).map((item, index) => <div key={index} style={{ marginTop: 8, color: '#9b1c1c', fontSize: 13 }}>
                    ⚠️ {item.message || item.title || item.reason}: {item.actual !== undefined ? `${item.actual} / ${item.required}` : ''}
                </div>)}
                <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>{goso.source}</div>
            </CompactSection>
        )}
        {audit && (
            <CompactSection
                title={t('automatic_quality_audit')}
                toggleLabel={compactToggleLabel}
                accent={audit.passed ? '#2e7d32' : '#e67e22'}
                defaultOpen={false}
            >
                <div style={{ fontSize: 13, color: '#566', marginBottom: 10 }}>{audit.engine}</div>
                <strong style={{ color: audit.passed ? '#1b5e20' : '#9a5b00' }}>
                    {audit.passed
                        ? t('quality_passed')
                        : t('quality_needs_corrections')}
                </strong>
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10, fontSize: 13 }}>
                    {verification.nominal_semester_load !== undefined && verification.allowed_semester_load && (
                        <span>{t('semester_load_band')}: <b>{verification.nominal_semester_load} ({verification.allowed_semester_load.min}–{verification.allowed_semester_load.max})</b></span>
                    )}
                    <span>{t('structural_prerequisites')}: <b>{audit.structural_foundations?.length || 0}</b></span>
                    <span>{t('los_without_real_course')}: <b>{audit.lo_without_real_course?.length || 0}</b></span>
                    <span>{t('weak_courses')}: <b>{audit.weak_courses?.length || 0}</b></span>
                    <span>{t('semester_misplacements')}: <b>{audit.semester_misplacements?.length || 0}</b></span>
                </div>
                {(audit.lo_without_real_course || []).slice(0, 5).map(row => <div key={row.lo_code} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                    ⚠ {row.lo_code}: {row.lo_text} · {t('best_real_link')} {Math.round((row.max_real_course_score || 0) * 100)}%
                </div>)}
                {(audit.weak_courses || []).slice(0, 5).map(row => <div key={row.course_id} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                    ⚠ {row.title} · {t('semester')} {row.semester} · {t('ai_short')} {Math.round((row.model_score || 0) * 100)}% · {t('epvo_short')} {Math.round((row.epvo_expert_score || 0) * 100)}%
                </div>)}
                {(audit.semester_misplacements || []).slice(0, 5).map(row => <div key={`semester-${row.course_id}`} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                    ⚠ {row.title}: {t('semester')} {row.semester} → {t('recommended')} {row.recommended_semester}
                </div>)}
            </CompactSection>
        )}
    </>
}
