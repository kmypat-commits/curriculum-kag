import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'

export default function PlanBuilder() {
    const { id } = useParams()
    const [searchParams] = useSearchParams()
    const { t, localize, language } = useLanguage()
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
    const [showCourseDescriptions, setShowCourseDescriptions] = useState(false)
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

    const errorMessage = (err) => {
        const detail = err?.response?.data?.detail
        if (Array.isArray(detail)) {
            return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join('; ')
        }
        if (detail && typeof detail === 'object') {
            return detail.message || detail.error || JSON.stringify(detail)
        }
        return detail || err?.message || localText('Неизвестная ошибка', 'Белгісіз қате', 'Unknown error')
    }

    const localizeQualityEvidence = (text = '') => {
        if (language !== 'ru') return text
        const patterns = [
            [/^(\d+)\/(\d+) learning outcomes meet the coverage threshold\.$/, '$1/$2 результатов обучения достигли порога покрытия.'],
            [/^Hard violations: (\d+)\.$/, 'Жёстких нарушений: $1.'],
            [/^(\d+)\/(\d+) repository courses match the project domains\.$/, '$1/$2 дисциплин соответствуют областям проекта.'],
            [/^(\d+)\/(\d+) courses are supported by the selected EPVO scope, programme LO evidence, or RK mandatory requirements\.$/, '$1/$2 дисциплин подтверждены выбранным направлением ЕПВО, связью с результатами обучения или обязательными требованиями РК.'],
            [/^Interdisciplinary\/bridge units: (\d+)\.$/, 'Междисциплинарных/bridge-модулей: $1.'],
            [/^Not applicable: this is a standard single-direction programme\.$/, 'Не применяется: это стандартная программа одного направления.'],
            [/^(\d+)\/(\d+) learning units include assessment methods\.$/, '$1/$2 учебных единиц содержат методы оценивания.'],
            [/^Promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Подтверждений bridge-модулей: $1; bridge-модулей в плане: $2.'],
            [/^Expert feedback: (\d+); promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Экспертных оценок: $1; подтверждений bridge-модулей: $2; bridge-модулей в плане: $3.'],
        ]
        return patterns.reduce((value, [pattern, replacement]) => pattern.test(value) ? value.replace(pattern, replacement) : value, text)
    }

    const epvoSyncMessage = (sync) => {
        if (!sync) return null
        return t('epvo_sync_summary')
            .replace('{created}', sync.created ?? 0)
            .replace('{linked}', sync.linked ?? 0)
            .replace('{scope}', sync.group_code || sync.direction_code || sync.scope || t('all_domains'))
    }

    const componentLabel = (value = '') => {
        const normalized = String(value).trim().toLowerCase()
        if (['elective', 'elective component', 'компонент по выбору'].includes(normalized)) return t('elective')
        if (['university', 'university component', 'вузовский компонент'].includes(normalized)) return t('university')
        return t('mandatory')
    }

    const buildStageLabel = (stage = 'idle') => {
        const dictionary = {
            ru: {
                idle: 'Ожидание',
                matching: 'Сопоставляем результаты обучения с дисциплинами',
                epvo_repository: 'Подтягиваем дисциплины ЕПВО по выбранным направлениям',
                scoring: 'Оцениваем связи дисциплина–результат обучения',
                variants: 'Готовим варианты A/B/C',
                variant_A_start: 'Строим вариант A',
                variant_A: 'Проверяем вариант A',
                variant_B_start: 'Строим вариант B',
                variant_B: 'Проверяем вариант B',
                variant_C_start: 'Строим вариант C',
                variant_C: 'Проверяем вариант C',
                saving: 'Сохраняем новые планы без порчи старого активного',
                complete: 'Готово',
                failed: 'Ошибка',
            },
            kk: {
                idle: 'Күту',
                matching: 'Оқу нәтижелерін пәндермен сәйкестендіру',
                epvo_repository: 'Таңдалған бағыттар бойынша ЕПВО пәндерін қосу',
                scoring: 'Пән–оқу нәтижесі байланыстарын бағалау',
                variants: 'A/B/C нұсқаларын дайындау',
                variant_A_start: 'A нұсқасын құру',
                variant_A: 'A нұсқасын тексеру',
                variant_B_start: 'B нұсқасын құру',
                variant_B: 'B нұсқасын тексеру',
                variant_C_start: 'C нұсқасын құру',
                variant_C: 'C нұсқасын тексеру',
                saving: 'Ескі белсенді жоспарды бұзбай жаңа жоспарларды сақтау',
                complete: 'Дайын',
                failed: 'Қате',
            },
            en: {
                idle: 'Waiting',
                matching: 'Matching learning outcomes with courses',
                epvo_repository: 'Adding EPVO courses for selected fields',
                scoring: 'Scoring course–learning outcome links',
                variants: 'Preparing A/B/C variants',
                variant_A_start: 'Building variant A',
                variant_A: 'Checking variant A',
                variant_B_start: 'Building variant B',
                variant_B: 'Checking variant B',
                variant_C_start: 'Building variant C',
                variant_C: 'Checking variant C',
                saving: 'Saving new plans without corrupting the active one',
                complete: 'Complete',
                failed: 'Failed',
            },
        }
        const labels = dictionary[language] || dictionary.ru
        return labels[stage] || stage
    }

    const buildStageDetail = () => {
        if (buildStatus.stage === 'scoring' && buildStatus.lo_total) {
            const linkWord = language === 'kk' ? 'байланыс' : language === 'en' ? 'links' : 'связей'
            return `LO ${buildStatus.lo_index}/${buildStatus.lo_total}${buildStatus.lo_code ? ` — ${buildStatus.lo_code}` : ''}${buildStatus.matches ? `, ${linkWord}: ${buildStatus.matches}` : ''}`
        }
        if (buildStatus.stage?.startsWith?.('variant_')) {
            if (language === 'kk') return 'Пәндер таңдалып, кредиттер, пререквизиттер және домен шектеулері тексеріліп жатыр.'
            if (language === 'en') return 'Selecting courses and checking credits, prerequisites, and domain constraints.'
            return 'Идёт подбор дисциплин, проверка кредитов, пререквизитов и доменных ограничений.'
        }
        return null
    }

    const buildElapsedLabel = () => {
        const total = Math.max(0, Math.round(Number(buildStatus.elapsed_seconds) || 0))
        if (!total) return null
        const minutes = Math.floor(total / 60)
        const seconds = total % 60
        const value = minutes ? `${minutes} ${language === 'en' ? 'min' : 'мин'} ${seconds} ${language === 'en' ? 'sec' : 'сек'}` : `${seconds} ${language === 'en' ? 'sec' : 'сек'}`
        if (language === 'kk') return `Өткен уақыт: ${value}`
        if (language === 'en') return `Elapsed: ${value}`
        return `Прошло: ${value}`
    }

    const buildAlreadyRunningText = () => {
        if (language === 'kk') return 'Құру процесі жүріп жатыр. Ағымдағы процесс аяқталғанын күтіңіз.'
        if (language === 'en') return 'Plan generation is already running. Please wait for the current process to finish.'
        return 'Построение уже идёт. Дождитесь завершения текущего процесса.'
    }

    const buildLongRunningHint = () => {
        if (language === 'kk') return 'ЕПВО базасы үлкен болса, бұл кезең бірнеше минутқа созылуы мүмкін. Ескі белсенді жоспар барлық нұсқалар сәтті құрылғанша сақталады.'
        if (language === 'en') return 'If the EPVO catalogue is large, this step may take several minutes. The old active plan is kept until all variants are built successfully.'
        return 'Если база ЕПВО большая, этап может идти несколько минут. Старый активный план сохраняется до успешного построения всех вариантов.'
    }

    const localText = (ru, kk, en) => language === 'kk' ? kk : language === 'en' ? en : ru
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

    const fetchVariants = async (versionId) => {
        try {
            const variantsRes = await axios.get(`/api/planner/${versionId}/variants`)
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

    const handleBuild = async () => {
        const versionId = project?.latest_version?.id
        if (!versionId) return

        try {
            setBuilding(true)
            setBuildNotice(null)
            setChangeReport(null)
            setBuildProgress(5)
            setBuildStatus({ state: 'running', stage: 'matching', progress: 5 })
            const buildRequest = axios.post(`/api/planner/${versionId}/build`)
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
                alert(t('build_error') + ': ' + message)
            }
        } finally {
            setBuilding(false)
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
            await axios.post('/api/kag/match-feedback', {
                project_version_id: versionId,
                course_id: courseId,
                lo_id: loId,
                verdict,
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
                        <button
                            className="btn btn-primary"
                            onClick={handleBuild}
                            disabled={building}
                        >
                            {building ? `${t('building_plan')} ${buildProgress}%` : '✨ ' + t('generate_variants')}
                        </button>
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
                {(building || buildStatus.state === 'running') && (
                    <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #366092' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'center' }}>
                            <div>
                                <h3 style={{ margin: '0 0 6px' }}>{t('building_plan')}</h3>
                                <div style={{ color: '#566', fontSize: 14 }}>{buildStageLabel(buildStatus.stage)}</div>
                                {buildStageDetail() && <div style={{ color: '#789', fontSize: 13, marginTop: 4 }}>{buildStageDetail()}</div>}
                                {buildElapsedLabel() && <div style={{ color: '#789', fontSize: 13, marginTop: 4 }}>{buildElapsedLabel()}</div>}
                            </div>
                            <strong style={{ fontSize: 22, color: '#366092' }}>{buildProgress}%</strong>
                        </div>
                        <div style={{ height: 10, background: '#e8edf5', borderRadius: 99, overflow: 'hidden', marginTop: 14 }}>
                            <div style={{
                                width: `${Math.max(5, Math.min(100, buildProgress || 0))}%`,
                                height: '100%',
                                background: 'linear-gradient(90deg, #366092, #5fc3ff)',
                                transition: 'width 300ms ease'
                            }} />
                        </div>
                        <p style={{ margin: '10px 0 0', color: '#667', fontSize: 13 }}>
                            {buildLongRunningHint()}
                        </p>
                    </div>
                )}
                {changeReport?.available && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #7b1fa2' }}>
                        <h3 style={{ marginTop: 0 }}>{localText('Что изменилось после перестройки', 'Қайта құрудан кейін не өзгерді', 'What changed after rebuild')}</h3>
                        <div className="quick-grid">
                            <div><b>{localText('Кредиты', 'Кредиттер', 'Credits')}</b><br />{changeReport.credits_delta > 0 ? '+' : ''}{changeReport.credits_delta}</div>
                            <div><b>Bridge</b><br />{changeReport.bridges_delta > 0 ? '+' : ''}{changeReport.bridges_delta}</div>
                            <div><b>Min LO</b><br />{changeReport.min_lo_delta == null ? '—' : `${changeReport.min_lo_delta > 0 ? '+' : ''}${Math.round(changeReport.min_lo_delta * 100)}%`}</div>
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

                        <div style={{ marginBottom: '14px', display: 'flex', justifyContent: 'flex-end' }}>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: '#4f5d6b', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={showCourseDescriptions}
                                    onChange={(event) => setShowCourseDescriptions(event.target.checked)}
                                />
                                {localText(
                                    '\u041f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0442\u044c \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d',
                                    '\u041f\u04d9\u043d \u0441\u0438\u043f\u0430\u0442\u0442\u0430\u043c\u0430\u043b\u0430\u0440\u044b\u043d \u043a\u04e9\u0440\u0441\u0435\u0442\u0443',
                                    'Show course descriptions',
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

                        {currentPlan?.metrics?.verification && (
                            <div className="card" style={{ marginBottom: '20px', borderLeft: `5px solid ${currentPlan.metrics.verification.feasible ? '#2e7d32' : '#c62828'}` }}>
                                <h3 style={{ marginTop: 0 }}>{t('verification')}</h3>
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
                                        {bridgePreview?.variant === activeVariant && (bridgePreview.suggestions || []).some(row =>
                                            (row.candidates || []).some(c => (c.expert_score || 0) >= 0.5 || (c.model_score || 0) >= 0.65)
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
                                        {bridgePreview?.variant === activeVariant && (
                                            <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
                                                {bridgePreview.elapsed_seconds !== undefined && (
                                                    <div style={{ fontSize: 12, color: '#6d4c41' }}>
                                                        {localText(`Поиск замен выполнен за ${bridgePreview.elapsed_seconds}s.`, `Ауыстыруларды іздеу ${bridgePreview.elapsed_seconds}s ішінде орындалды.`, `Replacement search completed in ${bridgePreview.elapsed_seconds}s.`)}
                                                    </div>
                                                )}
                                                {(bridgePreview.suggestions || []).map(row => {
                                                    const good = (row.candidates || []).filter(c => c.strong_candidate)
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
                                                                                    <strong>→ {(c.title_translations || {})[language] || c.title}</strong>
                                                                                </label> · {c.credits} {t('credits')} · AI {Math.round((c.model_score || 0) * 100)}% · EPVO {Math.round((c.expert_score || 0) * 100)}% · LO {Math.round((c.coverage_ratio || 0) * 100)}%
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
                                                                            <strong>{candidate[`title_${language}`] || candidate.title_ru}</strong> · {row.credits} {t('credits')}
                                                                            <div style={{ marginTop: 3, color: '#5d6470', lineHeight: 1.35 }}>{candidate[`description_${language}`] || candidate.description_ru}</div>
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
                                {currentPlan.domain_breakdown && (
                                    <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8 }}>
                                        {Object.entries(currentPlan.domain_breakdown).filter(([, item]) => item.credits > 0 || item.min_percent > 0).map(([key, item]) => (
                                            <div key={key} style={{ padding: '8px 10px', borderRadius: 8, background: '#f6f9fc', border: '1px solid #e1e8f0' }}>
                                                <div style={{ fontSize: 12, color: '#667' }}>{item.label || key}</div>
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
                                <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#f8fbff', border: '1px solid #dce9f7' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                                        <div>
                                            <strong>{localText('Источники покрытия LO', 'LO қамту көздері', 'LO coverage sources')}</strong>
                                            <div style={{ fontSize: 12, color: '#566', marginTop: 2 }}>
                                                {localText('Показывает, какие результаты закрыты реальными дисциплинами, а какие только bridge-модулями.', 'Қай нәтижелер нақты пәндермен, қайсысы bridge-модульдермен жабылғанын көрсетеді.', 'Shows which outcomes are covered by real courses and which only by bridge modules.')}
                                            </div>
                                        </div>
                                        <button className="btn btn-secondary" onClick={loadLoCoverageSources} disabled={loadingLoCoverageSources}>
                                            {loadingLoCoverageSources ? localText('Загрузка…', 'Жүктеу…', 'Loading…') : localText('Показать LO-источники', 'LO көздерін көрсету', 'Show LO sources')}
                                        </button>
                                    </div>
                                    {loCoverageSources?.variant === activeVariant && (
                                        <div style={{ marginTop: 10 }}>
                                            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12 }}>
                                                <span>{localText('Всего LO', 'Барлық LO', 'Total LOs')}: <b>{loCoverageSources.summary?.los || 0}</b></span>
                                                <span style={{ color: '#2e7d32' }}>{localText('реальные дисциплины', 'нақты пәндер', 'real courses')}: <b>{loCoverageSources.summary?.real_confirmed || 0}</b></span>
                                                <span style={{ color: '#8a5a00' }}>bridge: <b>{loCoverageSources.summary?.bridge_supported || 0}</b></span>
                                                <span style={{ color: '#c62828' }}>{localText('слабые', 'әлсіз', 'weak')}: <b>{loCoverageSources.summary?.weak || 0}</b></span>
                                            </div>
                                            <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
                                                {(loCoverageSources.items || []).map(row => (
                                                    <details key={row.lo_code} style={{ padding: 8, borderRadius: 7, background: '#fff', border: '1px solid #e2edf7' }}>
                                                        <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                                                            {row.lo_code}: {Math.round((row.coverage || 0) * 100)}%
                                                            <span style={{
                                                                marginLeft: 8,
                                                                padding: '2px 7px',
                                                                borderRadius: 999,
                                                                fontSize: 11,
                                                                background: row.status === 'real_confirmed' ? '#e8f5e9' : row.status === 'bridge_supported' ? '#fff8e1' : '#ffebee',
                                                                color: row.status === 'real_confirmed' ? '#1b5e20' : row.status === 'bridge_supported' ? '#8a5a00' : '#b71c1c'
                                                            }}>
                                                                {row.status === 'real_confirmed' ? localText('реальная дисциплина', 'нақты пән', 'real course') : row.status === 'bridge_supported' ? 'bridge' : localText('слабое покрытие', 'әлсіз қамту', 'weak')}
                                                            </span>
                                                        </summary>
                                                        <div style={{ marginTop: 6, fontSize: 12, color: '#455' }}>{row.lo_text}</div>
                                                        <div style={{ marginTop: 5, padding: '6px 8px', borderRadius: 6, background: row.coverage_kind === 'bridge_target_assumption' ? '#fff8e1' : '#f5f8fb', fontSize: 11, color: '#5d6470' }}>
                                                            {row.coverage_explanation || (row.status === 'bridge_supported'
                                                                ? localText('75% — служебная оценка проектного bridge, а не экспертная оценка реальной дисциплины ЕПВО.', '75% — жобалық bridge қызметтік бағасы, нақты ЕПВО пәнінің сараптамалық бағасы емес.', '75% is a planning assumption for a proposed bridge, not an expert EPVO course score.')
                                                                : '')}
                                                        </div>
                                                        <div style={{ marginTop: 8, display: 'grid', gap: 4, fontSize: 12 }}>
                                                            {(row.real_sources || []).slice(0, 3).map(src => (
                                                                <div key={`real-${row.lo_code}-${src.course_id}`}>✓ {src.title} · {src.credits} {t('credits')} · AI {Math.round((src.score || 0) * 100)}% · EPVO {Math.round((src.expert_score || 0) * 100)}%</div>
                                                            ))}
                                                            {(row.bridge_sources || []).slice(0, 3).map(src => (
                                                                <div key={`bridge-${row.lo_code}-${src.bridge_id}`} style={{ color: '#8a5a00' }}>
                                                                    ↳ bridge в плане: {src.title} · {src.credits} {t('credits')} · {t('semester')} {src.semester}
                                                                    <button className="btn btn-secondary" style={{ marginLeft: 7, padding: '3px 7px', fontSize: 10 }} onClick={() => document.querySelector(`[data-plan-semester="${src.semester}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>
                                                                        {localText('Показать в плане', 'Жоспарда көрсету', 'Show in plan')}
                                                                    </button>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </details>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                                {currentPlan.suspicious_courses?.length > 0 && (
                                    <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082' }}>
                                        <strong>{localText('Сомнительные дисциплины', 'Күмәнді пәндер', 'Suspicious courses')}: {currentPlan.suspicious_courses.length}</strong>
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
                                                                {candidate.selection_reason && <div style={{ color: '#39704c', marginTop: 3 }}>{candidate.selection_reason}</div>}
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
                            </div>
                        )}
                        {currentPlan?.metrics?.verification?.goso_compliance?.applicable && (() => {
                            const goso = currentPlan.metrics.verification.goso_compliance
                            return <div className="card" style={{ marginBottom: 20, borderLeft: `5px solid ${goso.compliant ? '#2e7d32' : '#c62828'}` }}>
                                <h3 style={{ marginTop: 0 }}>{localText('Соответствие ГОСО Республики Казахстан', 'Қазақстан Республикасының МЖМБС сәйкестігі', 'Kazakhstan state-standard compliance')}</h3>
                                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                                    <span>{localText('Статус', 'Күйі', 'Status')}: <strong>{goso.compliant ? localText('соответствует', 'сәйкес', 'compliant') : localText('есть нарушения', 'бұзушылықтар бар', 'violations found')}</strong></span>
                                    <span>{localText('Обязательные кредиты', 'Міндетті кредиттер', 'Mandatory credits')}: <strong>{goso.mandatory_credits}</strong></span>
                                    <span>{localText('Уровень', 'Деңгей', 'Level')}: <strong>{goso.education_level}</strong></span>
                                </div>
                                {(goso.violations || []).map((item, index) => <div key={index} style={{ marginTop: 8, color: '#9b1c1c', fontSize: 13 }}>
                                    ⚠️ {item.title || item.reason}: {item.actual !== undefined ? `${item.actual} / ${item.required}` : ''}
                                </div>)}
                                <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>{goso.source}</div>
                            </div>
                        })()}
                        {currentPlan?.metrics?.verification?.pedagogical_audit && (() => {
                            const audit = currentPlan.metrics.verification.pedagogical_audit
                            return <div className="card" style={{ marginBottom: 20, borderLeft: `5px solid ${audit.passed ? '#2e7d32' : '#e67e22'}` }}>
                                <h3 style={{ marginTop: 0 }}>{localText('Автоматическая проверка качества плана', 'Жоспар сапасын автоматты тексеру', 'Automatic curriculum quality audit')}</h3>
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
                                {(audit.structural_foundations || []).slice(0, 5).map(row => <div key={`foundation-${row.course_id}`} style={{ marginTop: 7, fontSize: 12, color: '#315b7a' }}>
                                    ↳ {row.title} · {localText('не закрывает LO напрямую, но является подтверждённым пререквизитом', 'LO-ны тікелей жаппайды, бірақ расталған пререквизит', 'indirect LO support as a confirmed prerequisite')}
                                </div>)}
                                {(audit.semester_misplacements || []).slice(0, 5).map(row => <div key={`semester-${row.course_id}`} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                                    ⚠ {row.title}: {t('semester')} {row.semester} → {localText('рекомендуется', 'ұсынылады', 'recommended')} {row.recommended_semester}
                                </div>)}
                            </div>
                        })()}
                        {currentPlan?.metrics?.optimizer && (
                            <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #3949ab' }}>
                                <h3 style={{ marginTop: 0 }}>{t('optimizer')}</h3>
                                <strong>{currentPlan.metrics.optimizer.name}</strong>
                                {currentPlan.metrics.optimizer.selection_method === 'nsga2' && (
                                    <span style={{ marginLeft: '12px', color: '#555' }}>
                                        {t('optimizer_parameters')
                                            .replace('{population}', currentPlan.metrics.optimizer.population)
                                            .replace('{generations}', currentPlan.metrics.optimizer.generations)}
                                    </span>
                                )}
                            </div>
                        )}
                        {currentPlan?.metrics?.international_quality && (
                            <div className="card" style={{ marginBottom: '20px', borderLeft: `5px solid ${currentPlan.metrics.international_quality.passed ? '#2e7d32' : '#e67e22'}` }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '12px' }}>
                                    <div>
                                        <h3 style={{ margin: 0 }}>{t('international_quality')}</h3>
                                        <p style={{ margin: '6px 0 0', color: '#666', fontSize: '14px' }}>
                                            OBE / ABET-style continuous improvement / CDIO integrated curriculum / Tuning competences
                                        </p>
                                    </div>
                                    <div style={{ fontSize: '28px', fontWeight: 'bold', color: currentPlan.metrics.international_quality.passed ? '#2e7d32' : '#e67e22' }}>
                                        {currentPlan.metrics.international_quality.score}%
                                    </div>
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
                            </div>
                        )}
                        <div className="card">
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
                                                                {localizedCourseField(c.title_translations, c.title)}{c.translation_status === 'machine_reviewed' && <span title={t('ai_translation')} style={{marginLeft:5,color:'#9a5b00',fontSize:10}}>AI</span>}
                                                            </div>
                                                            {showCourseDescriptions && localizedCourseField(c.description_translations, c.description) && (
                                                                <div style={{ fontSize: '11px', color: '#777', marginTop: 3, lineHeight: 1.35 }}>
                                                                    {localizedCourseField(c.description_translations, c.description).slice(0, 220)}{localizedCourseField(c.description_translations, c.description).length > 220 ? '…' : ''}
                                                                </div>
                                                            )}
                                                            <div style={{ fontSize: '11px', color: '#666', marginTop: '2px' }}>
                                                                {c.academic_cycle && <>{localText('Цикл', 'Цикл', 'Cycle')}: <b>{c.academic_cycle}</b>{c.academic_cycle_source === 'inferred' ? ` (${localText('расчёт системы', 'жүйе есебі', 'system estimate')})` : ''}{' · '}</>}
                                                                {localText('Компонент', 'Компонент', 'Component')}: {c.academic_component || componentLabel(c.cycle_component || c.type)}
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
                                                                        <div>{c.why_selected.selection_reason}</div>
                                                                        <div>{c.why_selected.semester_reason}</div>
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
                    </div>
                )}
            </main>
        </div>
    )
}
