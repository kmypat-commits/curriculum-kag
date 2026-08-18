import CompactSection from './CompactSection'

/** Compact, language-aware verification cards kept outside the page controller. */
export default function PlanVerificationPanels({ currentPlan, localText, compactToggleLabel, t }) {
    const verification = currentPlan?.metrics?.verification
    if (!verification) return null
    const goso = verification.goso_compliance
    const audit = verification.pedagogical_audit
    return <>
        {goso?.applicable && (
            <CompactSection
                title={localText('Соответствие ГОСО Республики Казахстан', 'Қазақстан Республикасының МЖМБС сәйкестігі', 'Kazakhstan state-standard compliance')}
                toggleLabel={compactToggleLabel}
                accent={goso.compliant ? '#2e7d32' : '#c62828'}
                defaultOpen={false}
            >
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 13 }}>
                    <span>{localText('Статус', 'Күйі', 'Status')}: <strong>{goso.compliant ? localText('соответствует', 'сәйкес', 'compliant') : localText('есть нарушения', 'бұзушылықтар бар', 'violations found')}</strong></span>
                    <span>{localText('Обязательные кредиты', 'Міндетті кредиттер', 'Mandatory credits')}: <strong>{goso.mandatory_credits}</strong></span>
                    <span>{localText('Уровень', 'Деңгей', 'Level')}: <strong>{goso.education_level}</strong></span>
                </div>
                {(goso.violations || []).map((item, index) => <div key={index} style={{ marginTop: 8, color: '#9b1c1c', fontSize: 13 }}>
                    ⚠️ {item.title || item.reason}: {item.actual !== undefined ? `${item.actual} / ${item.required}` : ''}
                </div>)}
                <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>{goso.source}</div>
            </CompactSection>
        )}
        {audit && (
            <CompactSection
                title={localText('Автоматическая проверка качества плана', 'Жоспар сапасын автоматты тексеру', 'Automatic curriculum quality audit')}
                toggleLabel={compactToggleLabel}
                accent={audit.passed ? '#2e7d32' : '#e67e22'}
                defaultOpen={false}
            >
                <div style={{ fontSize: 13, color: '#566', marginBottom: 10 }}>{audit.engine}</div>
                <strong style={{ color: audit.passed ? '#1b5e20' : '#9a5b00' }}>
                    {audit.passed
                        ? localText('План прошёл проверку связей с РО и последовательности семестров.', 'Жоспар ОН байланыстары мен семестр реттілігі тексерісінен өтті.', 'The plan passed LO alignment and semester sequencing checks.')
                        : localText('План требует исправлений до экспертного утверждения.', 'Жоспар сарапшылық бекітуге дейін түзетуді қажет етеді.', 'The plan needs corrections before expert approval.')}
                </strong>
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10, fontSize: 13 }}>
                    <span>{localText('Структурные пререквизиты', 'Құрылымдық пререквизиттер', 'Structural prerequisites')}: <b>{audit.structural_foundations?.length || 0}</b></span>
                    <span>{localText('РО без реальной дисциплины', 'Нақты пәнсіз ОН', 'LOs without a real course')}: <b>{audit.lo_without_real_course?.length || 0}</b></span>
                    <span>{localText('Слабые дисциплины', 'Әлсіз пәндер', 'Weak courses')}: <b>{audit.weak_courses?.length || 0}</b></span>
                    <span>{localText('Неуместный семестр', 'Орынсыз семестр', 'Semester misplacements')}: <b>{audit.semester_misplacements?.length || 0}</b></span>
                </div>
                {(audit.lo_without_real_course || []).slice(0, 5).map(row => <div key={row.lo_code} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                    ⚠ {row.lo_code}: {row.lo_text} · {localText('лучшая реальная связь', 'ең жақсы нақты байланыс', 'best real link')} {Math.round((row.max_real_course_score || 0) * 100)}%
                </div>)}
                {(audit.weak_courses || []).slice(0, 5).map(row => <div key={row.course_id} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                    ⚠ {row.title} · {t('semester')} {row.semester} · AI {Math.round((row.model_score || 0) * 100)}% · EPVO {Math.round((row.epvo_expert_score || 0) * 100)}%
                </div>)}
                {(audit.semester_misplacements || []).slice(0, 5).map(row => <div key={`semester-${row.course_id}`} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                    ⚠ {row.title}: {t('semester')} {row.semester} → {localText('рекомендуется', 'ұсынылады', 'recommended')} {row.recommended_semester}
                </div>)}
            </CompactSection>
        )}
    </>
}
