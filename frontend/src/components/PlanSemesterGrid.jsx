import React from 'react'

export default function PlanSemesterGrid({
    project, currentPlan, t, localText, localize, localizeCycle, componentLabel,
    localizedCourse, localizedCourseField, showCourseDescriptions, showSelectionDetails,
    excludedCourses, toggleCourseExclusion, matchFeedbackState, handleMatchFeedback,
}) {
    return (
                        <div className="card" data-semester-grid="legacy">
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '20px' }}>
                                {[...Array(project.constraints?.total_semesters || 8)].map((_, i) => {
                                    const semester = i + 1
                                    const courses = currentPlan?.schedule?.[semester] || []
                                    const totalCredits = courses.reduce((acc, c) => acc + (c.credits || 0), 0)
                                    const semesterLOs = currentPlan?.semester_lo_details?.[semester] || []

                                    return (
                                        <div key={semester} data-plan-semester={semester} style={{ background: '#f8f9fa', padding: '15px', borderRadius: '8px', border: '1px solid #eef2f7' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '2px solid #366092', paddingBottom: '5px', marginBottom: '10px' }}>
                                                <h4 style={{ margin: 0 }}>{t('semester')} {semester}</h4>
                                                <span style={{ fontSize: '13px', color: '#666' }}>{totalCredits} {t('credits')}</span>
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                                {courses.map((c, idx) => (
                                                    <div key={idx} style={{ background: 'white', padding: '10px', borderRadius: '4px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                        <div style={{ flex: 1 }}>
                                                            <div
                                                                style={{ fontSize: '15px', fontWeight: 'bold', color: '#17233b' }}
                                                                title={localizedCourseField(c.description_translations, c.description)}
                                                            >
                                                                {localizedCourse(c)}{c.translation_status === 'machine_reviewed' && <span title={t('ai_translation')} style={{marginLeft:5,color:'#9a5b00',fontSize:10}}>AI</span>}
                                                            </div>
                                                            {showCourseDescriptions && localizedCourseField(c.description_translations, c.description) && (
                                                                <div style={{ fontSize: '11px', color: '#777', marginTop: 3, lineHeight: 1.35 }}>
                                                                    {localizedCourseField(c.description_translations, c.description).slice(0, 220)}{localizedCourseField(c.description_translations, c.description).length > 220 ? '…' : ''}
                                                                </div>
                                                            )}
                                                            <div style={{ fontSize: '11px', color: '#666', marginTop: '2px' }}>
                                                                {c.academic_cycle && <>{localText('Цикл', 'Цикл', 'Cycle')}: <b>{localizeCycle(c.academic_cycle)}</b>{c.academic_cycle_source === 'inferred' ? ` (${localText('расчёт системы', 'жүйе есебі', 'system estimate')})` : ''}{' · '}</>}
                                                                {localText('Компонент', 'Компонент', 'Component')}: {componentLabel(c.academic_component || c.cycle_component || c.type)}
                                                                {' · '}{localText('Источник', 'Дереккөз', 'Source')}: {
                                                                    c.course_source === 'rk_mandatory' ? localText('обязательная дисциплина РК', 'ҚР міндетті пәні', 'RK mandatory course')
                                                                    : c.course_source === 'ai_confirmed' ? localText('подтверждённая замена ИИ', 'ЖИ расталған ауыстыру', 'AI-confirmed replacement')
                                                                    : c.course_source === 'bridge' ? localText('bridge-модуль', 'bridge-модуль', 'bridge module')
                                                                    : localText('репозиторий дисциплин', 'пәндер репозиторийі', 'course repository')
                                                                }
                                                                {c.course_code ? ` · ${localText('Код', 'Код', 'Code')}: ${c.course_code}` : ''}
                                                            </div>
                                                            {c.course_id && !c.protected_by_goso && (
                                                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 5, fontSize: 11, color: excludedCourses[c.course_id] ? '#b71c1c' : '#5d6470', cursor: 'pointer' }}>
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={Boolean(excludedCourses[c.course_id])}
                                                                        onChange={() => toggleCourseExclusion(c.course_id, c.title)}
                                                                    />
                                                                    {excludedCourses[c.course_id]
                                                                        ? localText('Будет убрана при перегенерации', 'Қайта құру кезінде алынады', 'Will be removed on regeneration')
                                                                        : localText('Заменить/убрать при следующей генерации', 'Келесі құруда ауыстыру/алып тастау', 'Replace/remove on next generation')}
                                                                </label>
                                                            )}
                                                            {c.protected_by_goso && (
                                                                <div style={{ marginTop: 5, fontSize: 11, color: '#1b5e20', fontWeight: 600 }}>
                                                                    🛡 {localText('Обязательная дисциплина ГОСО РК — защищена от удаления и замены', 'ҚР МЖМБС міндетті пәні — жоюдан және ауыстырудан қорғалған', 'RK mandatory course — protected from removal and replacement')}
                                                                </div>
                                                            )}
                                                            {c.why_selected && (
                                                                <details style={{ marginTop: 6, fontSize: 11, color: '#586174' }}>
                                                                    <summary style={{ cursor: 'pointer', color: '#366092', fontWeight: 600 }}>
                                                                        {localText('Почему выбрана?', 'Неге таңдалды?', 'Why selected?')}
                                                                    </summary>
                                                                    <div style={{ marginTop: 5, lineHeight: 1.45 }}>
                                                                        <div>{localize(c.why_selected.selection_reason_translations || c.why_selected.selection_reason)}</div>
                                                                        <div>{localize(c.why_selected.semester_reason_translations || c.why_selected.semester_reason)}</div>
                                                                        <div style={{ marginTop: 5, padding: '6px 8px', background: '#f5f7fb', borderRadius: 6 }}>
                                                                            {localText(
                                                                                'Проценты относятся к связи одной дисциплины с одним LO. ИИ — прогноз модели по текстам. ЕПВО — поддержка этой же связи в экспертных данных ЕПВО. Они не складываются; итог берётся по наиболее надёжному подтверждению.',
                                                                                'Пайыздар бір пән мен бір LO байланысына жатады. ЖИ — мәтіндер бойынша модель болжамы. ЖООББ — сол байланыстың сараптамалық деректердегі қолдауы. Олар қосылмайды.',
                                                                                'Percentages describe one course-to-LO link. AI is the text-model estimate; EPVO is expert support for the same link. They are not added.'
                                                                            )}
                                                                        </div>
                                                                        {c.why_selected.top_lo_matches?.length > 0 && (
                                                                            <div style={{ marginTop: 4 }}>
                                                                        <div style={{ fontWeight: 600, marginBottom: 3 }}>
                                                                            {localText('Связи с результатами обучения:', 'Оқу нәтижелерімен байланыс:', 'Learning-outcome links:')}
                                                                        </div>
                                                                        <div style={{ marginBottom: 5, color: '#607d8b', fontSize: 11 }}>
                                                                            {localText(
                                                                                'Как читать: “итог” — насколько дисциплина реально закрывает этот LO в плане; “ИИ” — прогноз модели по текстам; “ЕПВО” — похожая экспертная оценка из базы ЕПВО. Это три разных признака одной связи, они не суммируются.',
                                                                                'Оқу тәртібі: “қорытынды” — пән осы LO-ны жоспарда қаншалықты жабады; “ЖИ” — мәтіндер бойынша модель болжамы; “ЕПВО” — ЕПВО базасындағы ұқсас сараптамалық баға. Бұлар бір байланыстың үш бөлек белгісі, қосылмайды.',
                                                                                'How to read: effective is the final plan link strength; AI is the text-model prediction; EPVO is similar expert evidence from EPVO. These are separate signals for one link, not a sum.'
                                                                            )}
                                                                        </div>
                                                                        {c.why_selected.top_lo_matches.map(lo => (
                                                                                    <span key={lo.lo_code} title={lo.lo_text} style={{ display: 'inline-block', marginRight: 5, marginTop: 3 }}>
                                                                                        <span style={{
                                                                                            display: 'inline-block',
                                                                                            padding: '2px 6px',
                                                                                            borderRadius: 999,
                                                                                            background: '#eef4ff',
                                                                                            color: '#244b78'
                                                                                        }}>
                                                                                            {lo.lo_code} · {localText('итог', 'қорытынды', 'effective')}: {Math.round((lo.effective_score ?? lo.score ?? 0) * 100)}%
                                                                                            {lo.ai_score != null && (
                                                                                                <small style={{ marginLeft: 5, color: '#455a64' }}>
                                                                                                    {localText('ИИ', 'ЖИ', 'AI')} {Math.round((lo.ai_score || 0) * 100)}%
                                                                                                </small>
                                                                                            )}
                                                                                            {lo.expert_score != null && (
                                                                                                <small style={{ marginLeft: 5, color: '#6a4f00' }}>
                                                                                                    {localText('ЕПВО', 'ЕПВО', 'EPVO')} {Math.round((lo.expert_score || 0) * 100)}%
                                                                                                </small>
                                                                                            )}
                                                                                            {lo.source === 'bridge_target' && (
                                                                                                <small style={{ marginLeft: 5, color: '#7b1fa2' }}>
                                                                                                    {localText('bridge', 'bridge', 'bridge')}
                                                                                                </small>
                                                                                            )}
                                                                                            {lo.weak_evidence && (
                                                                                                <small style={{ marginLeft: 5, color: '#b26a00' }}>
                                                                                                    {localText('слабая связь', 'әлсіз байланыс', 'weak link')}
                                                                                                </small>
                                                                                            )}
                                                                                            {(matchFeedbackState[`${c.course_id}:${lo.lo_id}`] || lo.expert_feedback?.verdict) && (
                                                                                                <small style={{ marginLeft: 5, color: '#1b5e20' }}>✓ {matchFeedbackState[`${c.course_id}:${lo.lo_id}`] || lo.expert_feedback?.verdict}</small>
                                                                                            )}
                                                                                        </span>
                                                                                        <div style={{ marginTop: 2, maxWidth: 340, color: '#607d8b', fontSize: 11 }}>
                                                                                            {localText(
                                                                                                'Итог — итоговая сила связи этой дисциплины с этим LO. ИИ — прогноз модели по текстам. ЕПВО — воспроизведённая экспертная оценка из базы. Они не складываются.',
                                                                                                'Қорытынды — осы пәннің осы ОН-мен байланыс күші. ЖИ — мәтіндер бойынша модель болжамы. ЕПВО — базадағы сараптамалық бағаны қалпына келтіру. Олар қосылмайды.',
                                                                                                'Effective is the final strength for this course→LO link. AI is the text model prediction. EPVO is reconstructed expert evidence. They are not added together.'
                                                                                            )}
                                                                                        </div>
                                                                                        <div style={{ marginTop: 2, maxWidth: 310, color: '#4f5d6b' }}>
                                                                                            <b>{lo.lo_code}:</b> {lo.lo_text}
                                                                                        </div>
                                                                                        {lo.explanation && (
                                                                                            <div style={{ marginTop: 3, maxWidth: 360, color: '#37474f', fontSize: 11, background: '#fffde7', border: '1px solid #fff59d', borderRadius: 6, padding: '5px 7px' }}>
                                                                                                {localize(lo.explanation_translations || lo.explanation)}
                                                                                            </div>
                                                                                        )}
                                                                                        {lo.lo_id && c.course_id && (
                                                                                            <span style={{ display: 'inline-flex', gap: 3, marginLeft: 4 }}>
                                                                                                {['confirmed', 'weak', 'incorrect'].map(verdict => {
                                                                                                    const key = `${c.course_id}:${lo.lo_id}`
                                                                                                    const current = matchFeedbackState[key] || lo.expert_feedback?.verdict
                                                                                                    return (
                                                                                                        <button
                                                                                                            key={verdict}
                                                                                                            type="button"
                                                                                                            disabled={matchFeedbackState[key] === 'saving'}
                                                                                                            onClick={() => handleMatchFeedback(c.course_id, lo.lo_id, verdict)}
                                                                                                            style={{
                                                                                                                border: '1px solid #d6e0ee',
                                                                                                                background: current === verdict ? '#dff5e6' : '#fff',
                                                                                                                color: current === verdict ? '#1b5e20' : '#4b5b6b',
                                                                                                                borderRadius: 999,
                                                                                                                padding: '1px 5px',
                                                                                                                fontSize: 10,
                                                                                                                cursor: 'pointer'
                                                                                                            }}
                                                                                                        >
                                                                                                            {t(`feedback_${verdict}`)}
                                                                                                        </button>
                                                                                                    )
                                                                                                })}
                                                                                            </span>
                                                                                        )}
                                                                                    </span>
                                                                                ))}
                                                                            </div>
                                                                        )}
                                                                        {(c.plan_requisites?.prerequisites?.length > 0 || c.plan_requisites?.postrequisites?.length > 0) && (
                                                                            <div style={{ marginTop: 8, padding: '7px 9px', background: '#f8fbff', border: '1px solid #dbe8f6', borderRadius: 8 }}>
                                                                                <div style={{ fontWeight: 700, color: '#244b78', marginBottom: 4 }}>
                                                                                    {localText('Пре- и постреквизиты в этом плане', 'Осы жоспардағы пре- және постреквизиттер', 'Pre- and post-requisites in this plan')}
                                                                                </div>
                                                                                <div style={{ color: '#607d8b', marginBottom: 5 }}>
                                                                                    {localText(
                                                                                        'Показываются только дисциплины, которые реально есть в текущем варианте плана.',
                                                                                        'Тек ағымдағы жоспар нұсқасында бар пәндер көрсетіледі.',
                                                                                        'Only courses that are actually present in the current plan variant are shown.'
                                                                                    )}
                                                                                </div>
                                                                                <div style={{ display: 'grid', gap: 5 }}>
                                                                                    <div>
                                                                                        <b>{localText('До этой дисциплины:', 'Осы пәнге дейін:', 'Before this course:')}</b>{' '}
                                                                                        {c.plan_requisites?.prerequisites?.length > 0
                                                                                            ? c.plan_requisites.prerequisites.map(item => (
                                                                                                <span key={`pre-${item.course_id}`} title={`${localText('Семестр', 'Семестр', 'Semester')} ${item.semester} · ${item.credits} ${localText('кредитов', 'кредит', 'credits')}`} style={{ display: 'inline-block', margin: '2px 4px 2px 0', padding: '2px 6px', borderRadius: 999, background: '#eef4ff', color: '#244b78' }}>
                                                                                                    {localText('Сем.', 'Сем.', 'Sem.')} {item.semester}: {localizedCourse(item)}
                                                                                                </span>
                                                                                            ))
                                                                                            : <span style={{ color: '#8a96a3' }}>{localText('в плане нет обязательных предшествующих дисциплин', 'жоспарда міндетті алдыңғы пәндер жоқ', 'no required earlier courses in the plan')}</span>
                                                                                        }
                                                                                    </div>
                                                                                    <div>
                                                                                        <b>{localText('После неё опираются:', 'Одан кейін сүйенетін пәндер:', 'Courses that depend on it:')}</b>{' '}
                                                                                        {c.plan_requisites?.postrequisites?.length > 0
                                                                                            ? c.plan_requisites.postrequisites.map(item => (
                                                                                                <span key={`post-${item.course_id}`} title={`${localText('Семестр', 'Семестр', 'Semester')} ${item.semester} · ${item.credits} ${localText('кредитов', 'кредит', 'credits')}`} style={{ display: 'inline-block', margin: '2px 4px 2px 0', padding: '2px 6px', borderRadius: 999, background: '#eefaf3', color: '#1b5e20' }}>
                                                                                                    {localText('Сем.', 'Сем.', 'Sem.')} {item.semester}: {localizedCourse(item)}
                                                                                                </span>
                                                                                            ))
                                                                                            : <span style={{ color: '#8a96a3' }}>{localText('в текущем плане нет дисциплин, которые явно требуют её как пререквизит', 'ағымдағы жоспарда оны пререквизит ретінде талап ететін пәндер жоқ', 'no later courses explicitly require it in this plan')}</span>
                                                                                        }
                                                                                    </div>
                                                                                </div>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                </details>
                                                            )}
                                                        </div>
                                                        <div style={{ fontWeight: 'bold', color: '#366092', minWidth: '30px', textAlign: 'right' }}>{c.credits}</div>
                                                    </div>
                                                ))}
                                                {courses.length === 0 && <p style={{ fontSize: '13px', color: '#999', textAlign: 'center' }}>-</p>}
                                            </div>
                                            <div style={{ marginTop: '15px', paddingTop: '10px', borderTop: '1px dashed #ccc', fontSize: '12px', color: '#555' }}>
                                                <strong>{t('semester_lo')}:</strong>
                                                {semesterLOs.length > 0 ? <div className="semester-lo-list">
                                                    {semesterLOs.map(lo => <span
                                                        className="semester-lo-chip"
                                                        key={lo.code}
                                                        tabIndex="0"
                                                        title={`${lo.text}\n${t('evidence_courses')}: ${lo.courses.join(', ')}${lo.score == null ? '' : `\n${t('connection_strength')}: ${Math.round(lo.score * 100)}%`}`}
                                                    >{lo.code}<span className="semester-lo-tooltip"><strong>{lo.code} · {t(lo.kind === 'course' ? 'course_outcome' : 'programme_outcome')}</strong>{lo.text}<small>{t('evidence_courses')}: {lo.courses.join(', ')}</small>{lo.score != null && <small>{t('connection_strength')}: {Math.round(lo.score * 100)}%</small>}</span></span>)}
                                                </div> : <div className="semester-lo-empty">{t('no_semester_lo_evidence')}</div>}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
    )
}
