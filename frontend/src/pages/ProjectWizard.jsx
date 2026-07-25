import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'

export default function ProjectWizard() {
    const { user } = useAuth()
    const { t, language } = useLanguage()
    const navigate = useNavigate()
    const localText = (ru, kz, en) => language === 'kz' ? kz : language === 'en' ? en : ru
    const [step, setStep] = useState(1)
    const [goalSuggestions, setGoalSuggestions] = useState([])
    const [loSuggestions, setLoSuggestions] = useState([])
    const [directions, setDirections] = useState([])
    const [groups, setGroups] = useState([])
    const [secondaryDirections, setSecondaryDirections] = useState([])
    const [secondaryGroups, setSecondaryGroups] = useState([])
    const [educationAreas, setEducationAreas] = useState([])
    const [submitError, setSubmitError] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [formData, setFormData] = useState({
        name: '',
        goal: '',
        domains: ['', ''],
        learning_outcomes: [''],
        constraints: {
            jurisdiction: 'KZ',
            education_level: 'bachelor',
            master_track: 'scientific_pedagogical',
            education_area: '',
            direction_code: '',
            group_code: '',
            secondary_education_area: '',
            secondary_direction_code: '',
            secondary_group_code: '',
            program_type: 'standard',
            instruction_language: 'ru',
            duration_years: 4,
            total_semesters: 8,
            total_credits: 240,
            credit_tolerance: 3,
            max_credits_per_semester: 30,
            min_domain1_percent: 40,
            min_domain2_percent: 40,
            allow_new_courses: true,
            max_new_courses: 5
        }
    })

    const handleChange = (field, value) => {
        setFormData({ ...formData, [field]: value })
    }

    const handleConstraintChange = (field, value) => {
        setFormData({
            ...formData,
            constraints: { ...formData.constraints, [field]: value }
        })
    }

    const addLO = () => {
        setFormData({
            ...formData,
            learning_outcomes: [...formData.learning_outcomes, '']
        })
    }

    const updateLO = (index, value) => {
        const newLOs = [...formData.learning_outcomes]
        newLOs[index] = value
        setFormData({ ...formData, learning_outcomes: newLOs })
    }

    const removeLO = (index) => {
        setFormData({
            ...formData,
            learning_outcomes: formData.learning_outcomes.filter((_, i) => i !== index)
        })
    }

    const changeEducationLevel = (level) => {
        const defaults = level === 'master'
            ? { duration_years: 2, total_semesters: 4, total_credits: 120 }
            : level === 'doctorate'
                ? { duration_years: 3, total_semesters: 6, total_credits: 180 }
                : { duration_years: 4, total_semesters: 8, total_credits: 240 }
        setFormData(current => ({
            ...current,
            constraints: {
                ...current.constraints,
                ...defaults,
                education_level: level,
                education_area: '', direction_code: '', group_code: '',
                secondary_education_area: '', secondary_direction_code: '', secondary_group_code: '',
            },
            domains: ['', ''],
        }))
    }

    const chooseDirection = (secondary, code) => {
        const source = secondary ? secondaryDirections : directions
        const selected = source.find(item => item.code === code)
        const constraintField = secondary ? 'secondary_direction_code' : 'direction_code'
        const groupField = secondary ? 'secondary_group_code' : 'group_code'
        const domainIndex = secondary ? 1 : 0
        setFormData(current => {
            const domains = [...current.domains]
            domains[domainIndex] = selected?.title || code
            return {
                ...current,
                domains,
                constraints: { ...current.constraints, [constraintField]: code, [groupField]: '' },
            }
        })
    }

    const context = () => ({
        name: formData.name.trim() || t('new_program'),
        domain1: formData.domains[0].trim() || t('primary_domain'),
        domain2: formData.domains[1].trim() || t('secondary_domain')
    })

    useEffect(() => {
        axios.get('/api/epvo/education-areas', { params: { education_level: formData.constraints.education_level, language } })
            .then(response => setEducationAreas(response.data)).catch(() => setEducationAreas([]))
    }, [formData.constraints.education_level, language])

    useEffect(() => {
        const area = formData.constraints.education_area
        if (!area) { setDirections([]); return }
        axios.get('/api/epvo/directions', { params: { education_level: formData.constraints.education_level, education_area: area, language } })
            .then(response => setDirections(response.data)).catch(() => setDirections([]))
    }, [formData.constraints.education_level, formData.constraints.education_area, language])

    useEffect(() => {
        const code = formData.constraints.direction_code
        if (!code) { setGroups([]); return }
        axios.get('/api/epvo/groups', { params: { direction_code: code, language } }).then(response => setGroups(response.data)).catch(() => setGroups([]))
    }, [formData.constraints.direction_code, language])

    useEffect(() => {
        const area = formData.constraints.secondary_education_area
        if (!area) { setSecondaryDirections([]); return }
        axios.get('/api/epvo/directions', { params: { education_level: formData.constraints.education_level, education_area: area, language } })
            .then(response => setSecondaryDirections(response.data)).catch(() => setSecondaryDirections([]))
    }, [formData.constraints.education_level, formData.constraints.secondary_education_area, language])

    useEffect(() => {
        const code = formData.constraints.secondary_direction_code
        if (!code) { setSecondaryGroups([]); return }
        axios.get('/api/epvo/groups', { params: { direction_code: code, language } }).then(response => setSecondaryGroups(response.data)).catch(() => setSecondaryGroups([]))
    }, [formData.constraints.secondary_direction_code, language])

    const suggestGoals = () => {
        const { name, domain1, domain2 } = context()
        setGoalSuggestions(['goal_template_recommended', 'goal_template_practical', 'goal_template_research'].map(key =>
            t(key).replace('{name}', name).replaceAll('{domain1}', domain1).replaceAll('{domain2}', domain2)
        ))
    }

    const suggestLOs = () => {
        const { domain1, domain2 } = context()
        setLoSuggestions([1, 2, 3, 4, 5, 6].map(number =>
            t(`lo_template_${number}`).replaceAll('{domain1}', domain1).replaceAll('{domain2}', domain2)
        ))
    }

    const addSuggestedLO = (suggestion) => {
        if (formData.learning_outcomes.includes(suggestion)) return
        const clean = formData.learning_outcomes.filter(lo => lo.trim())
        setFormData({ ...formData, learning_outcomes: [...clean, suggestion] })
    }

    const addAllSuggestedLOs = () => {
        const existing = formData.learning_outcomes.filter(lo => lo.trim())
        setFormData({ ...formData, learning_outcomes: [...new Set([...existing, ...loSuggestions])] })
    }

    const isInterdisciplinary = ['interdisciplinary', 'joint'].includes(formData.constraints.program_type)
    const secondaryScopeValid = !isInterdisciplinary || Boolean(
        formData.constraints.secondary_education_area?.trim() &&
        formData.constraints.secondary_direction_code?.trim() &&
        formData.constraints.secondary_group_code?.trim() &&
        formData.constraints.secondary_direction_code !== formData.constraints.direction_code &&
        formData.constraints.secondary_group_code !== formData.constraints.group_code
    )

    const canContinue = step === 1
        ? Boolean(
            formData.name.trim() && formData.goal.trim() &&
            formData.constraints.education_area && formData.constraints.direction_code && formData.constraints.group_code &&
            secondaryScopeValid
        )
        : step === 2 ? formData.learning_outcomes.some(lo => lo.trim())
            : step === 3 ? Boolean(
                formData.constraints.education_level && formData.constraints.education_area.trim() &&
                formData.constraints.direction_code.trim() && formData.constraints.group_code.trim() &&
                formData.constraints.program_type && formData.constraints.instruction_language &&
                formData.constraints.total_semesters > 0 && formData.constraints.total_credits > 0 &&
                secondaryScopeValid
            ) : true

    const handleSubmit = async () => {
        if (submitting) return
        setSubmitting(true)
        setSubmitError('')
        try {
            // Map frontend data to backend model
            const payload = {
                title: formData.name,
                goal: formData.goal,
                domain1: formData.domains[0],
                domain2: formData.domains[1],
                learning_outcomes: formData.learning_outcomes
                    .filter(lo => lo.trim())
                    .map((lo, index) => ({ lo_code: `LO${index + 1}`, lo_text: lo })), // Unique LO codes
                constraints: formData.constraints
            }

            const response = await axios.post('/api/projects', payload)
            navigate(`/projects/${response.data.id}`)
        } catch (error) {
            const detail = error.response?.data?.detail
            const message = Array.isArray(detail)
                ? detail.map(item => item?.msg || String(item)).join('; ')
                : typeof detail === 'object' && detail !== null
                    ? (detail.message || JSON.stringify(detail))
                    : (detail || error.message)
            setSubmitError(`${t('error')}: ${message}`)
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <div className="workspace-page wizard-page" style={{ minHeight: '100vh', background: '#f5f7fa' }}>
            <header className="workspace-header" style={{
                background: 'white',
                borderBottom: '1px solid #e0e0e0',
                padding: '15px 0'
            }}>
                <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h1 style={{ margin: 0, fontSize: '24px', color: '#366092' }}>
                        {t('create_project')}
                    </h1>
                    <LanguageSelector />
                </div>
            </header>

            <main className="container workspace-main workspace-main-narrow" style={{ paddingTop: '30px', maxWidth: '800px' }}>
                {/* Progress */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    marginBottom: '30px'
                }}>
                    {[1, 2, 3, 4].map(s => (
                        <div key={s} style={{
                            flex: 1,
                            textAlign: 'center',
                            padding: '10px',
                            background: step >= s ? '#366092' : '#e0e0e0',
                            color: step >= s ? 'white' : '#666',
                            margin: '0 5px',
                            borderRadius: '4px'
                        }}>
                            {t('step')} {s}
                        </div>
                    ))}
                </div>

                <div className="card">
                    {/* Step 1: Basic Info */}
                    {step === 1 && (
                        <div>
                            <h2>{t('basic_info')}</h2>
                            <div className="form-group">
                                <label className="form-label">{t('program_name')} *</label>
                                <input
                                    type="text"
                                    className="form-control"
                                    value={formData.name}
                                    onChange={(e) => handleChange('name', e.target.value)}
                                    placeholder={t('program_name_example')}
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('program_goal')} *</label>
                                <textarea
                                    className="form-control"
                                    rows="4"
                                    value={formData.goal}
                                    onChange={(e) => handleChange('goal', e.target.value)}
                                    placeholder={t('program_goal_placeholder')}
                                />
                            </div>
                            <div style={{ margin: '-4px 0 18px' }}>
                                <button type="button" className="btn btn-secondary" onClick={suggestGoals} disabled={!formData.name.trim()}>
                                    ✨ {t('suggest_three_goals')}
                                </button>
                                {!formData.name.trim() && <div style={{ color: '#777', fontSize: '13px', marginTop: '6px' }}>{t('enter_name_first')}</div>}
                            </div>
                            {goalSuggestions.length > 0 && <div style={{ marginBottom: '20px' }}>
                                <h3 style={{ fontSize: '16px' }}>{t('choose_goal')}</h3>
                                {goalSuggestions.map((goal, index) => <div key={goal} style={{ border: `2px solid ${formData.goal === goal ? '#366092' : index === 0 ? '#2e7d32' : '#ddd'}`, borderRadius: '8px', padding: '12px', marginBottom: '10px', background: formData.goal === goal ? '#eef4fb' : 'white' }}>
                                    <div style={{ fontWeight: 'bold', color: index === 0 ? '#2e7d32' : '#555', marginBottom: '6px' }}>{index === 0 ? `★ ${t('recommended_best')}` : `${t('option')} ${index + 1}`}</div>
                                    <div style={{ lineHeight: 1.5 }}>{goal}</div>
                                    <button type="button" className="btn btn-primary" style={{ marginTop: '10px' }} onClick={() => handleChange('goal', goal)}>{formData.goal === goal ? t('selected') : t('select_goal')}</button>
                                </div>)}
                            </div>}
                            <h3>{t('direction_code')}</h3>
                            <p style={{ color: '#666', fontSize: 13 }}>Направления и группы ЕПВО определяют, из каких дисциплин система будет строить программу.</p>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 15 }}>
                                <div className="form-group"><label className="form-label">{localText('Страна и стандарт', 'Ел және стандарт', 'Country and standard')} *</label><select className="form-control" value={formData.constraints.jurisdiction} onChange={e => handleConstraintChange('jurisdiction', e.target.value)}><option value="KZ">{localText('Республика Казахстан — ГОСО', 'Қазақстан Республикасы — МЖМБС', 'Republic of Kazakhstan — State standard')}</option><option value="INTERNATIONAL">{localText('Международная программа', 'Халықаралық бағдарлама', 'International programme')}</option></select></div>
                                <div className="form-group"><label className="form-label">{t('education_level')} *</label><select className="form-control" value={formData.constraints.education_level} onChange={e => changeEducationLevel(e.target.value)}><option value="bachelor">{t('bachelor')}</option><option value="master">{t('master')}</option><option value="doctorate">{t('doctorate')}</option></select></div>
                                {formData.constraints.education_level === 'master' && <div className="form-group"><label className="form-label">{localText('Направление магистратуры', 'Магистратура бағыты', 'Master track')} *</label><select className="form-control" value={formData.constraints.master_track} onChange={e => handleConstraintChange('master_track', e.target.value)}><option value="scientific_pedagogical">{localText('Научно-педагогическая — 120 кредитов', 'Ғылыми-педагогикалық — 120 кредит', 'Scientific and pedagogical — 120 credits')}</option><option value="professional">{localText('Профильная', 'Бейіндік', 'Professional')}</option></select></div>}
                                <div className="form-group"><label className="form-label">{t('program_type')} *</label><select className="form-control" value={formData.constraints.program_type} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, program_type: e.target.value, secondary_education_area: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.constraints.secondary_education_area : '', secondary_direction_code: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.constraints.secondary_direction_code : '', secondary_group_code: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.constraints.secondary_group_code : '' }, domains: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.domains : [current.domains[0], ''] }))}><option value="standard">{t('standard_program')}</option><option value="interdisciplinary">{t('interdisciplinary_program')}</option><option value="joint">{t('joint_program')}</option></select></div>
                                <div className="form-group"><label className="form-label">{t('education_area')} 1 *</label><select className="form-control" value={formData.constraints.education_area} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, education_area: e.target.value, direction_code: '', group_code: '' }, domains: ['', current.domains[1]] }))}><option value="">{t('select_education_area')}</option>{educationAreas.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                <div className="form-group"><label className="form-label">{t('direction_code')} 1 *</label><select className="form-control" value={formData.constraints.direction_code} disabled={!formData.constraints.education_area} onChange={e => chooseDirection(false, e.target.value)}><option value="">{t('select_direction')}</option>{directions.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                <div className="form-group"><label className="form-label">{t('group_code')} 1 *</label><select className="form-control" value={formData.constraints.group_code} disabled={!formData.constraints.direction_code} onChange={e => handleConstraintChange('group_code', e.target.value)}><option value="">{t('select_group')}</option>{groups.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                            </div>
                            {isInterdisciplinary && <div style={{ padding: 14, border: '1px solid #d9e3ef', borderRadius: 8, background: '#f6f9fc' }}>
                                <strong>{t('secondary_epvo_scope')}</strong>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 15, marginTop: 10 }}>
                                    <div className="form-group"><label className="form-label">{t('education_area')} 2 *</label><select className="form-control" value={formData.constraints.secondary_education_area} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, secondary_education_area: e.target.value, secondary_direction_code: '', secondary_group_code: '' }, domains: [current.domains[0], ''] }))}><option value="">{t('select_education_area')}</option>{educationAreas.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                    <div className="form-group"><label className="form-label">{t('direction_code')} 2 *</label><select className="form-control" value={formData.constraints.secondary_direction_code} disabled={!formData.constraints.secondary_education_area} onChange={e => chooseDirection(true, e.target.value)}><option value="">{t('select_direction')}</option>{secondaryDirections.map(item => <option key={item.code} value={item.code} disabled={item.code === formData.constraints.direction_code}>{item.code} — {item.title}</option>)}</select></div>
                                    <div className="form-group"><label className="form-label">{t('group_code')} 2 *</label><select className="form-control" value={formData.constraints.secondary_group_code} disabled={!formData.constraints.secondary_direction_code} onChange={e => handleConstraintChange('secondary_group_code', e.target.value)}><option value="">{t('select_group')}</option>{secondaryGroups.map(item => <option key={item.code} value={item.code} disabled={item.code === formData.constraints.group_code}>{item.code} — {item.title}</option>)}</select></div>
                                </div>
                            </div>}
                        </div>
                    )}

                    {/* Step 2: Learning Outcomes */}
                    {step === 2 && (
                        <div>
                            <h2>{t('learning_outcomes')} (LO)</h2>
                            <p style={{ color: '#666', marginBottom: '20px' }}>
                                {t('add_lo_description')}
                            </p>
                            <div style={{ marginBottom: '18px' }}><button type="button" className="btn btn-secondary" onClick={suggestLOs}>✨ {t('suggest_learning_outcomes')}</button></div>
                            {loSuggestions.length > 0 && <div style={{ background: '#f6f9fc', border: '1px solid #d9e3ef', borderRadius: '8px', padding: '14px', marginBottom: '20px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', marginBottom: '10px' }}><strong>{t('suggested_learning_outcomes')}</strong><button type="button" className="btn btn-primary" onClick={addAllSuggestedLOs}>{t('add_all')}</button></div>
                                {loSuggestions.map((suggestion, index) => {
                                    const added = formData.learning_outcomes.includes(suggestion)
                                    return <div key={suggestion} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', padding: '9px 0', borderTop: index ? '1px solid #e3e9ef' : 'none' }}><span style={{ flex: 1 }}><b>LO{index + 1}.</b> {suggestion}</span><button type="button" className="btn btn-secondary" disabled={added} onClick={() => addSuggestedLO(suggestion)}>{added ? t('added') : `+ ${t('add')}`}</button></div>
                                })}
                            </div>}
                            {formData.learning_outcomes.map((lo, index) => (
                                <div key={index} style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
                                    <input
                                        type="text"
                                        className="form-control"
                                        value={lo}
                                        onChange={(e) => updateLO(index, e.target.value)}
                                        placeholder={t('lo_placeholder').replace('{number}', index + 1)}
                                    />
                                    {formData.learning_outcomes.length > 1 && (
                                        <button
                                            type="button"
                                            className="btn btn-secondary"
                                            onClick={() => removeLO(index)}
                                        >
                                            ✕
                                        </button>
                                    )}
                                </div>
                            ))}
                            <button type="button" className="btn btn-primary" onClick={addLO}>
                                + {t('add_lo')}
                            </button>
                        </div>
                    )}

                    {/* Step 3: Constraints */}
                    {step === 3 && (
                        <div>
                            <h2>{t('constraints')}</h2>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
                                <div className="form-group"><label className="form-label">{t('education_level')} *</label><select className="form-control" value={formData.constraints.education_level} onChange={e => changeEducationLevel(e.target.value)}><option value="bachelor">{t('bachelor')}</option><option value="master">{t('master')}</option><option value="doctorate">{t('doctorate')}</option></select></div>
                                <div className="form-group"><label className="form-label">{t('program_type')} *</label><select className="form-control" value={formData.constraints.program_type} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, program_type: e.target.value, secondary_education_area: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.constraints.secondary_education_area : '', secondary_direction_code: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.constraints.secondary_direction_code : '', secondary_group_code: ['interdisciplinary', 'joint'].includes(e.target.value) ? current.constraints.secondary_group_code : '' } }))}><option value="standard">{t('standard_program')}</option><option value="interdisciplinary">{t('interdisciplinary_program')}</option><option value="joint">{t('joint_program')}</option></select></div>
                                <div className="form-group"><label className="form-label">{t('education_area')} *</label><select className="form-control" value={formData.constraints.education_area} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, education_area: e.target.value, direction_code: '', group_code: '' } }))}><option value="">{t('select_education_area')}</option>{educationAreas.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                <div className="form-group"><label className="form-label">{t('direction_code')} *</label><select className="form-control" value={formData.constraints.direction_code} disabled={!formData.constraints.education_area} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, direction_code: e.target.value, group_code: '' } }))}><option value="">{t('select_direction')}</option>{directions.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                <div className="form-group"><label className="form-label">{t('group_code')} *</label><select className="form-control" value={formData.constraints.group_code} disabled={!formData.constraints.direction_code} onChange={e => handleConstraintChange('group_code', e.target.value)}><option value="">{t('select_group')}</option>{groups.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                <div className="form-group"><label className="form-label">{t('instruction_language')} *</label><select className="form-control" value={formData.constraints.instruction_language} onChange={e => handleConstraintChange('instruction_language', e.target.value)}><option value="ru">{t('lang_ru')}</option><option value="kk">{t('lang_kk')}</option><option value="en">{t('lang_en')}</option></select></div>
                            </div>
                            {isInterdisciplinary && (
                                <div style={{ marginTop: '15px', padding: '14px', border: '1px solid #d9e3ef', borderRadius: '8px', background: '#f6f9fc' }}>
                                    <h3 style={{ marginTop: 0 }}>{t('secondary_epvo_scope')}</h3>
                                    <p style={{ marginTop: 0, color: '#666', fontSize: '13px' }}>{t('secondary_epvo_scope_hint')}</p>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '15px' }}>
                                        <div className="form-group"><label className="form-label">{t('education_area')} 2 *</label><select className="form-control" value={formData.constraints.secondary_education_area} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, secondary_education_area: e.target.value, secondary_direction_code: '', secondary_group_code: '' } }))}><option value="">{t('select_education_area')}</option>{educationAreas.map(item => <option key={item.code} value={item.code}>{item.code} — {item.title}</option>)}</select></div>
                                        <div className="form-group"><label className="form-label">{t('direction_code')} 2 *</label><select className="form-control" value={formData.constraints.secondary_direction_code} disabled={!formData.constraints.secondary_education_area} onChange={e => setFormData(current => ({ ...current, constraints: { ...current.constraints, secondary_direction_code: e.target.value, secondary_group_code: '' } }))}><option value="">{t('select_direction')}</option>{secondaryDirections.map(item => <option key={item.code} value={item.code} disabled={item.code === formData.constraints.direction_code}>{item.code} — {item.title}</option>)}</select></div>
                                        <div className="form-group"><label className="form-label">{t('group_code')} 2 *</label><select className="form-control" value={formData.constraints.secondary_group_code} disabled={!formData.constraints.secondary_direction_code} onChange={e => handleConstraintChange('secondary_group_code', e.target.value)}><option value="">{t('select_group')}</option>{secondaryGroups.map(item => <option key={item.code} value={item.code} disabled={item.code === formData.constraints.group_code}>{item.code} — {item.title}</option>)}</select></div>
                                    </div>
                                    {!secondaryScopeValid && <div style={{ color: '#b71c1c', fontSize: '13px' }}>{t('secondary_scope_required')}</div>}
                                </div>
                            )}
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
                                <div className="form-group">
                                    <label className="form-label">{t('duration_years')}</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        min="1"
                                        max="6"
                                        value={Math.max(1, Math.round(formData.constraints.total_semesters / 2))}
                                        onChange={(e) => {
                                            const years = Math.max(1, parseInt(e.target.value) || 1)
                                            setFormData({
                                                ...formData,
                                                constraints: {
                                                    ...formData.constraints,
                                                    duration_years: years,
                                                    total_semesters: years * 2,
                                                    total_credits: years * 60
                                                }
                                            })
                                        }}
                                    />
                                    <div style={{ color: '#666', fontSize: '13px', marginTop: '5px' }}>
                                        {t('duration_hint')
                                            .replace('{semesters}', formData.constraints.total_semesters)
                                            .replace('{credits}', formData.constraints.total_credits)}
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('total_credits')}</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={formData.constraints.total_credits}
                                        onChange={(e) => handleConstraintChange('total_credits', parseInt(e.target.value))}
                                    />
                                    <div style={{ color: '#667085', fontSize: '12px', marginTop: '5px' }}>
                                        План должен набрать {formData.constraints.total_credits} кредитов. Допуск технического балансирования: +{formData.constraints.credit_tolerance ?? 3} кредита.
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">Допуск итоговых кредитов</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        min="0"
                                        max="10"
                                        value={formData.constraints.credit_tolerance ?? 3}
                                        onChange={(e) => handleConstraintChange('credit_tolerance', Math.max(0, parseInt(e.target.value) || 0))}
                                    />
                                    <div style={{ color: '#667085', fontSize: '12px', marginTop: '5px' }}>Для стандартной ОП обычно достаточно 3 кредитов; система стремится к точному объёму.</div>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('max_credits_semester')}</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={formData.constraints.max_credits_per_semester}
                                        onChange={(e) => handleConstraintChange('max_credits_per_semester', parseInt(e.target.value))}
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('min_domain_percent')}{isInterdisciplinary ? ' 1' : ''}</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={formData.constraints.min_domain1_percent}
                                        onChange={(e) => handleConstraintChange('min_domain1_percent', parseInt(e.target.value))}
                                    />
                                </div>
                                {isInterdisciplinary && <div className="form-group">
                                    <label className="form-label">{t('min_domain_percent')} 2</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={formData.constraints.min_domain2_percent}
                                        onChange={(e) => handleConstraintChange('min_domain2_percent', parseInt(e.target.value))}
                                    />
                                </div>}
                                {formData.constraints.allow_new_courses && <div className="form-group">
                                    <label className="form-label">{t('max_new_courses')}</label>
                                    <input
                                        type="number"
                                        className="form-control"
                                        value={formData.constraints.max_new_courses}
                                        onChange={(e) => handleConstraintChange('max_new_courses', parseInt(e.target.value))}
                                    />
                                </div>}
                            </div>
                            <div className="form-group">
                                <label style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <input
                                        type="checkbox"
                                        checked={formData.constraints.allow_new_courses}
                                        onChange={(e) => handleConstraintChange('allow_new_courses', e.target.checked)}
                                    />
                                    {t('allow_new_courses')}
                                </label>
                            </div>
                        </div>
                    )}

                    {/* Step 4: Review */}
                    {step === 4 && (
                        <div>
                            <h2>{t('review_data')}</h2>
                            <div style={{ background: '#f8f9fa', padding: '15px', borderRadius: '4px', marginBottom: '15px' }}>
                                <h3>{t('program_name')}:</h3>
                                <p>{formData.name}</p>
                                <h3>{t('domains')}:</h3>
                                <p>{formData.domains.join(', ')}</p>
                                <h3>{t('learning_outcomes')}:</h3>
                                <ul>
                                    {formData.learning_outcomes.filter(lo => lo.trim()).map((lo, i) => (
                                        <li key={i}>{lo}</li>
                                    ))}
                                </ul>
                                <h3>{t('constraints')}:</h3>
                                <p>{t('duration_years')}: {Math.round(formData.constraints.total_semesters / 2)} ({t('num_semesters')}: {formData.constraints.total_semesters}), {t('total_credits')}: {formData.constraints.total_credits}</p>
                            </div>
                        </div>
                    )}

                    {/* Navigation */}
                    {submitError && (
                        <div role="alert" style={{ marginTop: 20, padding: '12px 14px', borderRadius: 8, color: '#9b1c1c', background: '#fff1f1', border: '1px solid #fecaca' }}>
                            {submitError}
                        </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '30px' }}>
                        <button
                            className="btn btn-secondary"
                            onClick={() => step > 1 ? setStep(step - 1) : navigate('/')}
                        >
                            {step > 1 ? t('back') : t('cancel')}
                        </button>
                        {step < 4 ? (
                            <button className="btn btn-primary" disabled={!canContinue} onClick={() => setStep(step + 1)}>
                                {t('next')}
                            </button>
                        ) : (
                            <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
                                {submitting ? 'Создание…' : t('create_project')}
                            </button>
                        )}
                    </div>
                </div>
            </main>
        </div>
    )
}
