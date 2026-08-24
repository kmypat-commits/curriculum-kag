import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'
import CompactSection from '../components/CompactSection'
import PlanBuildProgress from '../components/PlanBuildProgress'
import PlanSemesterGrid from '../components/PlanSemesterGrid'
import PlanQualityPanel from '../components/PlanQualityPanel'
import PlanVerificationPanels from '../components/PlanVerificationPanels'
import { useNotifications } from '../contexts/NotificationContext'
import {
    alreadyRunningText,
    localizeQualityEvidenceText,
    longRunningHint,
    planBuildElapsedLabel,
    planBuildStageDetail,
    planBuildStageLabel,
} from '../utils/planBuilderPresentation'

export default function PlanBuilder() {
    const { notify } = useNotifications()
    const { id } = useParams()
    const [searchParams] = useSearchParams()
    const { t, localize, localizeCycle, localizeDomain, language } = useLanguage()
    const [project, setProject] = useState(null)
    const [loading, setLoading] = useState(true)
    const [building, setBuilding] = useState(false)
    const [buildProgress, setBuildProgress] = useState(0)
    const [buildStatus, setBuildStatus] = useState({ state: 'idle', stage: 'idle', progress: 0 })
    const [applyingQuality, setApplyingQuality] = useState(false)
    const [recomputingMatches, setRecomputingMatches] = useState(false)
    const [qualityNotice, setQualityNotice] = useState(null)
    const [activationNotice, setActivationNotice] = useState(null)
    const [buildNotice, setBuildNotice] = useState(null)
    const [changeReport, setChangeReport] = useState(null)
    const [variants, setVariants] = useState(null)
    const [activeVariant, setActiveVariant] = useState('A')
    const [buildVariants, setBuildVariants] = useState('all')
    const [showCourseDescriptions, setShowCourseDescriptions] = useState(false)
    const [showSelectionDetails, setShowSelectionDetails] = useState(false)
    const [matchFeedbackState, setMatchFeedbackState] = useState({})
    const [bridgePreview, setBridgePreview] = useState(null)
    const [loadingBridgePreview, setLoadingBridgePreview] = useState(false)
    const [replacingBridge, setReplacingBridge] = useState(null)
    const [replacingAllBridges, setReplacingAllBridges] = useState(false)
    const [selectedBridgeReplacements, setSelectedBridgeReplacements] = useState({})
    const [loCoverageSources, setLoCoverageSources] = useState(null)
    const [loadingLoCoverageSources, setLoadingLoCoverageSources] = useState(false)
    const [requiresRegeneration, setRequiresRegeneration] = useState(false)
    const [excludedCourses, setExcludedCourses] = useState({})
    const [aiBridgeCandidates, setAiBridgeCandidates] = useState({})
    const [loadingAiBridge, setLoadingAiBridge] = useState(null)
    const [confirmingAiBridge, setConfirmingAiBridge] = useState(null)
    const [courseReplacementPreviews, setCourseReplacementPreviews] = useState({})
    const [loadingCourseReplacement, setLoadingCourseReplacement] = useState(null)
    const [applyingCourseReplacement, setApplyingCourseReplacement] = useState(null)
    const buildPollTimer = useRef(null)

    const localizedCourseField = (translations, fallback = '') => {
        const translated = translations && typeof translations === 'object'
            ? localize(translations)
            : translations
        return String(translated || fallback || '').trim()
    }
    const localizedCourse = (course = {}) => {
        const translations = course.title_translations || (course.title_ru || course.title_kk || course.title_en ? { ru: course.title_ru, kk: course.title_kk || course.title_kz, en: course.title_en } : null)
        return localizedCourseField(translations, course.title)
    }

    // These labels bypass legacy mojibake entries in the translation bundle.
    const cycleLabel = language === 'en' ? 'Cycle' : language === 'kk' ? 'Пәндер циклі' : 'Цикл'
    const cycleEstimateLabel = language === 'en' ? 'system estimate' : language === 'kk' ? 'жүйе есебі' : 'расчёт системы'
    const componentLabelText = language === 'en' ? 'Component' : language === 'kk' ? 'Компоненті' : 'Компонент'
    const sourceLabel = language === 'en' ? 'Source' : language === 'kk' ? 'Дереккөз' : 'Источник'

    const errorMessage = (err) => {
        const detail = err?.response?.data?.detail
        if (Array.isArray(detail)) {
            return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join('; ')
        }
        if (detail && typeof detail === 'object') {
            return detail.message_by_language?.[language] || detail.message || detail.error || JSON.stringify(detail)
        }
        return detail || err?.message || localText('Неизвестная ошибка', 'Белгісіз қате', 'Unknown error')
    }

    const localizeQualityEvidence = (text = '') => localizeQualityEvidenceText(text, language)

    const epvoSyncMessage = (sync) => {
        if (!sync) return null
        return t('epvo_sync_summary')
            .replace('{created}', sync.created ?? 0)
            .replace('{linked}', sync.linked ?? 0)
            .replace('{scope}', sync.group_code || sync.direction_code || sync.scope || t('all_domains'))
    }

    const componentLabel = (value = '') => {
        const cycle = localizeCycle(value)
        if (cycle !== String(value || '').trim()) return cycle
        const normalized = String(value).trim().toLowerCase()
        if (['bd', 'бд', 'basic', 'basic disciplines', 'базовые дисциплины'].includes(normalized)) return localizeCycle('БД')
        if (['pd', 'пд', 'profile', 'profile disciplines', 'профильные дисциплины'].includes(normalized)) return localizeCycle('ПД')
        if (['ged', 'ood', 'оод', 'general', 'general education'].includes(normalized)) return localizeCycle('ООД')
        if (['elective', 'elective component', 'компонент по выбору'].includes(normalized)) return t('elective')
        if (['university', 'university component', 'вузовский компонент'].includes(normalized)) return t('university')
        return t('mandatory')
    }

    const buildStageLabel = (stage = 'idle') => planBuildStageLabel(stage, language)
    const buildStageDetail = () => planBuildStageDetail(buildStatus, language)
    const buildElapsedLabel = () => planBuildElapsedLabel(buildStatus, language)
    const buildAlreadyRunningText = () => alreadyRunningText(language)
    const buildLongRunningHint = () => longRunningHint(language)

    const localText = (ru, kk, en) => language === 'kk' ? kk : language === 'en' ? en : ru
    const compactToggleLabel = localText('Открыть / свернуть', 'Ашу / жинау', 'Open / collapse')
    const epvoApplied = searchParams.get('epvoApplied') === '1'

    const pollBuildStatus = async (versionId) => {
        const status = await axios.get(`/api/planner/${versionId}/build-status`)
        setBuildStatus(status.data)
        setBuildProgress(status.data.progress || 0)
        if (status.data.change_report) setChangeReport(status.data.change_report)
        return status.data
    }

    const stopBuildStatusPolling = () => {
        if (buildPollTimer.current) {
            window.clearTimeout(buildPollTimer.current)
            buildPollTimer.current = null
        }
    }

    const startBuildStatusPolling = (versionId) => {
        stopBuildStatusPolling()
        const tick = async () => {
            try {
                const status = await pollBuildStatus(versionId)
                if (status.state === 'running') {
                    setBuilding(true)
                    buildPollTimer.current = window.setTimeout(tick, 1200)
                    return
                }
                setBuilding(false)
                if (status.state === 'complete') await fetchVariants(versionId)
            } catch (_) {
                buildPollTimer.current = window.setTimeout(tick, 3000)
            }
        }
        tick()
    }

    useEffect(() => {
        fetchProjectData()
        return stopBuildStatusPolling
    }, [id])

    const fetchProjectData = async () => {
        try {
            setLoading(true)
            const projRes = await axios.get(`/api/projects/${id}`)
            setProject(projRes.data)
            setExcludedCourses(Object.fromEntries(
                (projRes.data?.constraints?.excluded_course_ids || []).map(courseId => [courseId, true])
            ))

            if (projRes.data.latest_version?.id) {
                await fetchVariants(projRes.data.latest_version.id)
                startBuildStatusPolling(projRes.data.latest_version.id)
            }
        } catch (err) {
            console.error('Error fetching project:', err)
        } finally {
            setLoading(false)
        }
    }

    const fetchVariants = async (
        versionId,
        includeDescriptions = showCourseDescriptions,
        includeExplanations = showSelectionDetails,
    ) => {
        try {
            const variantsRes = await axios.get(`/api/planner/${versionId}/variants`, {
                params: {
                    include_descriptions: includeDescriptions,
                    include_explanations: includeExplanations,
                },
            })
            if (variantsRes.data && variantsRes.data.length > 0) {
                const variantsObj = {}
                variantsRes.data.forEach(v => {
                    variantsObj[v.variant_type] = v
                })
                setVariants(variantsObj)
                const currentActive = activeVariant
                const preferred = variantsObj[currentActive] ? variantsObj[currentActive] : [...variantsRes.data].sort((a, b) =>
                    (b.metrics?.min_lo_coverage || 0) - (a.metrics?.min_lo_coverage || 0) ||
                    (b.metrics?.lo_coverage_percentage || 0) - (a.metrics?.lo_coverage_percentage || 0)
                )[0]
                if (preferred?.variant_type) setActiveVariant(preferred.variant_type)
            }
        } catch (err) {
            console.error('Error fetching variants:', err)
        }
    }

    const handleShowCourseDescriptionsChange = async (checked) => {
        setShowCourseDescriptions(checked)
        const versionId = project?.latest_version?.id
        if (checked && versionId) await fetchVariants(versionId, checked)
    }

    const handleShowSelectionDetailsChange = async (checked) => {
        setShowSelectionDetails(checked)
        const versionId = project?.latest_version?.id
        if (versionId) await fetchVariants(versionId, showCourseDescriptions, checked)
    }

    const handleBuild = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return

        try {
            setBuilding(true)
            setBuildNotice(null)
            setChangeReport(null)
            setBuildProgress(5)
            setBuildStatus({ state: 'running', stage: 'matching', progress: 5 })
            const buildRequest = axios.post(`/api/planner/${versionId}/build`, { variants: buildVariants === 'all' ? ['A', 'B', 'C'] : [buildVariants] })
            startBuildStatusPolling(versionId)
            const buildResponse = await buildRequest
            await fetchVariants(versionId)
            setRequiresRegeneration(false)
            setBuildProgress(100)
            setBuildStatus({ state: 'complete', stage: 'complete', progress: 100, change_report: buildResponse.data?.change_report })
            setChangeReport(buildResponse.data?.change_report || null)
            const message = epvoSyncMessage(buildResponse.data?.epvo_repository)
            if (message) setBuildNotice({ type: 'success', text: message })
        } catch (err) {
            if (err.authExpired || err.response?.status === 401) {
                return
            } else if (err.response?.status === 409) {
                await pollBuildStatus(versionId)
                setBuildNotice({ type: 'error', text: buildAlreadyRunningText() })
            } else {
                const message = errorMessage(err)
                setBuildStatus({ state: 'failed', stage: 'failed', progress: 0, error: message })
                notify(t('build_error') + ': ' + message)
            }
        } finally {
            setBuilding(false)
        }
    }

    const missingVariants = ['A', 'B', 'C'].filter(item => !variants?.[item])
    const handleBuildMissing = async () => {
        if (!missingVariants.length || building) return
        setBuildVariants(missingVariants.join(','))
        try {
            setBuilding(true)
            setBuildNotice(null)
            setBuildStatus({ state: 'running', stage: 'matching', progress: 5 })
            const response = await axios.post(`/api/planner/${project.latest_version.id}/build`, { variants: missingVariants })
            await fetchVariants(project.latest_version.id)
            setBuildStatus({ state: 'complete', stage: 'complete', progress: 100, change_report: response.data?.change_report })
        } catch (err) {
                notify(t('build_error') + ': ' + errorMessage(err))
        } finally { setBuilding(false) }
    }

    const handleToggleActive = async (planId) => {
        try {
            setActivationNotice(null)
            await axios.post(`/api/planner/${planId}/toggle-active`)
            await fetchVariants(project.latest_version.id)
            setProject(current => ({
                ...current,
                latest_version: { ...current.latest_version, status: 'active' }
            }))
            setActivationNotice({ type: 'success', text: t('activation_success') })
        } catch (err) {
            setActivationNotice({ type: 'error', text: t('activate_error') + ': ' + (errorMessage(err)) })
        }
    }

    const handleApplyQualityImprovements = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        try {
            setApplyingQuality(true)
            setQualityNotice(null)
            setBuildNotice(null)
            setChangeReport(null)
            setBuilding(true)
            setBuildProgress(5)
            setBuildStatus({ state: 'running', stage: 'epvo_repository', progress: 5 })
            const applyResponse = await axios.post(`/api/planner/${versionId}/apply-quality-improvements`)
            if (!applyResponse.data?.requires_rebuild) {
                await fetchVariants(versionId)
                setBuildProgress(100)
                setBuildStatus({ state: 'complete', stage: 'complete', progress: 100 })
                const protectedCount = applyResponse.data?.protected_regulatory_courses || 0
                const message = protectedCount
                    ? `${t('quality_improvements_applied')} ${protectedCount} ГОСО-компонентов защищены; пересборка не требуется.`
                    : `${t('quality_improvements_applied')} Пересборка не требуется.`
                setQualityNotice({ type: 'success', text: message })
                return
            }
            const progressTimer = window.setInterval(async () => {
                try { await pollBuildStatus(versionId) } catch (_) { /* build request handles errors */ }
            }, 1200)
            let buildResponse
            try {
                buildResponse = await axios.post(`/api/planner/${versionId}/build`)
            } finally {
                window.clearInterval(progressTimer)
            }
            await fetchVariants(versionId)
            setBuildProgress(100)
            setBuildStatus({ state: 'complete', stage: 'complete', progress: 100, change_report: buildResponse.data?.change_report })
            setChangeReport(buildResponse.data?.change_report || null)
            const syncMessage = epvoSyncMessage(buildResponse.data?.epvo_repository)
            setQualityNotice({ type: 'success', text: syncMessage ? `${t('quality_improvements_applied')} ${syncMessage}` : t('quality_improvements_applied') })
        } catch (err) {
            setQualityNotice({ type: 'error', text: t('quality_improvements_error') + ': ' + (errorMessage(err)) })
        } finally {
            setBuilding(false)
            window.setTimeout(() => setBuildProgress(0), 600)
            setApplyingQuality(false)
        }
    }

    const handleRecomputeMatches = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        try {
            setRecomputingMatches(true)
            setBuildNotice(null)
            setBuildProgress(5)
            setBuildStatus({ state: 'running', stage: 'scoring', progress: 5 })
            const progressTimer = window.setInterval(async () => {
                try { await pollBuildStatus(versionId) } catch (_) { /* recompute request handles errors */ }
            }, 1200)
            let response
            try {
                response = await axios.post(`/api/planner/${versionId}/recompute-matches`)
            } finally {
                window.clearInterval(progressTimer)
            }
            await fetchVariants(versionId)
            setBuildProgress(100)
            setBuildStatus({ state: 'complete', stage: 'complete', progress: 100 })
            setBuildNotice({
                type: 'success',
                text: localText(
                    `Связи дисциплина–LO пересчитаны: ${response.data?.total_matches || 0}. Теперь можно перестроить варианты.`,
                    `Пән–LO байланыстары қайта есептелді: ${response.data?.total_matches || 0}. Енді нұсқаларды қайта құруға болады.`,
                    `Course–LO links recomputed: ${response.data?.total_matches || 0}. You can now rebuild variants.`,
                )
            })
        } catch (err) {
            setBuildStatus({ state: 'failed', stage: 'failed', progress: 0, error: errorMessage(err) })
            setBuildNotice({ type: 'error', text: localText('Не удалось пересчитать связи', 'Байланыстарды қайта есептеу мүмкін болмады', 'Could not recompute links') + ': ' + (errorMessage(err)) })
        } finally {
            setRecomputingMatches(false)
            window.setTimeout(() => setBuildProgress(0), 600)
        }
    }

    const loadBridgePreview = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setLoadingBridgePreview(true)
        try {
            const response = await axios.get(`/api/planner/${versionId}/bridge-replacement-preview`, { params: { variant: activeVariant } })
            setBridgePreview(response.data)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось получить preview замены bridge', 'Bridge ауыстыру preview алу мүмкін болмады', 'Could not load bridge replacement preview') + ': ' + (errorMessage(err)) })
        } finally {
            setLoadingBridgePreview(false)
        }
    }

    const applyBridgeReplacement = async (bridgeItemId, courseId) => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        const key = `${bridgeItemId}:${courseId}`
        setReplacingBridge(key)
        try {
            const response = await axios.post(`/api/planner/${versionId}/bridge-replacement-apply`, {
                bridge_item_id: bridgeItemId,
                course_id: courseId,
            })
            setBuildNotice({ type: 'success', text: response.data?.message || localText('Дисциплина добавлена в план.', 'Пән жоспарға қосылды.', 'Course added to the plan.') })
            setBridgePreview(current => current ? {
                ...current,
                suggestions: (current.suggestions || []).filter(row => row.bridge_item_id !== bridgeItemId),
            } : current)
            setSelectedBridgeReplacements(current => {
                const next = { ...current }
                delete next[bridgeItemId]
                return next
            })
            setRequiresRegeneration(Boolean(response.data?.requires_regeneration))
            await fetchVariants(versionId)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось заменить bridge-модуль', 'Bridge-модульді ауыстыру мүмкін болмады', 'Could not replace bridge module') + ': ' + (errorMessage(err)) })
        } finally {
            setReplacingBridge(null)
        }
    }

    const applyAllBridgeReplacements = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setReplacingAllBridges(true)
        try {
            const selected = Object.entries(selectedBridgeReplacements).map(([bridgeItemId, courseId]) => ({
                bridge_item_id: Number(bridgeItemId), course_id: Number(courseId),
            }))
            const response = await axios.post(`/api/planner/${versionId}/bridge-replacement-apply-all`, {
                variant: activeVariant,
                ...(selected.length ? { selected_replacements: selected } : {}),
            })
            setBuildNotice({ type: response.data?.replaced_count > 0 ? 'success' : 'info', text: response.data?.message })
            setRequiresRegeneration(Boolean(response.data?.requires_regeneration))
            const replacedIds = new Set((response.data?.replacements || []).map(row => row.bridge_item_id))
            setBridgePreview(current => current ? {
                ...current,
                suggestions: (current.suggestions || []).filter(row => !replacedIds.has(row.bridge_item_id)),
            } : current)
            setSelectedBridgeReplacements({})
            await fetchVariants(versionId)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось массово заменить bridge-модули', 'Bridge-модульдерді жаппай ауыстыру мүмкін болмады', 'Could not replace bridge modules') + ': ' + (errorMessage(err)) })
        } finally {
            setReplacingAllBridges(false)
        }
    }

    const selectMediumBridgeReplacements = () => {
        const selected = {}
        for (const row of bridgePreview?.suggestions || []) {
            const candidate = (row.candidates || []).find(c => c.quality_level === 'medium' || c.medium_candidate)
            if (candidate) selected[row.bridge_item_id] = candidate.course_id
        }
        setSelectedBridgeReplacements(selected)
        setBuildNotice({
            type: Object.keys(selected).length ? 'success' : 'info',
            text: Object.keys(selected).length
                ? localText(`Выбрано средних замен: ${Object.keys(selected).length}. Проверьте список и нажмите подтверждение.`, `Орташа ауыстырулар таңдалды: ${Object.keys(selected).length}. Тізімді тексеріп, растаңыз.`, `Selected medium replacements: ${Object.keys(selected).length}. Review and confirm.`)
                : localText('Средних замен пока нет.', 'Орташа ауыстырулар жоқ.', 'No medium replacements available.'),
        })
    }

    const loadAiBridgeCandidates = async (bridgeItemId) => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setLoadingAiBridge(bridgeItemId)
        try {
            const response = await axios.get(`/api/planner/${versionId}/bridge-ai-candidates`, { params: { bridge_item_id: bridgeItemId } })
            setAiBridgeCandidates(current => ({ ...current, [bridgeItemId]: response.data }))
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось подобрать дисциплины через ИИ', 'ЖИ арқылы пәндерді таңдау мүмкін болмады', 'Could not generate AI course candidates') + ': ' + (errorMessage(err)) })
        } finally {
            setLoadingAiBridge(null)
        }
    }

    const confirmAiBridgeCandidate = async (bridgeItemId, candidate) => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        const key = `${bridgeItemId}:${candidate.candidate_id}`
        setConfirmingAiBridge(key)
        try {
            const response = await axios.post(`/api/planner/${versionId}/bridge-ai-replacement-apply`, {
                bridge_item_id: bridgeItemId,
                candidate,
            })
            setBuildNotice({ type: 'success', text: response.data?.message })
            setRequiresRegeneration(true)
            setBridgePreview(null)
            setAiBridgeCandidates(current => {
                const next = { ...current }
                delete next[bridgeItemId]
                return next
            })
            await fetchVariants(versionId)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось подтвердить дисциплину', 'Пәнді растау мүмкін болмады', 'Could not confirm the course') + ': ' + (errorMessage(err)) })
        } finally {
            setConfirmingAiBridge(null)
        }
    }

    const toggleCourseExclusion = async (courseId, title) => {
        const versionId = project?.latest_version?.id
        if (!versionId || !courseId) return
        const excluded = !excludedCourses[courseId]
        setExcludedCourses(current => ({ ...current, [courseId]: excluded }))
        try {
            const response = await axios.post(`/api/planner/${versionId}/course-exclusions`, {
                course_id: courseId,
                excluded,
            })
            setRequiresRegeneration(Boolean(response.data?.requires_regeneration))
            setBuildNotice({ type: 'success', text: response.data?.message || title })
        } catch (err) {
            setExcludedCourses(current => ({ ...current, [courseId]: !excluded }))
            setBuildNotice({ type: 'error', text: localText('Не удалось изменить исключение дисциплины', 'Пәнді алып тастау белгісін өзгерту мүмкін болмады', 'Could not update course exclusion') + ': ' + (errorMessage(err)) })
        }
    }

    const confirmSuspiciousCourse = async (courseId, title) => {
        const versionId = project?.latest_version?.id
        if (!versionId || !courseId) return
        try {
            const response = await axios.post(`/api/planner/${versionId}/confirm-suspicious-course`, {
                course_id: courseId,
                reason: 'expert_confirmed_in_planner',
            })
            setExcludedCourses(current => ({ ...current, [courseId]: false }))
            setBuildNotice({ type: 'success', text: response.data?.message || `${title}: подтверждено экспертом` })
            await fetchVariants(versionId)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось подтвердить дисциплину', 'Пәнді растау мүмкін болмады', 'Could not confirm the course') + ': ' + (errorMessage(err)) })
        }
    }

    const loadCourseReplacements = async courseId => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setLoadingCourseReplacement(courseId)
        try {
            const response = await axios.get(`/api/planner/${versionId}/course-replacement-preview`, {
                params: { course_id: courseId, variant: activeVariant },
            })
            setCourseReplacementPreviews(current => ({ ...current, [courseId]: response.data }))
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось подобрать замены', 'Ауыстыруларды таңдау мүмкін болмады', 'Could not find replacements') + ': ' + (errorMessage(err)) })
        } finally {
            setLoadingCourseReplacement(null)
        }
    }

    const loadAllVisibleCourseReplacements = async () => {
        const versionId = project?.latest_version?.id
        const visible = (currentPlan?.suspicious_courses || []).slice(0, 6).filter(row => row.course_id)
        if (!versionId || !visible.length) return
        setLoadingCourseReplacement('all')
        try {
            const results = await Promise.allSettled(visible.map(row =>
                axios.get(`/api/planner/${versionId}/course-replacement-preview`, {
                    params: { course_id: row.course_id, variant: activeVariant },
                }).then(response => [row.course_id, response.data])
            ))
            const next = {}
            let ok = 0
            for (const result of results) {
                if (result.status === 'fulfilled') {
                    const [courseId, data] = result.value
                    next[courseId] = data
                    ok += 1
                }
            }
            setCourseReplacementPreviews(current => ({ ...current, ...next }))
            setBuildNotice({
                type: ok ? 'success' : 'error',
                text: ok
                    ? localText(`Подобраны замены для ${ok} дисциплин.`, `${ok} пән үшін ауыстырулар таңдалды.`, `Loaded replacements for ${ok} courses.`)
                    : localText('Не удалось подобрать замены для видимых дисциплин.', 'Көрінетін пәндер үшін ауыстыру табылмады.', 'Could not load replacements for visible courses.'),
            })
        } finally {
            setLoadingCourseReplacement(null)
        }
    }

    const applyCourseReplacement = async (courseId, replacementCourseId) => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        const key = `${courseId}:${replacementCourseId}`
        setApplyingCourseReplacement(key)
        try {
            const response = await axios.post(`/api/planner/${versionId}/course-replacement-apply`, {
                course_id: courseId, replacement_course_id: replacementCourseId, variant: activeVariant,
            })
            setBuildNotice({ type: 'success', text: response.data?.message })
            setRequiresRegeneration(true)
            setCourseReplacementPreviews(current => {
                const next = { ...current }
                delete next[courseId]
                return next
            })
            await fetchVariants(versionId)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось подтвердить замену', 'Ауыстыруды растау мүмкін болмады', 'Could not confirm replacement') + ': ' + (errorMessage(err)) })
        } finally {
            setApplyingCourseReplacement(null)
        }
    }

    const loadLoCoverageSources = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        setLoadingLoCoverageSources(true)
        try {
            const response = await axios.get(`/api/planner/${versionId}/lo-coverage-sources`, { params: { variant: activeVariant } })
            setLoCoverageSources(response.data)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('Не удалось получить источники покрытия LO', 'LO қамту көздерін алу мүмкін болмады', 'Could not load LO coverage sources') + ': ' + (errorMessage(err)) })
        } finally {
            setLoadingLoCoverageSources(false)
        }
    }

    const handleMatchFeedback = async (courseId, loId, verdict) => {
        const versionId = project?.latest_version?.id
        if (!versionId || !courseId || !loId) return
        const key = `${courseId}:${loId}`
        setMatchFeedbackState(prev => ({ ...prev, [key]: 'saving' }))
        try {
            const correctedScore = verdict === 'confirmed' ? 1.0 : verdict === 'weak' ? 0.5 : 0.0
            await axios.post('/api/kag/match-feedback', {
                project_version_id: versionId,
                course_id: courseId,
                lo_id: loId,
                verdict,
                corrected_score: correctedScore,
            })
            setMatchFeedbackState(prev => ({ ...prev, [key]: verdict }))
        } catch (err) {
            setMatchFeedbackState(prev => ({ ...prev, [key]: 'error' }))
            setBuildNotice({ type: 'error', text: localText('Не удалось сохранить экспертную оценку', 'Сарапшы бағасын сақтау мүмкін болмады', 'Could not save expert feedback') + ': ' + (errorMessage(err)) })
        }
    }

    if (loading) return <LoadingSpinner />

    const currentPlan = variants ? variants[activeVariant] : null
    const currentPlanCanActivate = Boolean(currentPlan?.plan_id && !currentPlan?.is_active)
    const currentPlanHasHardViolations = Number(
        (currentPlan?.metrics?.verification || currentPlan?.verification || {}).hard_violation_count || 0
    ) > 0
    const duplicateVariantGroups = Object.values(variants || {})
        .filter(item => item && Array.isArray(item.duplicate_variants) && item.duplicate_variants.length > 1)
        .map(item => item.duplicate_variants.join('/'))
        .filter((value, index, values) => values.indexOf(value) === index)

    return (
        <div className="workspace-page planner-page" style={{ minHeight: '100vh', background: '#f5f7fa' }}>
            <header className="workspace-header" style={{ background: 'white', borderBottom: '1px solid #e0e0e0', padding: '15px 0' }}>
                <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                        <Link to={`/projects/${id}`} style={{ textDecoration: 'none', color: '#666' }}>← {t('open')}</Link>
                        <h1 style={{ margin: 0, fontSize: '24px', color: '#366092' }}>{t('plan_builder')}</h1>
                        <span style={{ fontSize: '18px', fontWeight: 'bold', color: '#666', marginLeft: '20px' }}>({t('total_credits')}: {project?.constraints?.total_credits || 0})</span>
                    </div>
                    <div style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
                        <LanguageSelector />
                        <label style={{ fontSize: 12, color: '#667085' }}>
                            {language === 'ru' ? 'Строить' : language === 'kk' ? 'Құру' : 'Build'}
                            <select value={buildVariants} onChange={event => setBuildVariants(event.target.value)} disabled={building} style={{ marginLeft: 6, padding: '7px 8px', borderRadius: 6 }}>
                                <option value="all">A/B/C</option><option value="A">A</option><option value="B">B</option><option value="C">C</option>
                            </select>
                        </label>
                        <button
                            className="btn btn-primary"
                            onClick={handleBuild}
                            disabled={building}
                        >
                            {building ? `${t('building_plan')} ${buildProgress}%` : '✨ ' + t('generate_variants')}
                        </button>
                        {missingVariants.length > 0 && variants && (
                            <button className="btn btn-secondary" onClick={handleBuildMissing} disabled={building}>
                                {localText('Построить отсутствующие: ' + missingVariants.join(', '), 'Жетпейтін нұсқаларды құру: ' + missingVariants.join(', '), 'Build missing: ' + missingVariants.join(', '))}
                            </button>
                        )}
                        <button
                            className="btn btn-secondary"
                            onClick={handleRecomputeMatches}
                            disabled={building || recomputingMatches}
                        >
                            {recomputingMatches ? `${buildProgress}%` : localText('Пересчитать LO-связи', 'LO байланыстарын қайта есептеу', 'Recompute LO links')}
                        </button>
                    </div>
                </div>
            </header>

            <main className="container workspace-main" style={{ paddingTop: '30px' }}>
                {epvoApplied && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #366092' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div>
                                <strong>{localText('EPVO-кандидаты добавлены', 'ЕПВО кандидаттары қосылды', 'EPVO candidates added')}</strong>
                                <div style={{ color: '#667', fontSize: 13, marginTop: 4 }}>
                                    {localText('Нажмите “Построить варианты”, чтобы A/B/C использовали новые дисциплины.', 'Жаңа пәндер A/B/C нұсқаларында қолданылуы үшін “Нұсқаларды құру” түймесін басыңыз.', 'Click “Build variants” so A/B/C can use the new courses.')}
                                </div>
                            </div>
                            <button className="btn btn-primary" onClick={handleBuild}>{t('generate_variants')}</button>
                        </div>
                    </div>
                )}
                {requiresRegeneration && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #ef6c00', background: '#fffaf2' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div>
                                <strong>{localText('Есть изменения для следующей генерации', 'Келесі құру үшін өзгерістер бар', 'Changes are ready for the next generation')}</strong>
                                <div style={{ color: '#6d4c41', fontSize: 13, marginTop: 4 }}>
                                    {localText('Система учтёт замены bridge и отмеченные исключения, затем заново рассчитает A/B/C, кредиты, РО и пререквизиты.', 'Жүйе bridge ауыстыруларын және белгіленген алып тастауларды ескеріп, A/B/C, кредиттер, ОН және пререквизиттерді қайта есептейді.', 'The system will apply bridge replacements and exclusions, then recalculate A/B/C, credits, LOs, and prerequisites.')}
                                </div>
                            </div>
                            <button className="btn btn-primary" onClick={handleBuild}>
                                {localText('Перегенерировать A/B/C', 'A/B/C қайта құру', 'Regenerate A/B/C')}
                            </button>
                        </div>
                    </div>
                )}
                <PlanBuildProgress
                    active={building || buildStatus.state === 'running'}
                    progress={buildProgress}
                    status={buildStatus}
                    title={t('building_plan')}
                    stageLabel={buildStageLabel}
                    stageDetail={buildStageDetail()}
                    elapsedLabel={buildElapsedLabel()}
                    longRunningHint={buildLongRunningHint()}
                />
                {changeReport?.available && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #7b1fa2' }}>
                        <h3 style={{ marginTop: 0 }}>{localText('Что изменилось после перестройки', 'Қайта құрудан кейін не өзгерді', 'What changed after rebuild')}</h3>
                        <div className="quick-grid">
                            <div><b>{localText('Кредиты', 'Кредиттер', 'Credits')}</b><br />{changeReport.credits_delta > 0 ? '+' : ''}{changeReport.credits_delta}</div>
                            <div><b>{localText('Bridge-модули', 'Bridge-модульдер', 'Bridge modules')}</b><br />{changeReport.bridges_delta > 0 ? '+' : ''}{changeReport.bridges_delta}</div>
                            <div><b>{localText('Минимальное покрытие РО', 'ОН ең төменгі қамтылуы', 'Minimum LO coverage')}</b><br />{changeReport.min_lo_delta == null ? '—' : `${changeReport.min_lo_delta > 0 ? '+' : ''}${Math.round(changeReport.min_lo_delta * 100)}%`}</div>
                            <div><b>{localText('Качество', 'Сапа', 'Quality')}</b><br />{String(changeReport.quality_before)} → {String(changeReport.quality_after)}</div>
                        </div>
                        <p style={{ color: '#667', fontSize: 13, marginTop: 10 }}>
                            {localText('Добавлено', 'Қосылды', 'Added')}: {changeReport.added_count}; {localText('удалено', 'жойылды', 'removed')}: {changeReport.removed_count}; hard: {changeReport.hard_before} → {changeReport.hard_after}.
                        </p>
                        {(changeReport.added_titles_sample?.length > 0 || changeReport.removed_titles_sample?.length > 0) && (
                            <details style={{ marginTop: 8 }}>
                                <summary style={{ cursor: 'pointer', color: '#366092', fontWeight: 600 }}>{localText('Показать примеры изменений', 'Өзгерістер мысалдарын көрсету', 'Show change examples')}</summary>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8, fontSize: 12 }}>
                                    <div><b>{localText('Добавлено', 'Қосылды', 'Added')}</b>{(changeReport.added_titles_sample || []).map((title, index) => <div key={`a-${index}`}>+ {title}</div>)}</div>
                                    <div><b>{localText('Удалено', 'Жойылды', 'Removed')}</b>{(changeReport.removed_titles_sample || []).map((title, index) => <div key={`r-${index}`}>− {title}</div>)}</div>
                                </div>
                            </details>
                        )}
                    </div>
                )}
                {!variants ? (
                    <div className="card" style={{ textAlign: 'center', padding: '60px' }}>
                        <h3>{t('no_projects')}</h3>
                        <p style={{ color: '#666' }}>{t('generate_variants')}</p>
                        <button className="btn btn-primary" onClick={handleBuild} disabled={building} style={{ marginTop: '20px' }}>
                            {building ? `${t('building_plan')} ${buildProgress}%` : t('generate_variants')}
                        </button>
                    </div>
                ) : (
                    <div>
                        {duplicateVariantGroups.length > 0 && (
                            <div style={{ marginBottom: 16, padding: '12px 16px', borderRadius: 10, background: '#fff8e1', border: '1px solid #f1c40f', color: '#6d4c00' }}>
                                <b>{localText('Внимание: варианты совпадают', 'Назар аударыңыз: нұсқалар бірдей', 'Warning: variants are identical')}</b>
                                <div style={{ marginTop: 5, fontSize: 13 }}>
                                    {localText(
                                        `Сохранённые варианты ${duplicateVariantGroups.join(', ')} имеют одинаковый состав дисциплин. Это не разные альтернативы. Перестройте только эти варианты после изменения ограничений или состава ЕПВО.`,
                                        `Сақталған ${duplicateVariantGroups.join(', ')} нұсқаларының пәндер құрамы бірдей. Бұл әртүрлі балама емес. Шектеулерді немесе ЕПВО құрамын өзгерткеннен кейін осы нұсқаларды қайта құрыңыз.`,
                                        `Saved variants ${duplicateVariantGroups.join(', ')} have the same course composition. They are not distinct alternatives. Rebuild these variants after changing the EPVO scope or constraints.`
                                    )}
                                </div>
                            </div>
                        )}
                        <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
                            {['A', 'B', 'C'].map(v => (
                                <button
                                    key={v}
                                    onClick={() => setActiveVariant(v)}
                                    style={{
                                        padding: '12px 24px',
                                        background: activeVariant === v ? '#366092' : 'white',
                                        color: activeVariant === v ? 'white' : '#666',
                                        border: '1px solid #e0e0e0',
                                        borderRadius: '4px',
                                        cursor: 'pointer',
                                        fontWeight: 'bold'
                                    }}
                                >
                                    {t('variant')} {v} {v === 'A' ? t('variant_a_desc') : v === 'B' ? t('variant_b_desc') : t('variant_c_desc')}
                                    {variants?.[v]?.is_active && (
                                        <span style={{
                                            marginLeft: 8,
                                            padding: '2px 7px',
                                            borderRadius: 999,
                                            background: activeVariant === v ? 'rgba(255,255,255,0.22)' : '#e8f5e9',
                                            color: activeVariant === v ? 'white' : '#1b5e20',
                                            fontSize: 11,
                                        }}>
                                            {t('active')}
                                        </span>
                                    )}
                                </button>
                            ))}
                        </div>

                        <div style={{ marginBottom: '20px', textAlign: 'right' }}>
                            <button
                                onClick={() => handleToggleActive(currentPlan.plan_id)}
                                className={currentPlan.is_active ? "btn btn-secondary" : "btn btn-primary"}
                                style={{ padding: '10px 30px' }}
                                disabled={!currentPlanCanActivate}
                            >
                                {currentPlan.is_active ? t('deactivate') : t('activate')}
                            </button>
                            <div style={{ marginTop: '8px', color: '#666', fontSize: '13px' }}>
                                {currentPlan.is_active
                                    ? t('active_plan_hint')
                                    : currentPlanHasHardViolations
                                        ? t('activate_plan_with_warnings_hint')
                                        : t('activate_plan_hint')}
                            </div>
                            {activationNotice && (
                                <div style={{
                                    marginTop: '10px', padding: '10px 12px', borderRadius: '7px', textAlign: 'left',
                                    background: activationNotice.type === 'success' ? '#e8f5e9' : '#ffebee',
                                    color: activationNotice.type === 'success' ? '#1b5e20' : '#b71c1c'
                                }}>
                                    {activationNotice.text}
                                </div>
                            )}
                        </div>

                        <div style={{ marginBottom: '14px', display: 'flex', justifyContent: 'flex-end', gap: 16, flexWrap: 'wrap' }}>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: '#4f5d6b', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={showCourseDescriptions}
                                    onChange={(event) => handleShowCourseDescriptionsChange(event.target.checked)}
                                />
                                {localText(
                                    '\u041f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0442\u044c \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d',
                                    '\u041f\u04d9\u043d \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430\u043b\u0430\u0440\u044b\u043d \u043a\u04e9\u0440\u0441\u0435\u0442\u0443',
                                    'Show course descriptions',
                                )}
                            </label>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: '#4f5d6b', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={showSelectionDetails}
                                    onChange={(event) => handleShowSelectionDetailsChange(event.target.checked)}
                                />
                                {localText(
                                    'Показывать подробные обоснования выбора',
                                    'Таңдаудың толық негіздемесін көрсету',
                                    'Show detailed selection reasons',
                                )}
                            </label>
                        </div>

                        {buildNotice && (
                            <div style={{
                                marginBottom: '20px', padding: '10px 12px', borderRadius: '7px',
                                background: buildNotice.type === 'success' ? '#e8f5e9' : '#ffebee',
                                color: buildNotice.type === 'success' ? '#1b5e20' : '#b71c1c'
                            }}>
                                {buildNotice.text}
                            </div>
                        )}

                        <PlanQualityPanel
                            activeVariant={activeVariant}
                            aiBridgeCandidates={aiBridgeCandidates}
                            applyAllBridgeReplacements={applyAllBridgeReplacements}
                            applyBridgeReplacement={applyBridgeReplacement}
                            applyCourseReplacement={applyCourseReplacement}
                            applyingCourseReplacement={applyingCourseReplacement}
                            applyingQuality={applyingQuality}
                            bridgePreview={bridgePreview}
                            building={building}
                            compactToggleLabel={compactToggleLabel}
                            confirmAiBridgeCandidate={confirmAiBridgeCandidate}
                            confirmSuspiciousCourse={confirmSuspiciousCourse}
                            confirmingAiBridge={confirmingAiBridge}
                            courseReplacementPreviews={courseReplacementPreviews}
                            currentPlan={currentPlan}
                            currentPlanHasHardViolations={currentPlanHasHardViolations}
                            excludedCourses={excludedCourses}
                            handleApplyQualityImprovements={handleApplyQualityImprovements}
                            handleBuild={handleBuild}
                            handleMatchFeedback={handleMatchFeedback}
                            id={id}
                            loCoverageSources={loCoverageSources}
                            loadAiBridgeCandidates={loadAiBridgeCandidates}
                            loadAllVisibleCourseReplacements={loadAllVisibleCourseReplacements}
                            loadBridgePreview={loadBridgePreview}
                            loadCourseReplacements={loadCourseReplacements}
                            loadLoCoverageSources={loadLoCoverageSources}
                            loadingAiBridge={loadingAiBridge}
                            loadingBridgePreview={loadingBridgePreview}
                            loadingCourseReplacement={loadingCourseReplacement}
                            loadingLoCoverageSources={loadingLoCoverageSources}
                            localText={localText}
                            localize={localize}
                            localizeDomain={localizeDomain}
                            localizedCourseField={localizedCourseField}
                            matchFeedbackState={matchFeedbackState}
                            replacingAllBridges={replacingAllBridges}
                            replacingBridge={replacingBridge}
                            requiresRegeneration={requiresRegeneration}
                            selectMediumBridgeReplacements={selectMediumBridgeReplacements}
                            selectedBridgeReplacements={selectedBridgeReplacements}
                            setSelectedBridgeReplacements={setSelectedBridgeReplacements}
                            t={t}
                            toggleCourseExclusion={toggleCourseExclusion}
                        />
                        <PlanVerificationPanels currentPlan={currentPlan} localText={localText} compactToggleLabel={compactToggleLabel} t={t} />
                        {currentPlan?.metrics?.optimizer && (
                            <CompactSection title={t('optimizer')} toggleLabel={compactToggleLabel} accent={'#3949ab'} defaultOpen={false}>
                                <strong>{currentPlan.metrics.optimizer.name}</strong>
                                {currentPlan.metrics.optimizer.selection_method === 'nsga2' && (
                                    <span style={{ marginLeft: '12px', color: '#555' }}>
                                        {t('optimizer_parameters')
                                            .replace('{population}', currentPlan.metrics.optimizer.population)
                                            .replace('{generations}', currentPlan.metrics.optimizer.generations)}
                                    </span>
                                )}
                            </CompactSection>
                        )}
                        {currentPlan?.metrics?.international_quality && (
                            <CompactSection title={t('international_quality')} toggleLabel={compactToggleLabel} subtitle={'OBE / ABET-style continuous improvement / CDIO integrated curriculum / Tuning competences'} accent={currentPlan.metrics.international_quality.passed ? '#2e7d32' : '#e67e22'} defaultOpen={false}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '12px' }}>
                                    <div>
                                        <p style={{ margin: '6px 0 0', color: '#666', fontSize: '14px' }}>
                                            OBE / ABET-style continuous improvement / CDIO integrated curriculum / Tuning competences
                                        </p>
                                    </div>
                                    <div style={{ fontSize: '28px', fontWeight: 'bold', color: currentPlan.metrics.international_quality.passed ? '#2e7d32' : '#e67e22' }}>
                                        {currentPlan.metrics.international_quality.score}%
                                    </div>
                                </div>
                                <div style={{
                                    marginBottom: '14px',
                                    padding: '10px 12px',
                                    borderRadius: '9px',
                                    background: currentPlan.metrics.international_quality.passed ? '#eef8f0' : '#fff8e1',
                                    border: `1px solid ${currentPlan.metrics.international_quality.passed ? '#c8e6c9' : '#ffe082'}`,
                                    color: '#344054',
                                    fontSize: '13px',
                                    lineHeight: 1.45
                                }}>
                                    <strong>
                                        {currentPlan.metrics.international_quality.passed
                                            ? localText('План уже прошёл международный чек-лист.', 'Жоспар халықаралық чек-листен өтті.', 'The plan already passed the international checklist.')
                                            : localText('План требует автоматического исправления.', 'Жоспар автоматты түзетуді қажет етеді.', 'The plan needs automatic repair.')}
                                    </strong>{' '}
                                    {localText(
                                        'Система проверяет кредиты, нагрузку по семестрам, пререквизиты, покрытие результатов обучения, предметную релевантность и защиту обязательных ГОСО-компонентов. Кнопка ниже исключает только заменяемые слабые дисциплины, защищает ГОСО и запускает пересборку A/B/C, если это действительно нужно.',
                                        'Жүйе кредиттерді, семестр жүктемесін, пререквизиттерді, оқу нәтижелерін қамтуды, пәндік сәйкестікті және міндетті МЖМБС компоненттерін қорғауды тексереді. Төмендегі батырма тек ауыстыруға болатын әлсіз пәндерді алып тастайды, МЖМБС-ты қорғайды және қажет болса A/B/C қайта құрады.',
                                        'The system checks credits, semester load, prerequisites, LO coverage, domain relevance, and protected regulatory components. The button excludes only replaceable weak courses, protects RK mandatory courses, and rebuilds A/B/C only when needed.'
                                    )}
                                </div>
                                {(!currentPlan.metrics.international_quality.passed || currentPlan.metrics.international_quality.checks?.some(check => !check.passed)) && (
                                    <button
                                        className="btn btn-primary"
                                        onClick={handleApplyQualityImprovements}
                                        disabled={applyingQuality || building}
                                        style={{ marginBottom: '14px' }}
                                    >
                                        {applyingQuality ? t('applying_quality_improvements') : `✨ ${t('apply_all_quality_improvements')}`}
                                    </button>
                                )}
                                {qualityNotice && (
                                    <div style={{
                                        marginBottom: '14px', padding: '10px 12px', borderRadius: '7px',
                                        background: qualityNotice.type === 'success' ? '#e8f5e9' : '#ffebee',
                                        color: qualityNotice.type === 'success' ? '#1b5e20' : '#b71c1c'
                                    }}>
                                        {qualityNotice.text}
                                    </div>
                                )}
                                {currentPlan.metrics.international_quality.relevance && (
                                    <div style={{
                                        marginBottom: '14px',
                                        padding: '12px',
                                        borderRadius: '10px',
                                        background: '#f5f7fb',
                                        border: '1px solid #dfe7f3',
                                        fontSize: '13px',
                                        color: '#344054'
                                    }}>
                                        {(() => {
                                            const rel = currentPlan.metrics.international_quality.relevance
                                            return (
                                                <>
                                                    <div style={{ fontWeight: 700, marginBottom: 6 }}>
                                                        {localText('Что проверяет система', 'Жүйе нені тексереді', 'What the system checks')}
                                                    </div>
                                                    <div>
                                                        {localText('Релевантные дисциплины', 'Сәйкес пәндер', 'Relevant courses')}: {rel.relevant_courses}/{rel.total_courses}.
                                                        {' '}{localText('Из них защищены как ГОСО РК', 'Оның ішінде ҚР МЖМБС ретінде қорғалған', 'Protected as RK regulatory')}: {rel.regulatory_protected_courses}.
                                                        {' '}{localText('Можно заменить без риска', 'Қауіпсіз ауыстыруға болады', 'Safely replaceable')}: {rel.replaceable_unsupported_courses}.
                                                    </div>
                                                    {rel.regulatory_examples?.length > 0 && (
                                                        <div style={{ marginTop: 6, color: '#475467' }}>
                                                            {localText('ГОСО не удаляется', 'МЖМБС жойылмайды', 'Regulatory courses are not removed')}: {rel.regulatory_examples.slice(0, 3).map(row => row.title).join('; ')}
                                                        </div>
                                                    )}
                                                    {rel.unsupported_examples?.length > 0 && (
                                                        <div style={{ marginTop: 6, color: '#8a4b00' }}>
                                                            {localText('Кандидаты на замену', 'Ауыстыруға үміткерлер', 'Replacement candidates')}: {rel.unsupported_examples.slice(0, 3).map(row => row.title).join('; ')}
                                                        </div>
                                                    )}
                                                </>
                                            )
                                        })()}
                                    </div>
                                )}
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '10px' }}>
                                    {currentPlan.metrics.international_quality.checks?.map((check, idx) => (
                                        <div key={idx} style={{
                                            background: check.passed ? '#f0fff4' : '#fff8e1',
                                            border: `1px solid ${check.passed ? '#a5d6a7' : '#ffe082'}`,
                                            borderRadius: '8px',
                                            padding: '10px'
                                        }}>
                                            <div style={{ fontWeight: 'bold', color: check.passed ? '#2e7d32' : '#e67e22', marginBottom: '4px' }}>
                                                {check.passed ? '✅' : '⚠️'} {t(check.name)}
                                            </div>
                                            <div style={{ color: '#555', fontSize: '13px', marginBottom: '6px' }}>{localizeQualityEvidence(check.evidence)}</div>
                                            {!check.passed && (
                                                <div style={{ color: '#6d4c41', fontSize: '12px' }}>
                                                    {t('recommendation')}: {t(check.recommendation)}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </CompactSection>
                        )}
                    <PlanSemesterGrid
                        project={project}
                        currentPlan={currentPlan}
                        t={t}
                        localText={localText}
                        localize={localize}
                        localizeCycle={localizeCycle}
                        componentLabel={componentLabel}
                        localizedCourse={localizedCourse}
                        localizedCourseField={localizedCourseField}
                        showCourseDescriptions={showCourseDescriptions}
                        showSelectionDetails={showSelectionDetails}
                        excludedCourses={excludedCourses}
                        toggleCourseExclusion={toggleCourseExclusion}
                        matchFeedbackState={matchFeedbackState}
                        handleMatchFeedback={handleMatchFeedback}
                    />
                    </div>
                )}
            </main>
        </div>
    )
}
