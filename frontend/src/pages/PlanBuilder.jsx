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
import CurriculumRequirements from '../components/CurriculumRequirements'
import { useNotifications } from '../contexts/NotificationContext'
import usePlanBuildPolling from '../hooks/usePlanBuildPolling'
import usePlanVariants from '../hooks/usePlanVariants'
import { saveCurriculumRequirements, loadCoreEvidencePreview, confirmCoreMatch } from '../utils/curriculumRequirementsApi'
import {
    alreadyRunningText,
    localizeQualityEvidenceText,
    longRunningHint,
    planBuildElapsedLabel,
    planBuildStageDetail,
    planBuildStageLabel,
} from '../utils/planBuilderPresentation'
import {
    componentLabel as formatComponentLabel,
    errorMessage as formatErrorMessage,
    epvoSyncMessage as formatEpvoSyncMessage,
    localizedCourse as formatLocalizedCourse,
    localizedCourseField as formatLocalizedCourseField,
} from '../utils/planBuilderFormatters'

const diagnosticGuidance = {
    prerequisites: {
        ru: 'Есть конфликт обязательных пререквизитов. Проверьте порядок дисциплин или измените ограничения последовательности.',
        kk: 'Міндетті пререквизиттерде қайшылық бар. Пәндер ретін немесе дәйектілік шектеулерін тексеріңіз.',
        en: 'Required prerequisites conflict. Check course order or the sequencing constraints.',
    },
    semester_load: {
        ru: 'Нагрузка хотя бы в одном семестре превышает заданный предел. Увеличьте допустимую нагрузку либо число семестров.',
        kk: 'Кемінде бір семестрдегі жүктеме берілген шектен асады. Рұқсат етілген жүктемені не семестр санын өзгертіңіз.',
        en: 'At least one semester exceeds the configured load. Adjust the load limit or number of semesters.',
    },
    credits: {
        ru: 'План не набрал требуемый объём кредитов. Проверьте целевой объём и доступность дисциплин в выбранной группе ЕПВО.',
        kk: 'Жоспар қажетті кредит көлеміне жетпеді. Мақсатты көлемді және таңдалған ЕПВО тобындағы пәндердің қолжетімділігін тексеріңіз.',
        en: 'The plan did not reach the required credit volume. Check the target volume and course availability in the selected EPVO group.',
    },
    domain_quota: {
        ru: 'Не выполнена доля одного из направлений. Уточните коды обоих направлений ЕПВО и минимальные доли.',
        kk: 'Бағыттардың бірінің үлесі орындалмады. Екі ЕПВО бағытының кодтары мен ең төменгі үлестерін нақтылаңыз.',
        en: 'One field quota was not met. Check both EPVO scope codes and the minimum shares.',
    },
    course_lo: {
        ru: 'Не подтверждена связь дисциплин с результатами обучения. Уточните формулировки РО или область/группу ЕПВО.',
        kk: 'Пәндер мен оқу нәтижелерінің байланысы расталмады. ОН тұжырымдарын немесе ЕПВО саласы мен тобын нақтылаңыз.',
        en: 'Course-to-outcome evidence was not confirmed. Refine the outcomes or EPVO scope.',
    },
    real_lo: {
        ru: 'Один или несколько РО не поддержаны реальной дисциплиной. Уточните РО либо профиль ЕПВО; bridge-модуль не заменяет такое подтверждение.',
        kk: 'Бір немесе бірнеше ОН нақты пәнмен расталмады. ОН-ды не ЕПВО профилін нақтылаңыз; bridge-модуль мұндай растауды алмастырмайды.',
        en: 'One or more outcomes lack support from a real course. Refine the outcomes or EPVO profile; a bridge module cannot replace this evidence.',
    },
    bridge_limit: {
        ru: 'Для покрытия РО требуется слишком много новых дисциплин. Сузьте или уточните РО и проверьте профиль ЕПВО.',
        kk: 'ОН жабу үшін тым көп жаңа пән қажет. ОН-ды нақтылап, ЕПВО профилін тексеріңіз.',
        en: 'Too many new course proposals are needed to cover the outcomes. Refine the outcomes and check the EPVO profile.',
    },
    goso: {
        ru: 'Нарушены обязательные нормативные компоненты. Проверьте выбранный нормативный профиль и заданный объём обязательных дисциплин.',
        kk: 'Міндетті нормативтік компоненттер бұзылды. Таңдалған нормативтік профильді және міндетті пәндер көлемін тексеріңіз.',
        en: 'Mandatory regulatory components are violated. Check the selected regulatory profile and required course volume.',
    },
    variant_not_distinct: {
        ru: 'Альтернативы получились одинаковыми. Оставьте вариант A или скорректируйте критерии сравнения B/C.',
        kk: 'Балама нұсқалар бірдей шықты. A нұсқасын қалдырыңыз немесе B/C салыстыру өлшемдерін түзетіңіз.',
        en: 'The alternatives are identical. Keep variant A or adjust the B/C comparison criteria.',
    },
}

function diagnosticActions(status, language) {
    const details = status?.verification_summary || status?.rejected_variants || []
    const reasons = new Set()
    for (const variant of details) {
        for (const item of variant?.hard_details || []) {
            if (item?.reason && item.reason !== 'verifier_breakdown') reasons.add(item.reason)
            if (item?.reason === 'verifier_breakdown') {
                const counts = item.counts || {}
                for (const [reason, count] of Object.entries(counts)) {
                    if (Number(count) > 0) reasons.add(reason === 'bridge_overflow' ? 'bridge_limit' : reason)
                }
            }
        }
    }
    return [...reasons]
        .map(reason => ({ reason, text: diagnosticGuidance[reason]?.[language] || diagnosticGuidance[reason]?.ru }))
        .filter(item => item.text)
}

export default function PlanBuilder() {
    const { notify } = useNotifications()
    const { id } = useParams()
    const [searchParams] = useSearchParams()
    const { t, localize, localizeCycle, localizeDomain, language } = useLanguage()
    const localizedCourseField = (translations, fallback = '') =>
        formatLocalizedCourseField(translations, fallback, localize)
    const [project, setProject] = useState(null)
    const [generationReadiness, setGenerationReadiness] = useState(null)
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
    const [drafts, setDrafts] = useState([])
    const [selectedDraft, setSelectedDraft] = useState(null)
    const { variants, activeVariant, setActiveVariant, fetchVariants } = usePlanVariants()
    // A is the normal, publishable plan. Alternatives are an explicit choice
    // because comparison should not triple a methodist's waiting time.
    const [buildVariants, setBuildVariants] = useState('A')
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
    const applyBuildStatus = (status) => {
            setBuildStatus(status)
            setBuildProgress(status.progress || 0)
            setBuilding(status.state === 'running' || status.state === 'queued')
            if (status.change_report) setChangeReport(status.change_report)
            if (Array.isArray(status.drafts)) setDrafts(status.drafts)
            if (status.publication_status === 'partial') {
                const rejected = (status.rejected_variants || []).map(item => item.variant).filter(Boolean)
                if (rejected.length) {
                    setBuildNotice({
                        type: 'success',
                        text: `Опубликованы прошедшие проверку варианты. Не опубликованы: ${rejected.join(', ')} — откройте отчёт ограничений перед повтором.`,
                    })
                }
            }
        }
    const pollBuildStatus = async (versionId) => {
        const { data } = await axios.get(`/api/planner/${versionId}/build-status`)
        applyBuildStatus(data)
        return data
    }
    const { start: startBuildStatusPolling, stop: stopBuildStatusPolling } = usePlanBuildPolling({
        onStatus: applyBuildStatus,
        onComplete: async (versionId) => {
            setBuilding(false)
            await fetchVariants(versionId)
        },
    })
    const semesterRefs = useRef({})
    const onShowSemester = (semester) => {
        semesterRefs.current[semester]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }

    const localizedCourse = (course = {}) => formatLocalizedCourse(course, localize)

    const cycleLabel = t('cycle')
    const cycleEstimateLabel = t('cycle_estimate')
    const componentLabelText = t('component')
    const sourceLabel = t('source')

    const errorMessage = (err) => formatErrorMessage(err, language, t)

    const localizeQualityEvidence = (text = '') => localizeQualityEvidenceText(text, language)

    const epvoSyncMessage = (sync) => formatEpvoSyncMessage(sync, t)

    const componentLabel = (value = '') => formatComponentLabel(value, { localizeCycle, t })

    const buildStageLabel = (stage = 'idle') => planBuildStageLabel(stage, language)
    const buildStageDetail = () => planBuildStageDetail(buildStatus, language)
    const buildElapsedLabel = () => planBuildElapsedLabel(buildStatus, language)
    const buildAlreadyRunningText = () => alreadyRunningText(language)
    const buildLongRunningHint = () => longRunningHint(language)

    const compactToggleLabel = t('open_collapse')
    const epvoApplied = searchParams.get('epvoApplied') === '1'
    const readinessChecks = generationReadiness?.checks || {}
    const evidenceReadiness = generationReadiness?.evidence_preflight
    const readinessChecklist = [
        {
            label: localize({ ru: 'Цель программы', kk: 'Бағдарлама мақсаты', en: 'Programme goal' }),
            value: readinessChecks.goal
                ? localize({ ru: 'заполнена', kk: 'толтырылған', en: 'provided' })
                : localize({ ru: 'не заполнена', kk: 'толтырылмаған', en: 'missing' }),
            passed: Boolean(readinessChecks.goal),
        },
        {
            label: localize({ ru: 'Результаты обучения', kk: 'Оқу нәтижелері', en: 'Learning outcomes' }),
            value: readinessChecks.learning_outcomes
                ? `${readinessChecks.learning_outcomes} ${localize({ ru: 'шт.', kk: 'дана', en: 'items' })}`
                : localize({ ru: 'не заданы', kk: 'берілмеген', en: 'missing' }),
            passed: Number(readinessChecks.learning_outcomes || 0) > 0,
        },
        {
            label: localize({ ru: 'Уникальные РО', kk: 'Бірегей ОН', en: 'Unique LOs' }),
            value: `${Number(readinessChecks.unique_learning_outcomes || 0)} / ${Number(readinessChecks.learning_outcomes || 0)}`,
            passed: Number(readinessChecks.unique_learning_outcomes || 0) === Number(readinessChecks.learning_outcomes || 0) && Number(readinessChecks.learning_outcomes || 0) > 0,
        },
        {
            label: localize({ ru: 'Область и группа ЕПВО', kk: 'ЕПВО саласы және тобы', en: 'EPVO area and group' }),
            value: readinessChecks.catalogue_scope
                ? localize({ ru: 'заданы', kk: 'берілген', en: 'provided' })
                : localize({ ru: 'требуют уточнения', kk: 'нақтылау қажет', en: 'needs clarification' }),
            passed: Boolean(readinessChecks.catalogue_scope),
        },
        {
            label: localize({ ru: 'Объём и нагрузка', kk: 'Көлемі және жүктеме', en: 'Volume and workload' }),
            value: `${readinessChecks.volume?.target_credits || 0} / ${readinessChecks.volume?.capacity_credits || 0} ECTS`,
            passed: Number(readinessChecks.volume?.target_credits || 0) > 0 && Number(readinessChecks.volume?.target_credits || 0) <= Number(readinessChecks.volume?.capacity_credits || 0),
        },
        {
            label: localize({ ru: 'Доказательства ЕПВО/РО', kk: 'ЕПВО/ОН дәлелдері', en: 'EPVO/LO evidence' }),
            value: !evidenceReadiness?.checked
                ? localize({ ru: 'будут проверены при построении', kk: 'құру кезінде тексеріледі', en: 'will be checked during build' })
                : evidenceReadiness.blocking
                    ? localize({ ru: 'требуют уточнения', kk: 'нақтылауды қажет етеді', en: 'need clarification' })
                    : localize({ ru: 'предварительно достаточны', kk: 'алдын ала жеткілікті', en: 'provisionally sufficient' }),
            // This is deliberately advisory: a fresh build may recalculate
            // stale MatchScore rows before the worker applies the hard gate.
            passed: !evidenceReadiness?.blocking,
        },
    ]

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
                axios.get(`/api/planner/${projRes.data.latest_version.id}/generation-readiness`)
                    .then(response => setGenerationReadiness(response.data))
                    .catch(() => setGenerationReadiness(null))
                await fetchVariants(projRes.data.latest_version.id)
                axios.get(`/api/planner/${projRes.data.latest_version.id}/drafts`)
                    .then(response => setDrafts(response.data?.drafts || []))
                    .catch(() => setDrafts([]))
                startBuildStatusPolling(projRes.data.latest_version.id)
            }
        } catch (err) {
            console.error('Error fetching project:', err)
        } finally {
            setLoading(false)
        }
    }

    const searchMethodistCourses = async (search) => {
        const { data } = await axios.get('/api/repository/courses', {
            params: { search, limit: 20, include_descriptions: false },
        })
        return data
    }

    const saveMethodistRequirements = async (requirements) => {
        const constraints = await saveCurriculumRequirements(
            axios.patch, Number(id), project?.constraints || {}, requirements,
        )
        setProject(current => ({ ...current, constraints }))
        setRequiresRegeneration(true)
    }

    const previewCoreMatch = (blockId, courseId) => loadCoreEvidencePreview(
        axios.get, Number(id), project.latest_version.id, blockId, courseId,
    )

    const confirmMethodistCoreMatch = async (reviewed) => {
        const record = await confirmCoreMatch(axios.post, Number(id), project.latest_version.id, reviewed)
        setProject(current => {
            const constraints = current.constraints || {}
            const prior = (constraints.curriculum_confirmations || []).filter(item =>
                item.block_id !== record.block_id || item.course_id !== record.course_id
            )
            return { ...current, constraints: { ...constraints, curriculum_confirmations: [...prior, record] } }
        })
        setRequiresRegeneration(true)
        return record
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

    const downloadMethodistPackage = async (format) => {
        const versionId = project?.latest_version?.id
        if (!versionId || !currentPlan?.plan_id) return
        try {
            const response = await axios.post(
                `/api/export/${versionId}`,
                null,
                { params: { format, variant: activeVariant, language }, responseType: 'blob' },
            )
            const url = URL.createObjectURL(response.data)
            const link = document.createElement('a')
            link.href = url
            link.download = `curriculum_plan_${versionId}_${activeVariant}.${format}`
            link.click()
            URL.revokeObjectURL(url)
        } catch (err) {
            notify(`Не удалось выгрузить ${format.toUpperCase()}: ${errorMessage(err)}`)
        }
    }

    const openDraft = async (draftId) => {
        const versionId = project?.latest_version?.id
        if (!versionId || !draftId) return
        try {
            const response = await axios.get(`/api/planner/${versionId}/drafts/${draftId}`)
            setSelectedDraft(response.data)
        } catch (err) {
            notify(`Не удалось открыть черновик: ${errorMessage(err)}`)
        }
    }

    const handleBuild = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return
        if (generationReadiness && !generationReadiness.ready) {
            const reasons = [...(generationReadiness.missing || []), ...(generationReadiness.blocking || [])]
            setBuildNotice({
                type: 'error',
                text: `Построение не начато: ${reasons.join('; ')}`,
            })
            return
        }
        let handedToAsyncWorker = false

        try {
            setBuilding(true)
            setBuildNotice(null)
            setChangeReport(null)
            setBuildProgress(5)
            setBuildStatus({ state: 'running', stage: 'matching', progress: 5 })
            const buildRequest = axios.post(`/api/planner/${versionId}/build`, { variants: buildVariants === 'all' ? ['A', 'B', 'C'] : [buildVariants] })
            startBuildStatusPolling(versionId)
            const buildResponse = await buildRequest
            if (buildResponse.status === 202 || buildResponse.data?.state === 'queued') {
                handedToAsyncWorker = true
                return
            }
            await fetchVariants(versionId)
            setRequiresRegeneration(false)
            setBuildProgress(100)
            setBuildStatus({ state: 'complete', stage: 'complete', progress: 100, change_report: buildResponse.data?.change_report, publication_status: buildResponse.data?.publication_status, rejected_variants: buildResponse.data?.rejected_variants, drafts: buildResponse.data?.drafts })
            if (Array.isArray(buildResponse.data?.drafts)) setDrafts(buildResponse.data.drafts)
            setChangeReport(buildResponse.data?.change_report || null)
            const message = epvoSyncMessage(buildResponse.data?.epvo_repository)
            const rejected = (buildResponse.data?.rejected_variants || []).map(item => item.variant).filter(Boolean)
            const partialText = buildResponse.data?.publication_status === 'partial' && rejected.length
                ? `Опубликованы прошедшие проверку варианты. Не опубликованы: ${rejected.join(', ')} — откройте отчёт ограничений перед повтором.`
                : null
            if (partialText || message) setBuildNotice({ type: 'success', text: partialText || message })
        } catch (err) {
            if (err.authExpired || err.response?.status === 401) {
                return
            } else if (err.response?.status === 409) {
                await pollBuildStatus(versionId)
                setBuildNotice({ type: 'error', text: buildAlreadyRunningText() })
            } else {
                const message = errorMessage(err)
                // A queued worker persists an actionable verifier summary.
                // Fetch it after a terminal HTTP error instead of replacing it
                // with the generic response text from the synchronous route.
                let terminalStatus = null
                if (err.response?.status === 422) {
                    try { terminalStatus = await pollBuildStatus(versionId) } catch (_) { /* preserve the HTTP error below */ }
                }
                if (!terminalStatus || !['rejected', 'failed', 'timed_out', 'cancelled'].includes(terminalStatus.state)) {
                    setBuildStatus({ state: 'failed', stage: 'failed', progress: 0, error: message })
                }
                notify(t('build_error') + ': ' + message)
            }
        } finally {
            // A 202 only confirms durable queue acceptance. Polling owns the
            // busy state until a terminal job status arrives.
            if (!handedToAsyncWorker) setBuilding(false)
        }
    }

    const missingVariants = ['A', 'B', 'C'].filter(item => !variants?.[item])
    const handleBuildMissing = async () => {
        if (!missingVariants.length || building) return
        setBuildVariants(missingVariants.join(','))
        const versionId = project?.latest_version?.id
        let handedToAsyncWorker = false
        try {
            setBuilding(true)
            setBuildNotice(null)
            setBuildStatus({ state: 'running', stage: 'matching', progress: 5 })
            const response = await axios.post(`/api/planner/${versionId}/build`, { variants: missingVariants })
            if (response.status === 202 || response.data?.state === 'queued') {
                handedToAsyncWorker = true
                startBuildStatusPolling(versionId)
                return
            }
            await fetchVariants(versionId)
            setBuildStatus({ state: 'complete', stage: 'complete', progress: 100, change_report: response.data?.change_report })
        } catch (err) {
                notify(t('build_error') + ': ' + errorMessage(err))
        } finally {
            if (!handedToAsyncWorker) setBuilding(false)
        }
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
                    ? `${t('quality_improvements_applied')} ${protectedCount} ${t('goso_components_protected')}`
                    : `${t('quality_improvements_applied')} ${t('rebuild_not_required')}`
                setQualityNotice({ type: 'success', text: message })
                return
            }
            const progressTimer = window.setInterval(async () => {
                try { await pollBuildStatus(versionId) } catch (_) { /* build request handles errors */ }
            }, BUILD_STATUS_POLL_MS)
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
            }, BUILD_STATUS_POLL_MS)
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
                text: t('recompute_success').replace('{count}', response.data?.total_matches || 0)
            })
        } catch (err) {
            setBuildStatus({ state: 'failed', stage: 'failed', progress: 0, error: errorMessage(err) })
            setBuildNotice({ type: 'error', text: t('recompute_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('bridge_preview_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'success', text: response.data?.message || t('course_added') })
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
            setBuildNotice({ type: 'error', text: t('bridge_replace_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('bridge_replace_all_error') + ': ' + (errorMessage(err)) })
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
                ? t('selected_medium_replacements').replace('{count}', Object.keys(selected).length)
                : t('no_medium_replacements'),
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
            setBuildNotice({ type: 'error', text: t('ai_courses_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('course_confirm_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('exclusion_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('course_confirm_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('replacements_error') + ': ' + (errorMessage(err)) })
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
                    ? `${t('replacements_loaded')}: ${ok}`
                    : t('replacements_visible_error'),
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
            setBuildNotice({ type: 'error', text: t('replacement_confirm_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('coverage_sources_error') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: t('feedback_save_error') + ': ' + (errorMessage(err)) })
        }
    }

    if (loading) return <LoadingSpinner fullPage={false}
        message={localize({ru: 'Загружаем сохранённый план', kk: 'Сақталған жоспар жүктелуде', en: 'Loading the saved plan'})}
        detail={localize({ru: 'Читаем данные программы. Повторное построение не запускается.', kk: 'Бағдарлама деректері оқылуда. Қайта құру іске қосылмайды.', en: 'Reading programme data. No new build is being started.'})} />

    const currentPlan = variants ? variants[activeVariant] : null
    const creditVerification = currentPlan?.metrics?.verification || currentPlan?.verification || {}
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
                            {t('build')}
                            <select value={buildVariants} onChange={event => setBuildVariants(event.target.value)} disabled={building} style={{ marginLeft: 6, padding: '7px 8px', borderRadius: 6 }}>
                                <option value="A">A — основной план</option><option value="all">A/B/C — сравнение альтернатив</option><option value="B">B — альтернатива</option><option value="C">C — альтернатива</option>
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
                                {t('build_missing') + missingVariants.join(', ')}
                            </button>
                        )}
                        <button
                            className="btn btn-secondary"
                            onClick={handleRecomputeMatches}
                            disabled={building || recomputingMatches}
                        >
                            {recomputingMatches ? `${buildProgress}%` : t('recompute_links')}
                        </button>
                    </div>
                </div>
            </header>

            <main className="container workspace-main" style={{ paddingTop: '30px' }}>
                <CurriculumRequirements
                    value={project?.constraints?.curriculum_requirements}
                    confirmations={project?.constraints?.curriculum_confirmations || []}
                    versionId={project?.latest_version?.id}
                    onSave={saveMethodistRequirements}
                    searchCourses={searchMethodistCourses}
                    loadPreview={previewCoreMatch}
                    confirmMatch={confirmMethodistCoreMatch}
                    disabled={building}
                />
                {epvoApplied && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderTop: '2px solid #366092' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div>
                                <strong>{t('epvo_candidates_added')}</strong>
                                <div style={{ color: '#667', fontSize: 13, marginTop: 4 }}>
                                    {t('epvo_candidates_hint')}
                                </div>
                            </div>
                            <button className="btn btn-primary" onClick={handleBuild}>{t('generate_variants')}</button>
                        </div>
                    </div>
                )}
                {requiresRegeneration && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderTop: '2px solid #ef6c00', background: '#fffaf2' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div>
                                <strong>{t('changes_next_generation')}</strong>
                                <div style={{ color: '#6d4c41', fontSize: 13, marginTop: 4 }}>
                                    {t('changes_next_generation_hint')}
                                </div>
                            </div>
                            <button className="btn btn-primary" onClick={handleBuild}>
                                {t('regenerate_abc')}
                            </button>
                        </div>
                    </div>
                )}
                {generationReadiness && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderTop: `2px solid ${generationReadiness.ready ? '#2e7d32' : '#c62828'}` }}>
                        <strong>{generationReadiness.ready ? 'Исходные условия готовы к построению' : 'Перед построением нужно исправить исходные условия'}</strong>
                        {generationReadiness.ready && (
                            <>
                                <p style={{ margin: '8px 0 0', color: '#356244', fontSize: 13 }}>
                                    {localize({ ru: 'Проверка перед запуском: цель, РО, область ЕПВО и объём программы. Это не заменяет финальную проверку дисциплин и нагрузки.', kk: 'Іске қосар алдындағы тексеріс: мақсат, ОН, ЕПВО саласы және бағдарлама көлемі. Бұл пәндер мен жүктеменің қорытынды тексерісін алмастырмайды.', en: 'Pre-build check: goal, LOs, EPVO scope and programme volume. It does not replace final course and workload verification.' })}
                                </p>
                                <div className="quick-grid" style={{ marginTop: 12 }}>
                                    {readinessChecklist.map((item) => (
                                        <div key={item.label} style={{ fontSize: 13 }}>
                                            <b>{item.passed ? '✓' : '!' } {item.label}</b><br />
                                            <span style={{ color: item.passed ? '#356244' : '#9b1c1c' }}>{item.value}</span>
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}
                        {(generationReadiness.missing || []).length > 0 && <p style={{ margin: '8px 0 0', color: '#b71c1c' }}>Заполните: {generationReadiness.missing.join(', ')}.</p>}
                        {(generationReadiness.blocking || []).map((item, index) => <p key={`block-${index}`} style={{ margin: '8px 0 0', color: '#b71c1c' }}>{item}</p>)}
                        {(generationReadiness.warnings || []).map((item, index) => <p key={`warning-${index}`} style={{ margin: '8px 0 0', color: '#7a5700' }}>{item}</p>)}
                        {evidenceReadiness?.message && (
                            <p style={{ margin: '8px 0 0', color: evidenceReadiness.blocking ? '#7a5700' : '#566' }}>
                                {evidenceReadiness.blocking ? '⚠ ' : ''}{evidenceReadiness.message}
                            </p>
                        )}
                    </div>
                )}
                <PlanBuildProgress
                    active={building || buildStatus.state === 'queued' || buildStatus.state === 'running'}
                    progress={buildProgress}
                    status={buildStatus}
                    title={t('building_plan')}
                    stageLabel={buildStageLabel}
                    stageDetail={buildStageDetail()}
                    elapsedLabel={buildElapsedLabel()}
                    longRunningHint={buildLongRunningHint()}
                />
                {['rejected', 'failed', 'timed_out'].includes(buildStatus.state) && buildStatus.error && (
                    <div className="card inline-alert inline-alert-error" role="alert" style={{ marginBottom: '20px' }}>
                        <strong>{t('build_result_error')}</strong>
                        <p>{buildStatus.error}</p>
                        {diagnosticActions(buildStatus, language).length > 0 && (
                            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid #f3c4c4' }}>
                                <strong>{localize({ ru: 'Что исправить перед повтором', kk: 'Қайталау алдында нені түзету керек', en: 'What to fix before retrying' })}</strong>
                                <ul style={{ margin: '7px 0 0', paddingLeft: 20, lineHeight: 1.45 }}>
                                    {diagnosticActions(buildStatus, language).map(item => <li key={item.reason}>{item.text}</li>)}
                                </ul>
                            </div>
                        )}
                    </div>
                )}
                {drafts.length > 0 && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderTop: '2px solid #ef6c00', background: '#fffaf2' }}>
                        <strong>Рабочие черновики после финальной проверки</strong>
                        <p style={{ margin: '8px 0', color: '#6d4c41', fontSize: 13 }}>
                            Это сохранённые варианты для методической доработки. Они не опубликованы, не могут стать активным планом и не заменяют проверенный результат.
                        </p>
                        {drafts.map((draft) => (
                            <div key={draft.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: '9px 0', borderTop: '1px solid #f0d6b7', flexWrap: 'wrap' }}>
                                <span>
                                    <b>Вариант {draft.variant_type}</b>: {draft.total_credits ?? '—'} / {draft.target_credits ?? '—'} ECTS, жёстких ограничений: {draft.hard_violation_count ?? '—'}.
                                </span>
                                <button className="btn btn-secondary" onClick={() => openDraft(draft.id)}>Открыть состав черновика</button>
                            </div>
                        ))}
                        {selectedDraft && (
                            <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #e9c9a5' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                                    <b>Черновик {selectedDraft.variant_type}: состав по семестрам</b>
                                    <button className="btn btn-secondary" onClick={() => setSelectedDraft(null)}>Скрыть</button>
                                </div>
                                {Object.entries(selectedDraft.schedule || {}).sort(([left], [right]) => Number(left) - Number(right)).map(([semester, items]) => (
                                    <div key={semester} style={{ marginTop: 10 }}>
                                        <b>Семестр {semester}</b>
                                        <ul style={{ margin: '5px 0 0', paddingLeft: 20 }}>
                                            {(items || []).map((item, index) => <li key={`${semester}-${index}`}>{item.title || item.course_title || (item.bridge_module_id ? 'Проектный bridge-модуль' : `Дисциплина #${item.course_id || '—'}`)} — {item.credits || '—'} ECTS</li>)}
                                        </ul>
                                    </div>
                                ))}
                                <p style={{ margin: '10px 0 0', color: '#8a4b08', fontSize: 13 }}>Перед публикацией исправьте указанные выше ограничения и повторите построение.</p>
                            </div>
                        )}
                    </div>
                )}
                {changeReport?.available && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderTop: '2px solid #7b1fa2' }}>
                        <h3 style={{ marginTop: 0 }}>{t('changes_after_rebuild')}</h3>
                        <div className="quick-grid">
                            <div><b>{t('credits')}</b><br />{changeReport.credits_delta > 0 ? '+' : ''}{changeReport.credits_delta}</div>
                            <div><b>{t('bridge_modules_label')}</b><br />{changeReport.bridges_delta > 0 ? '+' : ''}{changeReport.bridges_delta}</div>
                            <div><b>{t('minimum_lo')}</b><br />{changeReport.min_lo_delta == null ? '—' : `${changeReport.min_lo_delta > 0 ? '+' : ''}${Math.round(changeReport.min_lo_delta * 100)}%`}</div>
                            <div><b>{t('quality_label')}</b><br />{String(changeReport.quality_before)} → {String(changeReport.quality_after)}</div>
                        </div>
                        <p style={{ color: '#667', fontSize: 13, marginTop: 10 }}>
                            {t('added_label')}: {changeReport.added_count}; {t('removed_label')}: {changeReport.removed_count}; hard: {changeReport.hard_before} → {changeReport.hard_after}.
                        </p>
                        {(changeReport.added_titles_sample?.length > 0 || changeReport.removed_titles_sample?.length > 0) && (
                            <details style={{ marginTop: 8 }}>
                                <summary style={{ cursor: 'pointer', color: '#366092', fontWeight: 600 }}>{t('show_change_examples')}</summary>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8, fontSize: 12 }}>
                                    <div><b>{t('added_label')}</b>{(changeReport.added_titles_sample || []).map((title, index) => <div key={`a-${index}`}>+ {title}</div>)}</div>
                                    <div><b>{t('removed_label')}</b>{(changeReport.removed_titles_sample || []).map((title, index) => <div key={`r-${index}`}>− {title}</div>)}</div>
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
                            {building ? `${t('building_plan')} ${buildProgress}%` : (['rejected', 'failed', 'timed_out', 'cancelled'].includes(buildStatus.state) ? t('retry_build') : t('generate_variants'))}
                        </button>
                    </div>
                ) : (
                    <div>
                        {duplicateVariantGroups.length > 0 && (
                            <div style={{ marginBottom: 16, padding: '12px 16px', borderRadius: 10, background: '#fff8e1', border: '1px solid #f1c40f', color: '#6d4c00' }}>
                                <b>{t('duplicate_variants')}</b>
                                <div style={{ marginTop: 5, fontSize: 13 }}>
                                    {t('duplicate_variants_desc').replace('{variants}', duplicateVariantGroups.join(', '))}
                                </div>
                            </div>
                        )}
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '20px' }}>
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
                            <button className="btn btn-secondary" onClick={() => downloadMethodistPackage('pdf')}>
                                Скачать PDF-пакет
                            </button>
                            <button className="btn btn-secondary" onClick={() => downloadMethodistPackage('xlsx')}>
                                Скачать XLSX
                            </button>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: '#4f5d6b', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={showCourseDescriptions}
                                    onChange={(event) => handleShowCourseDescriptionsChange(event.target.checked)}
                                />
                                {t('show_course_descriptions')}
                            </label>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: '#4f5d6b', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={showSelectionDetails}
                                    onChange={(event) => handleShowSelectionDetailsChange(event.target.checked)}
                                />
                                {t('show_selection_reasons')}
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
                            onShowSemester={onShowSemester}
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
                        <PlanVerificationPanels currentPlan={currentPlan} compactToggleLabel={compactToggleLabel} t={t} />
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
                                            ? t('quality_passed_notice')
                                            : t('quality_repair_notice')}
                                    </strong>{' '}
                                    {t('quality_notice_desc')}
                                    {creditVerification.credit_adjustment_required && (
                                        <p role="status" style={{ margin: '8px 0 0' }}>
                                            {localize({
                                                ru: `План содержит ${creditVerification.total_credits} кредитов при цели ${creditVerification.target_credits}. Превышение в пределах допуска; перед утверждением скорректируйте кредиты вручную.`,
                                                kk: `Жоспарда ${creditVerification.total_credits} кредит, мақсат — ${creditVerification.target_credits}. Артық кредит рұқсат шегінде; бекіту алдында кредиттерді қолмен түзетіңіз.`,
                                                en: `The plan contains ${creditVerification.total_credits} credits against a target of ${creditVerification.target_credits}. The surplus is within the allowance; adjust credits manually before approval.`,
                                            })}
                                        </p>
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
                                                        {t('what_system_checks')}
                                                    </div>
                                                    <div>
                                                        {t('relevant_courses')}: {rel.relevant_courses}/{rel.total_courses}.
                                                        {' '}{t('protected_goso')}: {rel.regulatory_protected_courses}.
                                                        {' '}{t('safely_replaceable')}: {rel.replaceable_unsupported_courses}.
                                                    </div>
                                                    {rel.regulatory_examples?.length > 0 && (
                                                        <div style={{ marginTop: 6, color: '#475467' }}>
                                                            {t('goso_not_removed')}: {rel.regulatory_examples.slice(0, 3).map(row => row.title).join('; ')}
                                                        </div>
                                                    )}
                                                    {rel.unsupported_examples?.length > 0 && (
                                                        <div style={{ marginTop: 6, color: '#8a4b00' }}>
                                                            {t('replacement_candidates')}: {rel.unsupported_examples.slice(0, 3).map(row => row.title).join('; ')}
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
                        semesterRefs={semesterRefs}
                    />
                    </div>
                )}
            </main>
        </div>
    )
}
