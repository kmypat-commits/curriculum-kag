import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import axios from 'axios'
import LoadingSpinner from '../components/LoadingSpinner'


function CompactSection({ title, subtitle, accent = '#366092', defaultOpen = false, children }) {
    return <details className="card" open={defaultOpen} style={{ marginBottom: 20, borderLeft: `5px solid ${accent}`, padding: 0, overflow: 'hidden' }}>
        <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 18px', display: 'flex', justifyContent: 'space-between', gap: 14, alignItems: 'center', background: '#fbfdff' }}>
            <span>
                <span style={{ display: 'block', fontWeight: 800, color: '#17233b' }}>{title}</span>
                {subtitle && <span style={{ display: 'block', marginTop: 3, fontSize: 12, color: '#667085', fontWeight: 400 }}>{subtitle}</span>}
            </span>
            <span style={{ fontSize: 12, color: '#667085', whiteSpace: 'nowrap' }}>{'\u041e\u0442\u043a\u0440\u044b\u0442\u044c / \u0441\u0432\u0435\u0440\u043d\u0443\u0442\u044c'}</span>
        </summary>
        <div style={{ padding: 18 }}>
            {children}
        </div>
    </details>
}

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
    const [expandedLoCourses, setExpandedLoCourses] = useState({})
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
        return detail || err?.message || localText('РќРµРёР·РІРµСЃС‚РЅР°СЏ РѕС€РёР±РєР°', 'Р‘РµР»РіС–СЃС–Р· Т›Р°С‚Рµ', 'Unknown error')
    }

    const localizeQualityEvidence = (text = '') => {
        if (language !== 'ru') return text
        const patterns = [
            [/^(\d+)\/(\d+) learning outcomes meet the coverage threshold\.$/, '$1/$2 СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ РѕР±СѓС‡РµРЅРёСЏ РґРѕСЃС‚РёРіР»Рё РїРѕСЂРѕРіР° РїРѕРєСЂС‹С‚РёСЏ.'],
            [/^Hard violations: (\d+)\.$/, 'Р–С‘СЃС‚РєРёС… РЅР°СЂСѓС€РµРЅРёР№: $1.'],
            [/^(\d+)\/(\d+) repository courses match the project domains\.$/, '$1/$2 РґРёСЃС†РёРїР»РёРЅ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓСЋС‚ РѕР±Р»Р°СЃС‚СЏРј РїСЂРѕРµРєС‚Р°.'],
            [/^(\d+)\/(\d+) courses are supported by the selected EPVO scope, programme LO evidence, or RK mandatory requirements\.$/, '$1/$2 РґРёСЃС†РёРїР»РёРЅ РїРѕРґС‚РІРµСЂР¶РґРµРЅС‹ РІС‹Р±СЂР°РЅРЅС‹Рј РЅР°РїСЂР°РІР»РµРЅРёРµРј Р•РџР’Рћ, СЃРІСЏР·СЊСЋ СЃ СЂРµР·СѓР»СЊС‚Р°С‚Р°РјРё РѕР±СѓС‡РµРЅРёСЏ РёР»Рё РѕР±СЏР·Р°С‚РµР»СЊРЅС‹РјРё С‚СЂРµР±РѕРІР°РЅРёСЏРјРё Р Рљ.'],
            [/^Interdisciplinary\/bridge units: (\d+)\.$/, 'РњРµР¶РґРёСЃС†РёРїР»РёРЅР°СЂРЅС‹С…/bridge-РјРѕРґСѓР»РµР№: $1.'],
            [/^Not applicable: this is a standard single-direction programme\.$/, 'РќРµ РїСЂРёРјРµРЅСЏРµС‚СЃСЏ: СЌС‚Рѕ СЃС‚Р°РЅРґР°СЂС‚РЅР°СЏ РїСЂРѕРіСЂР°РјРјР° РѕРґРЅРѕРіРѕ РЅР°РїСЂР°РІР»РµРЅРёСЏ.'],
            [/^(\d+)\/(\d+) learning units include assessment methods\.$/, '$1/$2 СѓС‡РµР±РЅС‹С… РµРґРёРЅРёС† СЃРѕРґРµСЂР¶Р°С‚ РјРµС‚РѕРґС‹ РѕС†РµРЅРёРІР°РЅРёСЏ.'],
            [/^Promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'РџРѕРґС‚РІРµСЂР¶РґРµРЅРёР№ bridge-РјРѕРґСѓР»РµР№: $1; bridge-РјРѕРґСѓР»РµР№ РІ РїР»Р°РЅРµ: $2.'],
            [/^Expert feedback: (\d+); promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Р­РєСЃРїРµСЂС‚РЅС‹С… РѕС†РµРЅРѕРє: $1; РїРѕРґС‚РІРµСЂР¶РґРµРЅРёР№ bridge-РјРѕРґСѓР»РµР№: $2; bridge-РјРѕРґСѓР»РµР№ РІ РїР»Р°РЅРµ: $3.'],
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
        if (['elective', 'elective component', 'РєРѕРјРїРѕРЅРµРЅС‚ РїРѕ РІС‹Р±РѕСЂСѓ'].includes(normalized)) return t('elective')
        if (['university', 'university component', 'РІСѓР·РѕРІСЃРєРёР№ РєРѕРјРїРѕРЅРµРЅС‚'].includes(normalized)) return t('university')
        return t('mandatory')
    }

    const buildStageLabel = (stage = 'idle') => {
        const dictionary = {
            ru: {
                idle: 'РћР¶РёРґР°РЅРёРµ',
                matching: 'РЎРѕРїРѕСЃС‚Р°РІР»СЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹ РѕР±СѓС‡РµРЅРёСЏ СЃ РґРёСЃС†РёРїР»РёРЅР°РјРё',
                epvo_repository: 'РџРѕРґС‚СЏРіРёРІР°РµРј РґРёСЃС†РёРїР»РёРЅС‹ Р•РџР’Рћ РїРѕ РІС‹Р±СЂР°РЅРЅС‹Рј РЅР°РїСЂР°РІР»РµРЅРёСЏРј',
                scoring: 'РћС†РµРЅРёРІР°РµРј СЃРІСЏР·Рё РґРёСЃС†РёРїР»РёРЅР°вЂ“СЂРµР·СѓР»СЊС‚Р°С‚ РѕР±СѓС‡РµРЅРёСЏ',
                variants: 'Р“РѕС‚РѕРІРёРј РІР°СЂРёР°РЅС‚С‹ A/B/C',
                variant_A_start: 'РЎС‚СЂРѕРёРј РІР°СЂРёР°РЅС‚ A',
                variant_A: 'РџСЂРѕРІРµСЂСЏРµРј РІР°СЂРёР°РЅС‚ A',
                variant_B_start: 'РЎС‚СЂРѕРёРј РІР°СЂРёР°РЅС‚ B',
                variant_B: 'РџСЂРѕРІРµСЂСЏРµРј РІР°СЂРёР°РЅС‚ B',
                variant_C_start: 'РЎС‚СЂРѕРёРј РІР°СЂРёР°РЅС‚ C',
                variant_C: 'РџСЂРѕРІРµСЂСЏРµРј РІР°СЂРёР°РЅС‚ C',
                saving: 'РЎРѕС…СЂР°РЅСЏРµРј РЅРѕРІС‹Рµ РїР»Р°РЅС‹ Р±РµР· РїРѕСЂС‡Рё СЃС‚Р°СЂРѕРіРѕ Р°РєС‚РёРІРЅРѕРіРѕ',
                complete: 'Р“РѕС‚РѕРІРѕ',
                failed: 'РћС€РёР±РєР°',
            },
            kk: {
                idle: 'РљТЇС‚Сѓ',
                matching: 'РћТ›Сѓ РЅУ™С‚РёР¶РµР»РµСЂС–РЅ РїУ™РЅРґРµСЂРјРµРЅ СЃУ™Р№РєРµСЃС‚РµРЅРґС–СЂСѓ',
                epvo_repository: 'РўР°ТЈРґР°Р»Т“Р°РЅ Р±Р°Т“С‹С‚С‚Р°СЂ Р±РѕР№С‹РЅС€Р° Р•РџР’Рћ РїУ™РЅРґРµСЂС–РЅ Т›РѕСЃСѓ',
                scoring: 'РџУ™РЅвЂ“РѕТ›Сѓ РЅУ™С‚РёР¶РµСЃС– Р±Р°Р№Р»Р°РЅС‹СЃС‚Р°СЂС‹РЅ Р±Р°Т“Р°Р»Р°Сѓ',
                variants: 'A/B/C РЅТ±СЃТ›Р°Р»Р°СЂС‹РЅ РґР°Р№С‹РЅРґР°Сѓ',
                variant_A_start: 'A РЅТ±СЃТ›Р°СЃС‹РЅ Т›Т±СЂСѓ',
                variant_A: 'A РЅТ±СЃТ›Р°СЃС‹РЅ С‚РµРєСЃРµСЂСѓ',
                variant_B_start: 'B РЅТ±СЃТ›Р°СЃС‹РЅ Т›Т±СЂСѓ',
                variant_B: 'B РЅТ±СЃТ›Р°СЃС‹РЅ С‚РµРєСЃРµСЂСѓ',
                variant_C_start: 'C РЅТ±СЃТ›Р°СЃС‹РЅ Т›Т±СЂСѓ',
                variant_C: 'C РЅТ±СЃТ›Р°СЃС‹РЅ С‚РµРєСЃРµСЂСѓ',
                saving: 'Р•СЃРєС– Р±РµР»СЃРµРЅРґС– Р¶РѕСЃРїР°СЂРґС‹ Р±Т±Р·Р±Р°Р№ Р¶Р°ТЈР° Р¶РѕСЃРїР°СЂР»Р°СЂРґС‹ СЃР°Т›С‚Р°Сѓ',
                complete: 'Р”Р°Р№С‹РЅ',
                failed: 'ТљР°С‚Рµ',
            },
            en: {
                idle: 'Waiting',
                matching: 'Matching learning outcomes with courses',
                epvo_repository: 'Adding EPVO courses for selected fields',
                scoring: 'Scoring courseвЂ“learning outcome links',
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
            const linkWord = language === 'kk' ? 'Р±Р°Р№Р»Р°РЅС‹СЃ' : language === 'en' ? 'links' : 'СЃРІСЏР·РµР№'
            return `LO ${buildStatus.lo_index}/${buildStatus.lo_total}${buildStatus.lo_code ? ` вЂ” ${buildStatus.lo_code}` : ''}${buildStatus.matches ? `, ${linkWord}: ${buildStatus.matches}` : ''}`
        }
        if (buildStatus.stage?.startsWith?.('variant_')) {
            if (language === 'kk') return 'РџУ™РЅРґРµСЂ С‚Р°ТЈРґР°Р»С‹Рї, РєСЂРµРґРёС‚С‚РµСЂ, РїСЂРµСЂРµРєРІРёР·РёС‚С‚РµСЂ Р¶У™РЅРµ РґРѕРјРµРЅ С€РµРєС‚РµСѓР»РµСЂС– С‚РµРєСЃРµСЂС–Р»С–Рї Р¶Р°С‚С‹СЂ.'
            if (language === 'en') return 'Selecting courses and checking credits, prerequisites, and domain constraints.'
            return 'РРґС‘С‚ РїРѕРґР±РѕСЂ РґРёСЃС†РёРїР»РёРЅ, РїСЂРѕРІРµСЂРєР° РєСЂРµРґРёС‚РѕРІ, РїСЂРµСЂРµРєРІРёР·РёС‚РѕРІ Рё РґРѕРјРµРЅРЅС‹С… РѕРіСЂР°РЅРёС‡РµРЅРёР№.'
        }
        return null
    }

    const buildElapsedLabel = () => {
        const total = Math.max(0, Math.round(Number(buildStatus.elapsed_seconds) || 0))
        if (!total) return null
        const minutes = Math.floor(total / 60)
        const seconds = total % 60
        const value = minutes ? `${minutes} ${language === 'en' ? 'min' : 'РјРёРЅ'} ${seconds} ${language === 'en' ? 'sec' : 'СЃРµРє'}` : `${seconds} ${language === 'en' ? 'sec' : 'СЃРµРє'}`
        if (language === 'kk') return `УЁС‚РєРµРЅ СѓР°Т›С‹С‚: ${value}`
        if (language === 'en') return `Elapsed: ${value}`
        return `РџСЂРѕС€Р»Рѕ: ${value}`
    }

    const buildAlreadyRunningText = () => {
        if (language === 'kk') return 'ТљТ±СЂСѓ РїСЂРѕС†РµСЃС– Р¶ТЇСЂС–Рї Р¶Р°С‚С‹СЂ. РђТ“С‹РјРґР°Т“С‹ РїСЂРѕС†РµСЃСЃ Р°СЏТ›С‚Р°Р»Т“Р°РЅС‹РЅ РєТЇС‚С–ТЈС–Р·.'
        if (language === 'en') return 'Plan generation is already running. Please wait for the current process to finish.'
        return 'РџРѕСЃС‚СЂРѕРµРЅРёРµ СѓР¶Рµ РёРґС‘С‚. Р”РѕР¶РґРёС‚РµСЃСЊ Р·Р°РІРµСЂС€РµРЅРёСЏ С‚РµРєСѓС‰РµРіРѕ РїСЂРѕС†РµСЃСЃР°.'
    }

    const buildLongRunningHint = () => {
        if (language === 'kk') return 'Р•РџР’Рћ Р±Р°Р·Р°СЃС‹ ТЇР»РєРµРЅ Р±РѕР»СЃР°, Р±Т±Р» РєРµР·РµТЈ Р±С–СЂРЅРµС€Рµ РјРёРЅСѓС‚Т›Р° СЃРѕР·С‹Р»СѓС‹ РјТЇРјРєС–РЅ. Р•СЃРєС– Р±РµР»СЃРµРЅРґС– Р¶РѕСЃРїР°СЂ Р±Р°СЂР»С‹Т› РЅТ±СЃТ›Р°Р»Р°СЂ СЃУ™С‚С‚С– Т›Т±СЂС‹Р»Т“Р°РЅС€Р° СЃР°Т›С‚Р°Р»Р°РґС‹.'
        if (language === 'en') return 'If the EPVO catalogue is large, this step may take several minutes. The old active plan is kept until all variants are built successfully.'
        return 'Р•СЃР»Рё Р±Р°Р·Р° Р•РџР’Рћ Р±РѕР»СЊС€Р°СЏ, СЌС‚Р°Рї РјРѕР¶РµС‚ РёРґС‚Рё РЅРµСЃРєРѕР»СЊРєРѕ РјРёРЅСѓС‚. РЎС‚Р°СЂС‹Р№ Р°РєС‚РёРІРЅС‹Р№ РїР»Р°РЅ СЃРѕС…СЂР°РЅСЏРµС‚СЃСЏ РґРѕ СѓСЃРїРµС€РЅРѕРіРѕ РїРѕСЃС‚СЂРѕРµРЅРёСЏ РІСЃРµС… РІР°СЂРёР°РЅС‚РѕРІ.'
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

    const fetchVariants = async (versionId, includeDescriptions = showCourseDescriptions) => {
        try {
            const variantsRes = await axios.get(`/api/planner/${versionId}/variants`, {
                params: { include_descriptions: includeDescriptions },
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
                    ? `${t('quality_improvements_applied')} ${protectedCount} Р“РћРЎРћ-РєРѕРјРїРѕРЅРµРЅС‚РѕРІ Р·Р°С‰РёС‰РµРЅС‹; РїРµСЂРµСЃР±РѕСЂРєР° РЅРµ С‚СЂРµР±СѓРµС‚СЃСЏ.`
                    : `${t('quality_improvements_applied')} РџРµСЂРµСЃР±РѕСЂРєР° РЅРµ С‚СЂРµР±СѓРµС‚СЃСЏ.`
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
                    `РЎРІСЏР·Рё РґРёСЃС†РёРїР»РёРЅР°вЂ“LO РїРµСЂРµСЃС‡РёС‚Р°РЅС‹: ${response.data?.total_matches || 0}. РўРµРїРµСЂСЊ РјРѕР¶РЅРѕ РїРµСЂРµСЃС‚СЂРѕРёС‚СЊ РІР°СЂРёР°РЅС‚С‹.`,
                    `РџУ™РЅвЂ“LO Р±Р°Р№Р»Р°РЅС‹СЃС‚Р°СЂС‹ Т›Р°Р№С‚Р° РµСЃРµРїС‚РµР»РґС–: ${response.data?.total_matches || 0}. Р•РЅРґС– РЅТ±СЃТ›Р°Р»Р°СЂРґС‹ Т›Р°Р№С‚Р° Т›Т±СЂСѓТ“Р° Р±РѕР»Р°РґС‹.`,
                    `CourseвЂ“LO links recomputed: ${response.data?.total_matches || 0}. You can now rebuild variants.`,
                )
            })
        } catch (err) {
            setBuildStatus({ state: 'failed', stage: 'failed', progress: 0, error: errorMessage(err) })
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРµСЂРµСЃС‡РёС‚Р°С‚СЊ СЃРІСЏР·Рё', 'Р‘Р°Р№Р»Р°РЅС‹СЃС‚Р°СЂРґС‹ Т›Р°Р№С‚Р° РµСЃРµРїС‚РµСѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not recompute links') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ preview Р·Р°РјРµРЅС‹ bridge', 'Bridge Р°СѓС‹СЃС‚С‹СЂСѓ preview Р°Р»Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not load bridge replacement preview') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'success', text: response.data?.message || localText('Р”РёСЃС†РёРїР»РёРЅР° РґРѕР±Р°РІР»РµРЅР° РІ РїР»Р°РЅ.', 'РџУ™РЅ Р¶РѕСЃРїР°СЂТ“Р° Т›РѕСЃС‹Р»РґС‹.', 'Course added to the plan.') })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РјРµРЅРёС‚СЊ bridge-РјРѕРґСѓР»СЊ', 'Bridge-РјРѕРґСѓР»СЊРґС– Р°СѓС‹СЃС‚С‹СЂСѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not replace bridge module') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РјР°СЃСЃРѕРІРѕ Р·Р°РјРµРЅРёС‚СЊ bridge-РјРѕРґСѓР»Рё', 'Bridge-РјРѕРґСѓР»СЊРґРµСЂРґС– Р¶Р°РїРїР°Р№ Р°СѓС‹СЃС‚С‹СЂСѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not replace bridge modules') + ': ' + (errorMessage(err)) })
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
                ? localText(`Р’С‹Р±СЂР°РЅРѕ СЃСЂРµРґРЅРёС… Р·Р°РјРµРЅ: ${Object.keys(selected).length}. РџСЂРѕРІРµСЂСЊС‚Рµ СЃРїРёСЃРѕРє Рё РЅР°Р¶РјРёС‚Рµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ.`, `РћСЂС‚Р°С€Р° Р°СѓС‹СЃС‚С‹СЂСѓР»Р°СЂ С‚Р°ТЈРґР°Р»РґС‹: ${Object.keys(selected).length}. РўС–Р·С–РјРґС– С‚РµРєСЃРµСЂС–Рї, СЂР°СЃС‚Р°ТЈС‹Р·.`, `Selected medium replacements: ${Object.keys(selected).length}. Review and confirm.`)
                : localText('РЎСЂРµРґРЅРёС… Р·Р°РјРµРЅ РїРѕРєР° РЅРµС‚.', 'РћСЂС‚Р°С€Р° Р°СѓС‹СЃС‚С‹СЂСѓР»Р°СЂ Р¶РѕТ›.', 'No medium replacements available.'),
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРѕР±СЂР°С‚СЊ РґРёСЃС†РёРїР»РёРЅС‹ С‡РµСЂРµР· РР', 'Р–Р Р°СЂТ›С‹Р»С‹ РїУ™РЅРґРµСЂРґС– С‚Р°ТЈРґР°Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not generate AI course candidates') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґС‚РІРµСЂРґРёС‚СЊ РґРёСЃС†РёРїР»РёРЅСѓ', 'РџУ™РЅРґС– СЂР°СЃС‚Р°Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not confirm the course') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РёР·РјРµРЅРёС‚СЊ РёСЃРєР»СЋС‡РµРЅРёРµ РґРёСЃС†РёРїР»РёРЅС‹', 'РџУ™РЅРґС– Р°Р»С‹Рї С‚Р°СЃС‚Р°Сѓ Р±РµР»РіС–СЃС–РЅ У©Р·РіРµСЂС‚Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not update course exclusion') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'success', text: response.data?.message || `${title}: РїРѕРґС‚РІРµСЂР¶РґРµРЅРѕ СЌРєСЃРїРµСЂС‚РѕРј` })
            await fetchVariants(versionId)
        } catch (err) {
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґС‚РІРµСЂРґРёС‚СЊ РґРёСЃС†РёРїР»РёРЅСѓ', 'РџУ™РЅРґС– СЂР°СЃС‚Р°Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not confirm the course') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРѕР±СЂР°С‚СЊ Р·Р°РјРµРЅС‹', 'РђСѓС‹СЃС‚С‹СЂСѓР»Р°СЂРґС‹ С‚Р°ТЈРґР°Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not find replacements') + ': ' + (errorMessage(err)) })
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
                    ? localText(`РџРѕРґРѕР±СЂР°РЅС‹ Р·Р°РјРµРЅС‹ РґР»СЏ ${ok} РґРёСЃС†РёРїР»РёРЅ.`, `${ok} РїУ™РЅ ТЇС€С–РЅ Р°СѓС‹СЃС‚С‹СЂСѓР»Р°СЂ С‚Р°ТЈРґР°Р»РґС‹.`, `Loaded replacements for ${ok} courses.`)
                    : localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРѕР±СЂР°С‚СЊ Р·Р°РјРµРЅС‹ РґР»СЏ РІРёРґРёРјС‹С… РґРёСЃС†РёРїР»РёРЅ.', 'РљУ©СЂС–РЅРµС‚С–РЅ РїУ™РЅРґРµСЂ ТЇС€С–РЅ Р°СѓС‹СЃС‚С‹СЂСѓ С‚Р°Р±С‹Р»РјР°РґС‹.', 'Could not load replacements for visible courses.'),
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґС‚РІРµСЂРґРёС‚СЊ Р·Р°РјРµРЅСѓ', 'РђСѓС‹СЃС‚С‹СЂСѓРґС‹ СЂР°СЃС‚Р°Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not confirm replacement') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РёСЃС‚РѕС‡РЅРёРєРё РїРѕРєСЂС‹С‚РёСЏ LO', 'LO Т›Р°РјС‚Сѓ РєУ©Р·РґРµСЂС–РЅ Р°Р»Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not load LO coverage sources') + ': ' + (errorMessage(err)) })
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
            setBuildNotice({ type: 'error', text: localText('РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕС…СЂР°РЅРёС‚СЊ СЌРєСЃРїРµСЂС‚РЅСѓСЋ РѕС†РµРЅРєСѓ', 'РЎР°СЂР°РїС€С‹ Р±Р°Т“Р°СЃС‹РЅ СЃР°Т›С‚Р°Сѓ РјТЇРјРєС–РЅ Р±РѕР»РјР°РґС‹', 'Could not save expert feedback') + ': ' + (errorMessage(err)) })
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
                        <Link to={`/projects/${id}`} style={{ textDecoration: 'none', color: '#666' }}>в†ђ {t('open')}</Link>
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
                            {building ? `${t('building_plan')} ${buildProgress}%` : 'вњЁ ' + t('generate_variants')}
                        </button>
                        <button
                            className="btn btn-secondary"
                            onClick={handleRecomputeMatches}
                            disabled={building || recomputingMatches}
                        >
                            {recomputingMatches ? `${buildProgress}%` : localText('РџРµСЂРµСЃС‡РёС‚Р°С‚СЊ LO-СЃРІСЏР·Рё', 'LO Р±Р°Р№Р»Р°РЅС‹СЃС‚Р°СЂС‹РЅ Т›Р°Р№С‚Р° РµСЃРµРїС‚РµСѓ', 'Recompute LO links')}
                        </button>
                    </div>
                </div>
            </header>

            <main className="container workspace-main" style={{ paddingTop: '30px' }}>
                {epvoApplied && !building && (
                    <div className="card" style={{ marginBottom: '20px', borderLeft: '5px solid #366092' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div>
                                <strong>{localText('EPVO-РєР°РЅРґРёРґР°С‚С‹ РґРѕР±Р°РІР»РµРЅС‹', 'Р•РџР’Рћ РєР°РЅРґРёРґР°С‚С‚Р°СЂС‹ Т›РѕСЃС‹Р»РґС‹', 'EPVO candidates added')}</strong>
                                <div style={{ color: '#667', fontSize: 13, marginTop: 4 }}>
                                    {localText('РќР°Р¶РјРёС‚Рµ вЂњРџРѕСЃС‚СЂРѕРёС‚СЊ РІР°СЂРёР°РЅС‚С‹вЂќ, С‡С‚РѕР±С‹ A/B/C РёСЃРїРѕР»СЊР·РѕРІР°Р»Рё РЅРѕРІС‹Рµ РґРёСЃС†РёРїР»РёРЅС‹.', 'Р–Р°ТЈР° РїУ™РЅРґРµСЂ A/B/C РЅТ±СЃТ›Р°Р»Р°СЂС‹РЅРґР° Т›РѕР»РґР°РЅС‹Р»СѓС‹ ТЇС€С–РЅ вЂњРќТ±СЃТ›Р°Р»Р°СЂРґС‹ Т›Т±СЂСѓвЂќ С‚ТЇР№РјРµСЃС–РЅ Р±Р°СЃС‹ТЈС‹Р·.', 'Click вЂњBuild variantsвЂќ so A/B/C can use the new courses.')}
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
                                <strong>{localText('Р•СЃС‚СЊ РёР·РјРµРЅРµРЅРёСЏ РґР»СЏ СЃР»РµРґСѓСЋС‰РµР№ РіРµРЅРµСЂР°С†РёРё', 'РљРµР»РµСЃС– Т›Т±СЂСѓ ТЇС€С–РЅ У©Р·РіРµСЂС–СЃС‚РµСЂ Р±Р°СЂ', 'Changes are ready for the next generation')}</strong>
                                <div style={{ color: '#6d4c41', fontSize: 13, marginTop: 4 }}>
                                    {localText('РЎРёСЃС‚РµРјР° СѓС‡С‚С‘С‚ Р·Р°РјРµРЅС‹ bridge Рё РѕС‚РјРµС‡РµРЅРЅС‹Рµ РёСЃРєР»СЋС‡РµРЅРёСЏ, Р·Р°С‚РµРј Р·Р°РЅРѕРІРѕ СЂР°СЃСЃС‡РёС‚Р°РµС‚ A/B/C, РєСЂРµРґРёС‚С‹, Р Рћ Рё РїСЂРµСЂРµРєРІРёР·РёС‚С‹.', 'Р–ТЇР№Рµ bridge Р°СѓС‹СЃС‚С‹СЂСѓР»Р°СЂС‹РЅ Р¶У™РЅРµ Р±РµР»РіС–Р»РµРЅРіРµРЅ Р°Р»С‹Рї С‚Р°СЃС‚Р°СѓР»Р°СЂРґС‹ РµСЃРєРµСЂС–Рї, A/B/C, РєСЂРµРґРёС‚С‚РµСЂ, РћРќ Р¶У™РЅРµ РїСЂРµСЂРµРєРІРёР·РёС‚С‚РµСЂРґС– Т›Р°Р№С‚Р° РµСЃРµРїС‚РµР№РґС–.', 'The system will apply bridge replacements and exclusions, then recalculate A/B/C, credits, LOs, and prerequisites.')}
                                </div>
                            </div>
                            <button className="btn btn-primary" onClick={handleBuild}>
                                {localText('РџРµСЂРµРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ A/B/C', 'A/B/C Т›Р°Р№С‚Р° Т›Т±СЂСѓ', 'Regenerate A/B/C')}
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
                        <h3 style={{ marginTop: 0 }}>{localText('Р§С‚Рѕ РёР·РјРµРЅРёР»РѕСЃСЊ РїРѕСЃР»Рµ РїРµСЂРµСЃС‚СЂРѕР№РєРё', 'ТљР°Р№С‚Р° Т›Т±СЂСѓРґР°РЅ РєРµР№С–РЅ РЅРµ У©Р·РіРµСЂРґС–', 'What changed after rebuild')}</h3>
                        <div className="quick-grid">
                            <div><b>{localText('РљСЂРµРґРёС‚С‹', 'РљСЂРµРґРёС‚С‚РµСЂ', 'Credits')}</b><br />{changeReport.credits_delta > 0 ? '+' : ''}{changeReport.credits_delta}</div>
                            <div><b>Bridge</b><br />{changeReport.bridges_delta > 0 ? '+' : ''}{changeReport.bridges_delta}</div>
                            <div><b>Min LO</b><br />{changeReport.min_lo_delta == null ? 'вЂ”' : `${changeReport.min_lo_delta > 0 ? '+' : ''}${Math.round(changeReport.min_lo_delta * 100)}%`}</div>
                            <div><b>{localText('РљР°С‡РµСЃС‚РІРѕ', 'РЎР°РїР°', 'Quality')}</b><br />{String(changeReport.quality_before)} в†’ {String(changeReport.quality_after)}</div>
                        </div>
                        <p style={{ color: '#667', fontSize: 13, marginTop: 10 }}>
                            {localText('Р”РѕР±Р°РІР»РµРЅРѕ', 'ТљРѕСЃС‹Р»РґС‹', 'Added')}: {changeReport.added_count}; {localText('СѓРґР°Р»РµРЅРѕ', 'Р¶РѕР№С‹Р»РґС‹', 'removed')}: {changeReport.removed_count}; hard: {changeReport.hard_before} в†’ {changeReport.hard_after}.
                        </p>
                        {(changeReport.added_titles_sample?.length > 0 || changeReport.removed_titles_sample?.length > 0) && (
                            <details style={{ marginTop: 8 }}>
                                <summary style={{ cursor: 'pointer', color: '#366092', fontWeight: 600 }}>{localText('РџРѕРєР°Р·Р°С‚СЊ РїСЂРёРјРµСЂС‹ РёР·РјРµРЅРµРЅРёР№', 'УЁР·РіРµСЂС–СЃС‚РµСЂ РјС‹СЃР°Р»РґР°СЂС‹РЅ РєУ©СЂСЃРµС‚Сѓ', 'Show change examples')}</summary>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8, fontSize: 12 }}>
                                    <div><b>{localText('Р”РѕР±Р°РІР»РµРЅРѕ', 'ТљРѕСЃС‹Р»РґС‹', 'Added')}</b>{(changeReport.added_titles_sample || []).map((title, index) => <div key={`a-${index}`}>+ {title}</div>)}</div>
                                    <div><b>{localText('РЈРґР°Р»РµРЅРѕ', 'Р–РѕР№С‹Р»РґС‹', 'Removed')}</b>{(changeReport.removed_titles_sample || []).map((title, index) => <div key={`r-${index}`}>в€’ {title}</div>)}</div>
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
                                    onChange={(event) => handleShowCourseDescriptionsChange(event.target.checked)}
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
                            <CompactSection title={t('verification')} accent={currentPlan.metrics.verification.feasible ? '#2e7d32' : '#c62828'} defaultOpen={false}>
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
                                        {applyingQuality ? t('applying_quality_improvements') : localText('РСЃРїСЂР°РІРёС‚СЊ РїРѕСЂСЏРґРѕРє, РЅР°РіСЂСѓР·РєСѓ Рё РєСЂРµРґРёС‚С‹', 'Р РµС‚С‚С–, Р¶ТЇРєС‚РµРјРµРЅС– Р¶У™РЅРµ РєСЂРµРґРёС‚С‚РµСЂРґС– С‚ТЇР·РµС‚Сѓ', 'Fix order, load, and credits')}
                                    </button>
                                )}
                                {(currentPlan.metrics.num_bridge_modules || 0) > 0 && (
                                    <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#fff8e1', border: '1px solid #ffe082', color: '#6d4c41' }}>
                                        <strong>{localText('Bridge-РјРѕРґСѓР»Рё С‚СЂРµР±СѓСЋС‚ СЌРєСЃРїРµСЂС‚РЅРѕРіРѕ СЂРµС€РµРЅРёСЏ', 'Bridge-РјРѕРґСѓР»СЊРґРµСЂ СЃР°СЂР°РїС‚Р°РјР°Р»С‹Т› С€РµС€С–РјРґС– Т›Р°Р¶РµС‚ РµС‚РµРґС–', 'Bridge modules require expert review')}: {currentPlan.metrics.num_bridge_modules}</strong>
                                        <div style={{ fontSize: 12, marginTop: 4 }}>
                                            {localText(
                                                'Р­С‚Рѕ Р·РЅР°С‡РёС‚, С‡С‚Рѕ СЂРµР°Р»СЊРЅС‹С… РґРёСЃС†РёРїР»РёРЅ Р•РџР’Рћ РЅРµ С…РІР°С‚РёР»Рѕ РґР»СЏ С‡Р°СЃС‚Рё LO РёР»Рё РЅР°РіСЂСѓР·РєРё. Р›СѓС‡С€Рµ РїРµСЂРµРЅР°СЃС‚СЂРѕРёС‚СЊ Р•РџР’Рћ-РЅР°РїСЂР°РІР»РµРЅРёРµ РёР»Рё Р·Р°РјРµРЅРёС‚СЊ bridge СЂРµР°Р»СЊРЅС‹РјРё РґРёСЃС†РёРїР»РёРЅР°РјРё.',
                                                'Р‘Т±Р» РєРµР№Р±С–СЂ LO РЅРµРјРµСЃРµ Р¶ТЇРєС‚РµРјРµ ТЇС€С–РЅ РЅР°Т›С‚С‹ Р•РџР’Рћ РїУ™РЅРґРµСЂС– Р¶РµС‚РєС–Р»С–РєСЃС–Р· РµРєРµРЅС–РЅ Р±С–Р»РґС–СЂРµРґС–. Р•РџР’Рћ Р±Р°Т“С‹С‚С‹РЅ Т›Р°Р№С‚Р° Р±Р°РїС‚Р°Сѓ РЅРµРјРµСЃРµ bridge РѕСЂРЅС‹РЅР° РЅР°Т›С‚С‹ РїУ™РЅРґРµСЂРґС– С‚Р°ТЈРґР°Сѓ Т±СЃС‹РЅС‹Р»Р°РґС‹.',
                                                'This means real EPVO courses were insufficient for some LOs or workload. Reconfigure the EPVO scope or replace bridges with real courses.'
                                            )}
                                        </div>
                                        <button className="btn btn-secondary" onClick={loadBridgePreview} disabled={loadingBridgePreview} style={{ marginTop: 8 }}>
                                            {loadingBridgePreview ? localText('РџРѕРёСЃРєвЂ¦', 'Р†Р·РґРµСѓвЂ¦', 'SearchingвЂ¦') : localText('РќР°Р№С‚Рё СЂРµР°Р»СЊРЅС‹Рµ РґРёСЃС†РёРїР»РёРЅС‹ РІРјРµСЃС‚Рѕ bridge', 'Bridge РѕСЂРЅС‹РЅР° РЅР°Т›С‚С‹ РїУ™РЅРґРµСЂРґС– С‚Р°Р±Сѓ', 'Find real courses instead of bridges')}
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
                                                    ? localText('Р—Р°РјРµРЅР°вЂ¦', 'РђСѓС‹СЃС‚С‹СЂСѓвЂ¦', 'ReplacingвЂ¦')
                                                    : Object.keys(selectedBridgeReplacements).length
                                                        ? localText(`РџРѕРґС‚РІРµСЂРґРёС‚СЊ РІС‹Р±СЂР°РЅРЅС‹Рµ: ${Object.keys(selectedBridgeReplacements).length}`, `РўР°ТЈРґР°Р»Т“Р°РЅРґР°СЂРґС‹ СЂР°СЃС‚Р°Сѓ: ${Object.keys(selectedBridgeReplacements).length}`, `Confirm selected: ${Object.keys(selectedBridgeReplacements).length}`)
                                                        : localText('Р—Р°РјРµРЅРёС‚СЊ РІСЃРµ РїРѕРґС…РѕРґСЏС‰РёРµ bridge', 'Р‘Р°СЂР»С‹Т› Т›РѕР»Р°Р№Р»С‹ bridge-РјРѕРґСѓР»СЊРґРµСЂРґС– Р°СѓС‹СЃС‚С‹СЂСѓ', 'Replace all suitable bridges')}
                                            </button>
                                        )}
                                        {bridgePreview?.variant === activeVariant && (bridgePreview.suggestions || []).some(row => (row.candidates || []).some(c => c.quality_level === 'medium' || c.medium_candidate)) && (
                                            <button
                                                className="btn btn-secondary"
                                                onClick={selectMediumBridgeReplacements}
                                                disabled={replacingAllBridges || Boolean(replacingBridge)}
                                                style={{ marginTop: 8, marginLeft: 8, borderColor: '#c17b00', color: '#8a5a00' }}
                                            >
                                                {localText('Р’С‹Р±СЂР°С‚СЊ РІСЃРµ СЃСЂРµРґРЅРёРµ Р·Р°РјРµРЅС‹', 'Р‘Р°СЂР»С‹Т› РѕСЂС‚Р°С€Р° Р°СѓС‹СЃС‚С‹СЂСѓР»Р°СЂРґС‹ С‚Р°ТЈРґР°Сѓ', 'Select all medium replacements')}
                                            </button>
                                        )}
                                        {bridgePreview?.variant === activeVariant && (
                                            <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
                                                {bridgePreview.summary && (
                                                    <div style={{ padding: '8px 10px', borderRadius: 8, background: '#fff3cd', border: '1px solid #ffecb5', color: '#6d4c00', fontSize: 12 }}>
                                                        <strong>{localText('РС‚РѕРі РїРѕРёСЃРєР° Р·Р°РјРµРЅ', 'РђСѓС‹СЃС‚С‹СЂСѓ С–Р·РґРµСѓ Т›РѕСЂС‹С‚С‹РЅРґС‹СЃС‹', 'Replacement search summary')}:</strong>{' '}
                                                        {localText(
                                                            `${bridgePreview.summary.bridge_count} bridge В· ${bridgePreview.summary.bridge_credits} РєСЂРµРґРёС‚РѕРІ В· СЃРёР»СЊРЅС‹С…: ${bridgePreview.summary.with_strong_candidate} В· СЃСЂРµРґРЅРёС…: ${bridgePreview.summary.with_medium_candidate || 0} В· Р±РµР· СЃРёР»СЊРЅРѕР№: ${bridgePreview.summary.without_strong_candidate}.`,
                                                            `${bridgePreview.summary.bridge_count} bridge В· ${bridgePreview.summary.bridge_credits} РєСЂРµРґРёС‚ В· РєТЇС€С‚С–: ${bridgePreview.summary.with_strong_candidate} В· РѕСЂС‚Р°С€Р°: ${bridgePreview.summary.with_medium_candidate || 0} В· РєТЇС€С‚С–СЃС–Р·: ${bridgePreview.summary.without_strong_candidate}.`,
                                                            `${bridgePreview.summary.bridge_count} bridges В· ${bridgePreview.summary.bridge_credits} credits В· strong: ${bridgePreview.summary.with_strong_candidate} В· medium: ${bridgePreview.summary.with_medium_candidate || 0} В· without strong: ${bridgePreview.summary.without_strong_candidate}.`
                                                        )}
                                                        <div style={{ marginTop: 4 }}>
                                                            {bridgePreview.summary.diagnosis}
                                                        </div>
                                                    </div>
                                                )}
                                                {bridgePreview.elapsed_seconds !== undefined && (
                                                    <div style={{ fontSize: 12, color: '#6d4c41' }}>
                                                        {localText(`РџРѕРёСЃРє Р·Р°РјРµРЅ РІС‹РїРѕР»РЅРµРЅ Р·Р° ${bridgePreview.elapsed_seconds}s.`, `РђСѓС‹СЃС‚С‹СЂСѓР»Р°СЂРґС‹ С–Р·РґРµСѓ ${bridgePreview.elapsed_seconds}s С–С€С–РЅРґРµ РѕСЂС‹РЅРґР°Р»РґС‹.`, `Replacement search completed in ${bridgePreview.elapsed_seconds}s.`)}
                                                    </div>
                                                )}
                                                {(bridgePreview.suggestions || []).map(row => {
                                                    const good = (row.candidates || []).filter(c => c.strong_candidate || c.medium_candidate)
                                                    return (
                                                        <div key={row.bridge_item_id} style={{ fontSize: 12, padding: 8, borderRadius: 6, background: '#fff', border: '1px solid #f3d27a' }}>
                                                            <b>{row.bridge_title}</b> В· {row.credits} {t('credits')} В· LO: {(row.target_los || []).join(', ')}
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
                                                                                    <strong>в†’ {(c.title_translations || {})[language] || c.title}</strong>
                                                                                </label> В· {c.credits} {t('credits')} В· {c.quality_level === 'strong' ? localText('СЃРёР»СЊРЅР°СЏ', 'РєТЇС€С‚С–', 'strong') : localText('СЃСЂРµРґРЅСЏСЏ, РЅСѓР¶РЅРѕ РїРѕРґС‚РІРµСЂРґРёС‚СЊ', 'РѕСЂС‚Р°С€Р°, СЂР°СЃС‚Р°Сѓ РєРµСЂРµРє', 'medium, needs confirmation')} В· AI {Math.round((c.model_score || 0) * 100)}% В· EPVO {Math.round((c.expert_score || 0) * 100)}% В· LO {Math.round((c.coverage_ratio || 0) * 100)}%
                                                                                <div style={{ marginTop: 3, color: '#5d6470', lineHeight: 1.35 }}>{c.description}</div>
                                                                            </span>
                                                                            <button
                                                                                className="btn btn-primary"
                                                                                style={{ padding: '5px 9px', fontSize: 11, whiteSpace: 'nowrap' }}
                                                                                disabled={Boolean(replacingBridge) || replacingAllBridges}
                                                                                onClick={() => applyBridgeReplacement(row.bridge_item_id, c.course_id)}
                                                                            >
                                                                                {replacingBridge === `${row.bridge_item_id}:${c.course_id}`
                                                                                    ? localText('Р”РѕР±Р°РІР»РµРЅРёРµвЂ¦', 'ТљРѕСЃСѓвЂ¦', 'AddingвЂ¦')
                                                                                    : localText('РџРѕРґС‚РІРµСЂРґРёС‚СЊ Р·Р°РјРµРЅСѓ', 'РђСѓС‹СЃС‚С‹СЂСѓРґС‹ СЂР°СЃС‚Р°Сѓ', 'Confirm replacement')}
                                                                            </button>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            ) : (
                                                                <div style={{ marginTop: 4, color: '#8a5a00' }}>{localText('РЎРёР»СЊРЅРѕР№ Р·Р°РјРµРЅС‹ РїРѕРєР° РЅРµС‚. РђРІС‚РѕР·Р°РјРµРЅР° С‚СЂРµР±СѓРµС‚ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ Р•РџР’Рћ в‰Ґ 50%, РїРѕРєСЂС‹С‚РёРµ в‰Ґ 75% РїСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹С… LO, Р±Р»РёР·РєРёРµ РєСЂРµРґРёС‚С‹ Рё РѕР±Р»Р°СЃС‚СЊ РІС‹Р±СЂР°РЅРЅРѕРіРѕ РЅР°РїСЂР°РІР»РµРЅРёСЏ.', 'УР·С–СЂС€Рµ РєТЇС€С‚С– Р°СѓС‹СЃС‚С‹СЂСѓ Р¶РѕТ›. РђРІС‚РѕР°СѓС‹СЃС‚С‹СЂСѓ ТЇС€С–РЅ Р•РџР’Рћ СЂР°СЃС‚Р°СѓС‹ в‰Ґ 50%, РєУ™СЃС–Р±Рё РћРќ Т›Р°РјС‚СѓС‹ в‰Ґ 75%, Р¶Р°Т›С‹РЅ РєСЂРµРґРёС‚С‚РµСЂ Р¶У™РЅРµ С‚Р°ТЈРґР°Р»Т“Р°РЅ Р±Р°Т“С‹С‚ Т›Р°Р¶РµС‚.', 'No strong replacement yet. Automatic replacement requires EPVO evidence в‰Ґ 50%, coverage of в‰Ґ 75% of professional LOs, similar credits, and the selected programme scope.')}</div>
                                                            )}
                                                            <button
                                                                className="btn btn-secondary"
                                                                style={{ marginTop: 8, padding: '6px 10px', fontSize: 11 }}
                                                                disabled={loadingAiBridge === row.bridge_item_id || Boolean(confirmingAiBridge)}
                                                                onClick={() => loadAiBridgeCandidates(row.bridge_item_id)}
                                                            >
                                                                {loadingAiBridge === row.bridge_item_id
                                                                    ? localText('РР РїРѕРґР±РёСЂР°РµС‚ 3 РІР°СЂРёР°РЅС‚Р°вЂ¦', 'Р–Р 3 РЅТ±СЃТ›Р° С‚Р°ТЈРґР°СѓРґР°вЂ¦', 'AI is generating 3 optionsвЂ¦')
                                                                    : localText('РџРѕРґРѕР±СЂР°С‚СЊ 3 РґРёСЃС†РёРїР»РёРЅС‹ С‡РµСЂРµР· РР', 'Р–Р Р°СЂТ›С‹Р»С‹ 3 РїУ™РЅ Т±СЃС‹РЅСѓ', 'Generate 3 courses with AI')}
                                                            </button>
                                                            {aiBridgeCandidates[row.bridge_item_id] && (
                                                                <div style={{ marginTop: 8, display: 'grid', gap: 7 }}>
                                                                    {(aiBridgeCandidates[row.bridge_item_id].candidates || []).map(candidate => (
                                                                        <div key={candidate.candidate_id} style={{ padding: 8, borderRadius: 6, background: '#f7f9fc', border: '1px solid #dce5ef' }}>
                                                                            <strong>{candidate[`title_${language}`] || candidate.title_ru}</strong> В· {row.credits} {t('credits')}
                                                                            <div style={{ marginTop: 3, color: '#5d6470', lineHeight: 1.35 }}>{candidate[`description_${language}`] || candidate.description_ru}</div>
                                                                            <div style={{ marginTop: 4, color: '#53657a' }}>LO: {(candidate.target_los || []).join(', ')}</div>
                                                                            <button
                                                                                className="btn btn-primary"
                                                                                style={{ marginTop: 6, padding: '5px 9px', fontSize: 11 }}
                                                                                disabled={Boolean(confirmingAiBridge)}
                                                                                onClick={() => confirmAiBridgeCandidate(row.bridge_item_id, candidate)}
                                                                            >
                                                                                {confirmingAiBridge === `${row.bridge_item_id}:${candidate.candidate_id}`
                                                                                    ? localText('РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµвЂ¦', 'Р Р°СЃС‚Р°СѓвЂ¦', 'ConfirmingвЂ¦')
                                                                                    : localText('РџРѕРґС‚РІРµСЂРґРёС‚СЊ Рё Р·Р°РјРµРЅРёС‚СЊ bridge', 'Р Р°СЃС‚Р°Сѓ Р¶У™РЅРµ bridge Р°СѓС‹СЃС‚С‹СЂСѓ', 'Confirm and replace bridge')}
                                                                            </button>
                                                                        </div>
                                                                    ))}
                                                                    <div style={{ fontSize: 11, color: '#7a6570' }}>
                                                                        {localText('Р­С‚Рѕ РїСЂРµРґР»РѕР¶РµРЅРёРµ РР. Р’ РїР»Р°РЅ РѕРЅРѕ РїРѕРїР°РґС‘С‚ С‚РѕР»СЊРєРѕ РїРѕСЃР»Рµ РІР°С€РµРіРѕ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ.', 'Р‘Т±Р» Р–Р Т±СЃС‹РЅС‹СЃС‹. Р–РѕСЃРїР°СЂТ“Р° С‚РµРє СЃС–Р· СЂР°СЃС‚Р°Т“Р°РЅРЅР°РЅ РєРµР№С–РЅ РµРЅРіС–Р·С–Р»РµРґС–.', 'This is an AI proposal. It enters the plan only after your confirmation.')}
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
                                                    ? localText('РџРµСЂРµСЃС‚СЂРѕРµРЅРёРµвЂ¦', 'ТљР°Р№С‚Р° Т›Т±СЂСѓвЂ¦', 'RebuildingвЂ¦')
                                                    : localText('РџРµСЂРµРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ A/B/C СЃ РёР·РјРµРЅРµРЅРёСЏРјРё', 'УЁР·РіРµСЂС–СЃС‚РµСЂРјРµРЅ A/B/C Т›Р°Р№С‚Р° Т›Т±СЂСѓ', 'Regenerate A/B/C with changes')}
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
                                            <strong>{localText('Р”РёСЃС†РёРїР»РёРЅС‹ РїР»Р°РЅР° РёР· Р•РџР’Рћ', 'Р–РѕСЃРїР°СЂРґР°Т“С‹ Р•РџР’Рћ РїУ™РЅРґРµСЂС–', 'Plan courses from EPVO')}: {currentPlan.epvo_plan_quality.match_percentage}%</strong>
                                            <span style={{ color: '#566' }}>
                                                {localText('С‚РёРїРѕРІС‹С… РґРёСЃС†РёРїР»РёРЅ', 'С‚РёРїС‚С–Рє РїУ™РЅРґРµСЂ', 'typical courses')}: {currentPlan.epvo_plan_quality.matched_courses}/{currentPlan.epvo_plan_quality.course_count}
                                            </span>
                                            <span style={{ color: '#566' }}>
                                                {localText('СЌРєСЃРїРµСЂС‚РЅС‹С… СЃРІСЏР·РµР№', 'СЃР°СЂР°РїС‚Р°РјР°Р»С‹Т› Р±Р°Р№Р»Р°РЅС‹СЃС‚Р°СЂ', 'expert links')}: {currentPlan.epvo_plan_quality.expert_links}
                                            </span>
                                            </div>
                                            <Link to={`/projects/${id}/epvo`} className="btn btn-secondary" style={{ padding: '7px 12px', whiteSpace: 'nowrap' }}>
                                                {localText('РџРѕР»РЅС‹Р№ Р°РЅР°Р»РёР· Р•РџР’Рћ', 'Р•РџР’Рћ С‚РѕР»С‹Т› С‚Р°Р»РґР°СѓС‹', 'Full EPVO analysis')}
                                            </Link>
                                        </div>
                                    </div>
                                )}
                                <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#f8fbff', border: '1px solid #dce9f7' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                                        <div>
                                            <strong>{localText('РСЃС‚РѕС‡РЅРёРєРё РїРѕРєСЂС‹С‚РёСЏ LO', 'LO Т›Р°РјС‚Сѓ РєУ©Р·РґРµСЂС–', 'LO coverage sources')}</strong>
                                            <div style={{ fontSize: 12, color: '#566', marginTop: 2 }}>
                                                {localText('РџРѕРєР°Р·С‹РІР°РµС‚, РєР°РєРёРµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ Р·Р°РєСЂС‹С‚С‹ СЂРµР°Р»СЊРЅС‹РјРё РґРёСЃС†РёРїР»РёРЅР°РјРё, Р° РєР°РєРёРµ С‚РѕР»СЊРєРѕ bridge-РјРѕРґСѓР»СЏРјРё.', 'ТљР°Р№ РЅУ™С‚РёР¶РµР»РµСЂ РЅР°Т›С‚С‹ РїУ™РЅРґРµСЂРјРµРЅ, Т›Р°Р№СЃС‹СЃС‹ bridge-РјРѕРґСѓР»СЊРґРµСЂРјРµРЅ Р¶Р°Р±С‹Р»Т“Р°РЅС‹РЅ РєУ©СЂСЃРµС‚РµРґС–.', 'Shows which outcomes are covered by real courses and which only by bridge modules.')}
                                            </div>
                                        </div>
                                        <button className="btn btn-secondary" onClick={loadLoCoverageSources} disabled={loadingLoCoverageSources}>
                                            {loadingLoCoverageSources ? localText('Р—Р°РіСЂСѓР·РєР°вЂ¦', 'Р–ТЇРєС‚РµСѓвЂ¦', 'LoadingвЂ¦') : localText('РџРѕРєР°Р·Р°С‚СЊ LO-РёСЃС‚РѕС‡РЅРёРєРё', 'LO РєУ©Р·РґРµСЂС–РЅ РєУ©СЂСЃРµС‚Сѓ', 'Show LO sources')}
                                        </button>
                                    </div>
                                    {loCoverageSources?.variant === activeVariant && (
                                        <div style={{ marginTop: 10 }}>
                                            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12 }}>
                                                <span>{localText('Р’СЃРµРіРѕ LO', 'Р‘Р°СЂР»С‹Т› LO', 'Total LOs')}: <b>{loCoverageSources.summary?.los || 0}</b></span>
                                                <span style={{ color: '#2e7d32' }}>{localText('СЂРµР°Р»СЊРЅС‹Рµ РґРёСЃС†РёРїР»РёРЅС‹', 'РЅР°Т›С‚С‹ РїУ™РЅРґРµСЂ', 'real courses')}: <b>{loCoverageSources.summary?.real_confirmed || 0}</b></span>
                                                <span style={{ color: '#8a5a00' }}>bridge: <b>{loCoverageSources.summary?.bridge_supported || 0}</b></span>
                                                <span style={{ color: '#c62828' }}>{localText('СЃР»Р°Р±С‹Рµ', 'У™Р»СЃС–Р·', 'weak')}: <b>{loCoverageSources.summary?.weak || 0}</b></span>
                                            </div>
                                            <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #dfeaf6' }}>
                                                <div style={{ fontWeight: 700, marginBottom: 6, color: '#17233b' }}>
                                                    {localText('\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u043e\u0431\u0443\u0447\u0435\u043d\u0438\u044f \u0438 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u0438\u0445 \u043f\u043e\u043a\u0440\u044b\u0432\u0430\u044e\u0442', '\u041e\u049b\u0443 \u043d\u04d9\u0442\u0438\u0436\u0435\u043b\u0435\u0440\u0456 \u0436\u04d9\u043d\u0435 \u043e\u043b\u0430\u0440\u0434\u044b \u049b\u0430\u043c\u0442\u0438\u0442\u044b\u043d \u043f\u04d9\u043d\u0434\u0435\u0440', 'Learning outcomes and covering courses')}
                                                </div>
                                                <div style={{ fontSize: 12, color: '#566', marginBottom: 8 }}>
                                                    {localText('\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b\u00bb, \u0447\u0442\u043e\u0431\u044b \u0443\u0432\u0438\u0434\u0435\u0442\u044c, \u043a\u0430\u043a\u0438\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b \u043f\u043b\u0430\u043d\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u044e\u0442 \u0434\u043e\u0441\u0442\u0438\u0436\u0435\u043d\u0438\u0435 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0433\u043e \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430 \u043e\u0431\u0443\u0447\u0435\u043d\u0438\u044f.', '\u00ab\u041f\u04d9\u043d\u0434\u0435\u0440\u0434\u0456 \u043a\u04e9\u0440\u0441\u0435\u0442\u0443\u00bb \u0431\u0430\u0442\u044b\u0440\u043c\u0430\u0441\u044b\u043d \u0431\u0430\u0441\u0441\u0430\u04a3\u044b\u0437, \u0442\u0430\u04a3\u0434\u0430\u043b\u0493\u0430\u043d \u043e\u049b\u0443 \u043d\u04d9\u0442\u0438\u0436\u0435\u0441\u0456\u043d \u0440\u0430\u0441\u0442\u0430\u0439\u0442\u044b\u043d \u0436\u043e\u0441\u043f\u0430\u0440 \u043f\u04d9\u043d\u0434\u0435\u0440\u0456 \u043a\u04e9\u0440\u0441\u0435\u0442\u0456\u043b\u0435\u0434\u0456.', 'Click Show courses to see which plan courses support the selected learning outcome.')}
                                                </div>
                                                <div style={{ display: 'grid', gap: 7 }}>
                                                    {(loCoverageSources.items || []).map(row => {
                                                        const loKey = `${activeVariant}:${row.lo_code}`
                                                        const checked = Boolean(expandedLoCourses[loKey])
                                                        const real = row.real_sources || []
                                                        const bridges = row.bridge_sources || []
                                                        return <div key={`lo-course-map-${row.lo_code}`} style={{ padding: '8px 10px', borderRadius: 8, background: checked ? '#f8fbff' : '#fbfcfe', border: '1px solid #e4edf7' }}>
                                                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                                                                <button
                                                                    type="button"
                                                                    className="btn btn-secondary"
                                                                    onClick={() => setExpandedLoCourses(current => ({ ...current, [loKey]: !current[loKey] }))}
                                                                    style={{ padding: '4px 8px', fontSize: 11, whiteSpace: 'nowrap', marginTop: 1 }}
                                                                >
                                                                    {checked ? localText('\u0421\u043a\u0440\u044b\u0442\u044c', '\u0421\u043a\u0440\u044b\u0442\u044c', 'Hide') : localText('\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b', '\u041f\u04d9\u043d\u0434\u0435\u0440\u0434\u0456 \u043a\u04e9\u0440\u0441\u0435\u0442\u0443', 'Show courses')}
                                                                </button>
                                                                <span>
                                                                    <strong>{row.lo_code}</strong> <span aria-hidden="true">&middot;</span> {Math.round((row.coverage || 0) * 100)}% <span aria-hidden="true">&middot;</span> {row.status === 'real_confirmed' ? localText('\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e \u0440\u0435\u0430\u043b\u044c\u043d\u044b\u043c\u0438 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u0430\u043c\u0438', '\u043d\u0430\u049b\u0442\u044b \u043f\u04d9\u043d\u0434\u0435\u0440\u043c\u0435\u043d \u0440\u0430\u0441\u0442\u0430\u043b\u0493\u0430\u043d', 'confirmed by real courses') : row.status === 'bridge_supported' ? localText('\u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0430\u043d\u043e bridge-\u043c\u043e\u0434\u0443\u043b\u0435\u043c', 'bridge-\u043c\u043e\u0434\u0443\u043b\u044c\u043c\u0435\u043d \u049b\u043e\u043b\u0434\u0430\u0443 \u0442\u0430\u043f\u049b\u0430\u043d', 'supported by a bridge module') : localText('\u043d\u0443\u0436\u043d\u043e \u0443\u0441\u0438\u043b\u0438\u0442\u044c', '\u043a\u04af\u0448\u0435\u0439\u0442\u0443 \u049b\u0430\u0436\u0435\u0442', 'needs strengthening')}
                                                                    <span style={{ display: 'block', marginTop: 2, color: '#667085', fontSize: 12 }}>{row.lo_text}</span>
                                                                </span>
                                                            </div>
                                                            {checked && <div style={{ marginTop: 8, paddingLeft: 25, display: 'grid', gap: 5, fontSize: 12 }}>
                                                                {real.length > 0 && real.map(src => (
                                                                    <div key={`lo-real-${row.lo_code}-${src.course_id}`} style={{ color: '#1b5e20' }}>
                                                                        <span aria-hidden="true">&#10003;</span> {src.title} <span aria-hidden="true">&middot;</span> {src.credits} {t('credits')} <span aria-hidden="true">&middot;</span> AI {Math.round((src.score || 0) * 100)}% <span aria-hidden="true">&middot;</span> EPVO {Math.round((src.expert_score || 0) * 100)}%
                                                                    </div>
                                                                ))}
                                                                {bridges.length > 0 && bridges.map(src => (
                                                                    <div key={`lo-bridge-${row.lo_code}-${src.bridge_id || src.title}`} style={{ color: '#8a5a00' }}>
                                                                        <span aria-hidden="true">&#8618;</span> bridge: {src.title} <span aria-hidden="true">&middot;</span> {src.credits} {t('credits')} <span aria-hidden="true">&middot;</span> {t('semester')} {src.semester}
                                                                    </div>
                                                                ))}
                                                                {real.length === 0 && bridges.length === 0 && <div style={{ color: '#b71c1c' }}>
                                                                    {localText('\u0412 \u0442\u0435\u043a\u0443\u0449\u0435\u043c \u043f\u043b\u0430\u043d\u0435 \u043d\u0435\u0442 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u0443\u0432\u0435\u0440\u0435\u043d\u043d\u043e \u043f\u043e\u043a\u0440\u044b\u0432\u0430\u044e\u0442 \u044d\u0442\u043e\u0442 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442.', '\u0410\u0493\u044b\u043c\u0434\u0430\u0493\u044b \u0436\u043e\u0441\u043f\u0430\u0440\u0434\u0430 \u0431\u04b1\u043b \u043d\u04d9\u0442\u0438\u0436\u0435\u043d\u0456 \u0441\u0435\u043d\u0456\u043c\u0434\u0456 \u049b\u0430\u043c\u0442\u0438\u0442\u044b\u043d \u043f\u04d9\u043d\u0434\u0435\u0440 \u0436\u043e\u049b.', 'No courses in the current plan confidently cover this outcome.')}
                                                                </div>}
                                                            </div>}
                                                        </div>
                                                    })}
                                                </div>
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
                                                                {row.status === 'real_confirmed' ? localText('СЂРµР°Р»СЊРЅР°СЏ РґРёСЃС†РёРїР»РёРЅР°', 'РЅР°Т›С‚С‹ РїУ™РЅ', 'real course') : row.status === 'bridge_supported' ? 'bridge' : localText('СЃР»Р°Р±РѕРµ РїРѕРєСЂС‹С‚РёРµ', 'У™Р»СЃС–Р· Т›Р°РјС‚Сѓ', 'weak')}
                                                            </span>
                                                        </summary>
                                                        <div style={{ marginTop: 6, fontSize: 12, color: '#455' }}>{row.lo_text}</div>
                                                        <div style={{ marginTop: 5, padding: '6px 8px', borderRadius: 6, background: row.coverage_kind === 'bridge_target_assumption' ? '#fff8e1' : '#f5f8fb', fontSize: 11, color: '#5d6470' }}>
                                                            {row.coverage_explanation || (row.status === 'bridge_supported'
                                                                ? localText('75% вЂ” СЃР»СѓР¶РµР±РЅР°СЏ РѕС†РµРЅРєР° РїСЂРѕРµРєС‚РЅРѕРіРѕ bridge, Р° РЅРµ СЌРєСЃРїРµСЂС‚РЅР°СЏ РѕС†РµРЅРєР° СЂРµР°Р»СЊРЅРѕР№ РґРёСЃС†РёРїР»РёРЅС‹ Р•РџР’Рћ.', '75% вЂ” Р¶РѕР±Р°Р»С‹Т› bridge Т›С‹Р·РјРµС‚С‚С–Рє Р±Р°Т“Р°СЃС‹, РЅР°Т›С‚С‹ Р•РџР’Рћ РїУ™РЅС–РЅС–ТЈ СЃР°СЂР°РїС‚Р°РјР°Р»С‹Т› Р±Р°Т“Р°СЃС‹ РµРјРµСЃ.', '75% is a planning assumption for a proposed bridge, not an expert EPVO course score.')
                                                                : '')}
                                                        </div>
                                                        <div style={{ marginTop: 8, display: 'grid', gap: 4, fontSize: 12 }}>
                                                            {(row.real_sources || []).slice(0, 3).map(src => (
                                                                <div key={`real-${row.lo_code}-${src.course_id}`}>вњ“ {src.title} В· {src.credits} {t('credits')} В· AI {Math.round((src.score || 0) * 100)}% В· EPVO {Math.round((src.expert_score || 0) * 100)}%</div>
                                                            ))}
                                                            {(row.bridge_sources || []).slice(0, 3).map(src => (
                                                                <div key={`bridge-${row.lo_code}-${src.bridge_id}`} style={{ color: '#8a5a00' }}>
                                                                    в†і bridge РІ РїР»Р°РЅРµ: {src.title} В· {src.credits} {t('credits')} В· {t('semester')} {src.semester}
                                                                    <button className="btn btn-secondary" style={{ marginLeft: 7, padding: '3px 7px', fontSize: 10 }} onClick={() => document.querySelector(`[data-plan-semester="${src.semester}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>
                                                                        {localText('РџРѕРєР°Р·Р°С‚СЊ РІ РїР»Р°РЅРµ', 'Р–РѕСЃРїР°СЂРґР° РєУ©СЂСЃРµС‚Сѓ', 'Show in plan')}
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
                                        <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}>
                                            <strong>{localText('РЎРѕРјРЅРёС‚РµР»СЊРЅС‹Рµ РґРёСЃС†РёРїР»РёРЅС‹', 'РљТЇРјУ™РЅРґС– РїУ™РЅРґРµСЂ', 'Suspicious courses')}: {currentPlan.suspicious_courses.length}</strong>
                                            <button
                                                className="btn btn-secondary"
                                                style={{ padding: '5px 9px', fontSize: 11, borderColor: '#c17b00' }}
                                                disabled={loadingCourseReplacement === 'all'}
                                                onClick={loadAllVisibleCourseReplacements}
                                            >
                                                {loadingCourseReplacement === 'all'
                                                    ? localText('РС‰РµРј Р·Р°РјРµРЅС‹вЂ¦', 'РђСѓС‹СЃС‚С‹СЂСѓР»Р°СЂ С–Р·РґРµР»СѓРґРµвЂ¦', 'Searching replacementsвЂ¦')
                                                    : localText('РџРѕРґРѕР±СЂР°С‚СЊ Р·Р°РјРµРЅС‹ РґР»СЏ РІСЃРµС… РІРёРґРёРјС‹С…', 'РљУ©СЂС–РЅРµС‚С–РЅРґРµСЂРґС–ТЈ Р±У™СЂС–РЅРµ Р°СѓС‹СЃС‚С‹СЂСѓ С‚Р°Р±Сѓ', 'Find replacements for all visible')}
                                            </button>
                                        </div>
                                        <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
                                            {currentPlan.suspicious_courses.slice(0, 6).map((row, idx) => (
                                                <div key={`${row.course_id}-${idx}`} style={{ fontSize: 12, color: '#6d4c41' }}>
                                                    <strong>{row.title}</strong> В· {t('semester')} {row.semester} В· {Math.round((row.max_score || 0) * 100)}%
                                                    <span style={{ marginLeft: 6 }}>
                                                        {row.reasons?.map(reason => localText(
                                                            reason === 'wrong_education_level' ? 'РЅРµ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ СѓСЂРѕРІРЅСЋ РѕР±СЂР°Р·РѕРІР°РЅРёСЏ' : reason === 'not_core_for_program' ? 'РЅРµ СЏРґСЂРѕ РїСЂРѕРіСЂР°РјРјС‹' : reason === 'weak_lo_evidence' ? 'СЃР»Р°Р±РѕРµ LO-РґРѕРєР°Р·Р°С‚РµР»СЊСЃС‚РІРѕ' : 'СЃР»РёС€РєРѕРј СЂР°РЅРѕ',
                                                            reason === 'wrong_education_level' ? 'Р±С–Р»С–Рј РґРµТЈРіРµР№С–РЅРµ СЃУ™Р№РєРµСЃ РµРјРµСЃ' : reason === 'not_core_for_program' ? 'Р±Р°Т“РґР°СЂР»Р°РјР° У©Р·РµРіС– РµРјРµСЃ' : reason === 'weak_lo_evidence' ? 'LO РґУ™Р»РµР»С– У™Р»СЃС–Р·' : 'С‚С‹Рј РµСЂС‚Рµ',
                                                            reason === 'wrong_education_level' ? 'wrong degree level' : reason === 'not_core_for_program' ? 'not programme core' : reason === 'weak_lo_evidence' ? 'weak LO evidence' : 'too early',
                                                        )).join('; ')}
                                                    </span>
                                                    {row.top_lo_code && <div style={{ marginTop: 4, color: '#5d6470' }} title={row.top_lo_text || row.top_lo_code}>
                                                        {localText('Р›СѓС‡С€Р°СЏ СЃРІСЏР·СЊ', 'Р•ТЈ Р¶Р°Т›СЃС‹ Р±Р°Р№Р»Р°РЅС‹СЃ', 'Best link')}: {row.top_lo_code} В· {Math.round((row.max_score || 0) * 100)}%
                                                    </div>}
                                                    {row.reason_details?.length > 0 && (
                                                        <div style={{ marginTop: 4, color: '#6d4c41', lineHeight: 1.35 }}>
                                                            {row.reason_details.map((reason, reasonIndex) => (
                                                                <div key={reasonIndex}>вЂў {reason}</div>
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
                                                            {matchFeedbackState[`${row.course_id}:${row.top_lo_id}`] === 'confirmed' ? 'вњ“ ' : ''}
                                                            {localText('РџРѕРґС‚РІРµСЂРґРёС‚СЊ СЃРІСЏР·СЊ', 'Р‘Р°Р№Р»Р°РЅС‹СЃС‚С‹ СЂР°СЃС‚Р°Сѓ', 'Confirm link')}
                                                        </button>}
                                                        <button
                                                            className="btn btn-secondary"
                                                            style={{ padding: '5px 8px', fontSize: 11, borderColor: '#2e7d32', color: '#2e7d32' }}
                                                            onClick={() => confirmSuspiciousCourse(row.course_id, row.title)}
                                                        >
                                                            {localText('РћСЃС‚Р°РІРёС‚СЊ РІ РїР»Р°РЅРµ', 'Р–РѕСЃРїР°СЂРґР° Т›Р°Р»РґС‹СЂСѓ', 'Keep in plan')}
                                                        </button>
                                                        <button
                                                            className="btn btn-secondary"
                                                            style={{ padding: '5px 8px', fontSize: 11, borderColor: '#c17b00' }}
                                                            onClick={() => toggleCourseExclusion(row.course_id, row.title)}
                                                        >
                                                            {excludedCourses[row.course_id]
                                                                ? localText('вњ“ Р—Р°РјРµРЅРёС‚СЊ РїСЂРё РїРµСЂРµРіРµРЅРµСЂР°С†РёРё', 'вњ“ ТљР°Р№С‚Р° Т›Т±СЂСѓРґР° Р°СѓС‹СЃС‚С‹СЂСѓ', 'вњ“ Replace on regeneration')
                                                                : localText('РћС‚РјРµС‚РёС‚СЊ РЅР° Р·Р°РјРµРЅСѓ', 'РђСѓС‹СЃС‚С‹СЂСѓТ“Р° Р±РµР»РіС–Р»РµСѓ', 'Mark for replacement')}
                                                        </button>
                                                        <button
                                                            className="btn btn-primary"
                                                            style={{ padding: '5px 8px', fontSize: 11 }}
                                                            disabled={loadingCourseReplacement === row.course_id}
                                                            onClick={() => loadCourseReplacements(row.course_id)}
                                                        >
                                                            {loadingCourseReplacement === row.course_id
                                                                ? localText('РџРѕРёСЃРєвЂ¦', 'Р†Р·РґРµСѓвЂ¦', 'SearchingвЂ¦')
                                                                : localText('РџРѕРґРѕР±СЂР°С‚СЊ 3 Р·Р°РјРµРЅС‹', '3 Р°СѓС‹СЃС‚С‹СЂСѓРґС‹ С‚Р°ТЈРґР°Сѓ', 'Find 3 replacements')}
                                                        </button>
                                                    </div>
                                                    {courseReplacementPreviews[row.course_id] && <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
                                                        {courseReplacementPreviews[row.course_id].elapsed_seconds !== undefined && (
                                                            <div style={{ color: '#6d4c41', fontSize: 12 }}>
                                                                {localText(`РџРѕРґР±РѕСЂ Р·Р°РјРµРЅ РІС‹РїРѕР»РЅРµРЅ Р·Р° ${courseReplacementPreviews[row.course_id].elapsed_seconds}s.`, `РђСѓС‹СЃС‚С‹СЂСѓРґС‹ С‚Р°ТЈРґР°Сѓ ${courseReplacementPreviews[row.course_id].elapsed_seconds}s С–С€С–РЅРґРµ РѕСЂС‹РЅРґР°Р»РґС‹.`, `Replacement preview completed in ${courseReplacementPreviews[row.course_id].elapsed_seconds}s.`)}
                                                            </div>
                                                        )}
                                                        {(courseReplacementPreviews[row.course_id].candidates || []).length ? (courseReplacementPreviews[row.course_id].candidates || []).map(candidate => (
                                                            <div key={candidate.course_id} style={{ padding: 8, borderRadius: 7, background: '#fff', border: '1px solid #ead49e' }}>
                                                                <strong>{localize(candidate.title_translations || candidate.title)}</strong> В· {candidate.credits} {t('credits')}
                                                                <div style={{ color: '#667', marginTop: 3 }}>AI {Math.round((candidate.model_score || 0) * 100)}% В· Р•РџР’Рћ {Math.round((candidate.expert_score || 0) * 100)}% В· LO {candidate.covered_lo_count}</div>
                                                                {candidate.covered_los?.length > 0 && <div style={{ color: '#46566a', marginTop: 3 }}>
                                                                    {localText('РџСЂРѕС„РµСЃСЃРёРѕРЅР°Р»СЊРЅС‹Рµ LO', 'РљУ™СЃС–Р±Рё РћРќ', 'Professional LOs')}: {candidate.covered_los.join(', ')}
                                                                    {candidate.recommended_semester ? ` В· ${localText('СЂРµРєРѕРјРµРЅРґСѓРµРјС‹Р№ СЃРµРјРµСЃС‚СЂ', 'Т±СЃС‹РЅС‹Р»Р°С‚С‹РЅ СЃРµРјРµСЃС‚СЂ', 'recommended semester')} ${candidate.recommended_semester}` : ''}
                                                                </div>}
                                                                {candidate.selection_reason && <div style={{ color: '#39704c', marginTop: 3 }}>{candidate.selection_reason}</div>}
                                                                {candidate.description && <div style={{ color: '#667', marginTop: 3 }}>{candidate.description}</div>}
                                                                <button className="btn btn-primary" style={{ marginTop: 6, padding: '5px 8px', fontSize: 11 }} disabled={Boolean(applyingCourseReplacement)} onClick={() => applyCourseReplacement(row.course_id, candidate.course_id)}>
                                                                    {applyingCourseReplacement === `${row.course_id}:${candidate.course_id}` ? localText('Р—Р°РјРµРЅР°вЂ¦', 'РђСѓС‹СЃС‚С‹СЂСѓвЂ¦', 'ReplacingвЂ¦') : localText('РџРѕРґС‚РІРµСЂРґРёС‚СЊ Р·Р°РјРµРЅСѓ', 'РђСѓС‹СЃС‚С‹СЂСѓРґС‹ СЂР°СЃС‚Р°Сѓ', 'Confirm replacement')}
                                                                </button>
                                                            </div>
                                                        )) : <div style={{ color: '#8a5a00' }}>{courseReplacementPreviews[row.course_id].no_candidate_reason || localText('РџРѕРґС…РѕРґСЏС‰РµР№ СЂР°РІРЅРѕС†РµРЅРЅРѕР№ Р·Р°РјРµРЅС‹ РїРѕРєР° РЅРµС‚.', 'РЎУ™Р№РєРµСЃ Р±Р°Р»Р°РјР° У™Р»С– Р¶РѕТ›.', 'No equivalent replacement found yet.')}</div>}
                                                    </div>}
                                                </div>
                                            ))}
                                        </div>
                                        <div style={{ marginTop: 6, fontSize: 12, color: '#795548' }}>
                                            {localText('РЎРёСЃС‚РµРјР° РЅРµ Р±Р»РѕРєРёСЂСѓРµС‚ РїСЂРѕСЃРјРѕС‚СЂ, РЅРѕ С‚Р°РєРёРµ РґРёСЃС†РёРїР»РёРЅС‹ РЅСѓР¶РЅРѕ Р·Р°РјРµРЅРёС‚СЊ РёР»Рё РїРѕРґС‚РІРµСЂРґРёС‚СЊ СЌРєСЃРїРµСЂС‚РѕРј.', 'Р–ТЇР№Рµ Т›Р°СЂР°СѓРґС‹ Р±Т±Т“Р°С‚С‚Р°РјР°Р№РґС‹, Р±С–СЂР°Т› РјТ±РЅРґР°Р№ РїУ™РЅРґРµСЂРґС– Р°СѓС‹СЃС‚С‹СЂСѓ РЅРµРјРµСЃРµ СЃР°СЂР°РїС€С‹РјРµРЅ СЂР°СЃС‚Р°Сѓ РєРµСЂРµРє.', 'The system does not block viewing, but these courses should be replaced or expert-confirmed.')}
                                        </div>
                                    </div>
                                )}
                            </CompactSection>
                        )}
                        {currentPlan?.metrics?.verification?.goso_compliance?.applicable && (() => {
                            const goso = currentPlan.metrics.verification.goso_compliance
                            return <CompactSection title={localText('\u0421\u043e\u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0438\u0435 \u0413\u041e\u0421\u041e \u0420\u0435\u0441\u043f\u0443\u0431\u043b\u0438\u043a\u0438 \u041a\u0430\u0437\u0430\u0445\u0441\u0442\u0430\u043d', '\u049a\u0430\u0437\u0430\u049b\u0441\u0442\u0430\u043d \u0420\u0435\u0441\u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0441\u044b\u043d\u044b\u04a3 \u041c\u0416\u041c\u0411\u0421 \u0441\u04d9\u0439\u043a\u0435\u0441\u0442\u0456\u0433\u0456', 'Kazakhstan state-standard compliance')} accent={goso.compliant ? '#2e7d32' : '#c62828'} defaultOpen={false}>
                                <h3 style={{ marginTop: 0 }}>{localText('РЎРѕРѕС‚РІРµС‚СЃС‚РІРёРµ Р“РћРЎРћ Р РµСЃРїСѓР±Р»РёРєРё РљР°Р·Р°С…СЃС‚Р°РЅ', 'ТљР°Р·Р°Т›СЃС‚Р°РЅ Р РµСЃРїСѓР±Р»РёРєР°СЃС‹РЅС‹ТЈ РњР–РњР‘РЎ СЃУ™Р№РєРµСЃС‚С–РіС–', 'Kazakhstan state-standard compliance')}</h3>
                                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                                    <span>{localText('РЎС‚Р°С‚СѓСЃ', 'РљТЇР№С–', 'Status')}: <strong>{goso.compliant ? localText('СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚', 'СЃУ™Р№РєРµСЃ', 'compliant') : localText('РµСЃС‚СЊ РЅР°СЂСѓС€РµРЅРёСЏ', 'Р±Т±Р·СѓС€С‹Р»С‹Т›С‚Р°СЂ Р±Р°СЂ', 'violations found')}</strong></span>
                                    <span>{localText('РћР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РєСЂРµРґРёС‚С‹', 'РњС–РЅРґРµС‚С‚С– РєСЂРµРґРёС‚С‚РµСЂ', 'Mandatory credits')}: <strong>{goso.mandatory_credits}</strong></span>
                                    <span>{localText('РЈСЂРѕРІРµРЅСЊ', 'Р”РµТЈРіРµР№', 'Level')}: <strong>{goso.education_level}</strong></span>
                                </div>
                                {(goso.violations || []).map((item, index) => <div key={index} style={{ marginTop: 8, color: '#9b1c1c', fontSize: 13 }}>
                                    вљ пёЏ {item.title || item.reason}: {item.actual !== undefined ? `${item.actual} / ${item.required}` : ''}
                                </div>)}
                                <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>{goso.source}</div>
                            </CompactSection>
                        })()}
                        {currentPlan?.metrics?.verification?.pedagogical_audit && (() => {
                            const audit = currentPlan.metrics.verification.pedagogical_audit
                            return <CompactSection title={localText('\u0410\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430 \u043f\u043b\u0430\u043d\u0430', '\u0416\u043e\u0441\u043f\u0430\u0440 \u0441\u0430\u043f\u0430\u0441\u044b\u043d \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0442\u044b \u0442\u0435\u043a\u0441\u0435\u0440\u0443', 'Automatic curriculum quality audit')} accent={audit.passed ? '#2e7d32' : '#e67e22'} defaultOpen={false}>
                                <h3 style={{ marginTop: 0 }}>{localText('РђРІС‚РѕРјР°С‚РёС‡РµСЃРєР°СЏ РїСЂРѕРІРµСЂРєР° РєР°С‡РµСЃС‚РІР° РїР»Р°РЅР°', 'Р–РѕСЃРїР°СЂ СЃР°РїР°СЃС‹РЅ Р°РІС‚РѕРјР°С‚С‚С‹ С‚РµРєСЃРµСЂСѓ', 'Automatic curriculum quality audit')}</h3>
                                <div style={{ fontSize: 13, color: '#566', marginBottom: 10 }}>{audit.engine}</div>
                                <strong style={{ color: audit.passed ? '#1b5e20' : '#9a5b00' }}>
                                    {audit.passed
                                        ? localText('РџР»Р°РЅ РїСЂРѕС€С‘Р» РїСЂРѕРІРµСЂРєСѓ СЃРІСЏР·РµР№ СЃ Р Рћ Рё РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕСЃС‚Рё СЃРµРјРµСЃС‚СЂРѕРІ.', 'Р–РѕСЃРїР°СЂ РћРќ Р±Р°Р№Р»Р°РЅС‹СЃС‚Р°СЂС‹ РјРµРЅ СЃРµРјРµСЃС‚СЂ СЂРµС‚С‚С–Р»С–РіС– С‚РµРєСЃРµСЂС–СЃС–РЅРµРЅ У©С‚С‚С–.', 'The plan passed LO alignment and semester sequencing checks.')
                                        : localText('РџР»Р°РЅ С‚СЂРµР±СѓРµС‚ РёСЃРїСЂР°РІР»РµРЅРёР№ РґРѕ СЌРєСЃРїРµСЂС‚РЅРѕРіРѕ СѓС‚РІРµСЂР¶РґРµРЅРёСЏ.', 'Р–РѕСЃРїР°СЂ СЃР°СЂР°РїС€С‹Р»С‹Т› Р±РµРєС–С‚СѓРіРµ РґРµР№С–РЅ С‚ТЇР·РµС‚СѓРґС– Т›Р°Р¶РµС‚ РµС‚РµРґС–.', 'The plan needs corrections before expert approval.')}
                                </strong>
                                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10, fontSize: 13 }}>
                                    <span>{localText('РЎС‚СЂСѓРєС‚СѓСЂРЅС‹Рµ РїСЂРµСЂРµРєРІРёР·РёС‚С‹', 'ТљТ±СЂС‹Р»С‹РјРґС‹Т› РїСЂРµСЂРµРєРІРёР·РёС‚С‚РµСЂ', 'Structural prerequisites')}: <b>{audit.structural_foundations?.length || 0}</b></span>
                                    <span>{localText('Р Рћ Р±РµР· СЂРµР°Р»СЊРЅРѕР№ РґРёСЃС†РёРїР»РёРЅС‹', 'РќР°Т›С‚С‹ РїУ™РЅСЃС–Р· РћРќ', 'LOs without a real course')}: <b>{audit.lo_without_real_course?.length || 0}</b></span>
                                    <span>{localText('РЎР»Р°Р±С‹Рµ РґРёСЃС†РёРїР»РёРЅС‹', 'УР»СЃС–Р· РїУ™РЅРґРµСЂ', 'Weak courses')}: <b>{audit.weak_courses?.length || 0}</b></span>
                                    <span>{localText('РќРµСѓРјРµСЃС‚РЅС‹Р№ СЃРµРјРµСЃС‚СЂ', 'РћСЂС‹РЅСЃС‹Р· СЃРµРјРµСЃС‚СЂ', 'Semester misplacements')}: <b>{audit.semester_misplacements?.length || 0}</b></span>
                                </div>
                                {(audit.lo_without_real_course || []).slice(0, 5).map(row => <div key={row.lo_code} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                                    вљ  {row.lo_code}: {row.lo_text} В· {localText('Р»СѓС‡С€Р°СЏ СЂРµР°Р»СЊРЅР°СЏ СЃРІСЏР·СЊ', 'РµТЈ Р¶Р°Т›СЃС‹ РЅР°Т›С‚С‹ Р±Р°Р№Р»Р°РЅС‹СЃ', 'best real link')} {Math.round((row.max_real_course_score || 0) * 100)}%
                                </div>)}
                                {(audit.weak_courses || []).slice(0, 5).map(row => <div key={row.course_id} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                                    вљ  {row.title} В· {t('semester')} {row.semester} В· AI {Math.round((row.model_score || 0) * 100)}% В· EPVO {Math.round((row.epvo_expert_score || 0) * 100)}%
                                </div>)}
                                {(audit.structural_foundations || []).slice(0, 5).map(row => <div key={`foundation-${row.course_id}`} style={{ marginTop: 7, fontSize: 12, color: '#315b7a' }}>
                                    в†і {row.title} В· {localText('РЅРµ Р·Р°РєСЂС‹РІР°РµС‚ LO РЅР°РїСЂСЏРјСѓСЋ, РЅРѕ СЏРІР»СЏРµС‚СЃСЏ РїРѕРґС‚РІРµСЂР¶РґС‘РЅРЅС‹Рј РїСЂРµСЂРµРєРІРёР·РёС‚РѕРј', 'LO-РЅС‹ С‚С–РєРµР»РµР№ Р¶Р°РїРїР°Р№РґС‹, Р±С–СЂР°Т› СЂР°СЃС‚Р°Р»Т“Р°РЅ РїСЂРµСЂРµРєРІРёР·РёС‚', 'indirect LO support as a confirmed prerequisite')}
                                </div>)}
                                {(audit.semester_misplacements || []).slice(0, 5).map(row => <div key={`semester-${row.course_id}`} style={{ marginTop: 7, fontSize: 12, color: '#7a4f00' }}>
                                    вљ  {row.title}: {t('semester')} {row.semester} в†’ {localText('СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ', 'Т±СЃС‹РЅС‹Р»Р°РґС‹', 'recommended')} {row.recommended_semester}
                                </div>)}
                            </CompactSection>
                        })()}
                        {currentPlan?.metrics?.optimizer && (
                            <CompactSection title={t('optimizer')} accent={'#3949ab'} defaultOpen={false}>
                                <h3 style={{ marginTop: 0 }}>{t('optimizer')}</h3>
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
                            <CompactSection title={t('international_quality')} subtitle={'OBE / ABET-style continuous improvement / CDIO integrated curriculum / Tuning competences'} accent={currentPlan.metrics.international_quality.passed ? '#2e7d32' : '#e67e22'} defaultOpen={false}>
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
                                            ? localText('РџР»Р°РЅ СѓР¶Рµ РїСЂРѕС€С‘Р» РјРµР¶РґСѓРЅР°СЂРѕРґРЅС‹Р№ С‡РµРє-Р»РёСЃС‚.', 'Р–РѕСЃРїР°СЂ С…Р°Р»С‹Т›Р°СЂР°Р»С‹Т› С‡РµРє-Р»РёСЃС‚РµРЅ У©С‚С‚С–.', 'The plan already passed the international checklist.')
                                            : localText('РџР»Р°РЅ С‚СЂРµР±СѓРµС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРіРѕ РёСЃРїСЂР°РІР»РµРЅРёСЏ.', 'Р–РѕСЃРїР°СЂ Р°РІС‚РѕРјР°С‚С‚С‹ С‚ТЇР·РµС‚СѓРґС– Т›Р°Р¶РµС‚ РµС‚РµРґС–.', 'The plan needs automatic repair.')}
                                    </strong>{' '}
                                    {localText(
                                        'РЎРёСЃС‚РµРјР° РїСЂРѕРІРµСЂСЏРµС‚ РєСЂРµРґРёС‚С‹, РЅР°РіСЂСѓР·РєСѓ РїРѕ СЃРµРјРµСЃС‚СЂР°Рј, РїСЂРµСЂРµРєРІРёР·РёС‚С‹, РїРѕРєСЂС‹С‚РёРµ СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ РѕР±СѓС‡РµРЅРёСЏ, РїСЂРµРґРјРµС‚РЅСѓСЋ СЂРµР»РµРІР°РЅС‚РЅРѕСЃС‚СЊ Рё Р·Р°С‰РёС‚Сѓ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹С… Р“РћРЎРћ-РєРѕРјРїРѕРЅРµРЅС‚РѕРІ. РљРЅРѕРїРєР° РЅРёР¶Рµ РёСЃРєР»СЋС‡Р°РµС‚ С‚РѕР»СЊРєРѕ Р·Р°РјРµРЅСЏРµРјС‹Рµ СЃР»Р°Р±С‹Рµ РґРёСЃС†РёРїР»РёРЅС‹, Р·Р°С‰РёС‰Р°РµС‚ Р“РћРЎРћ Рё Р·Р°РїСѓСЃРєР°РµС‚ РїРµСЂРµСЃР±РѕСЂРєСѓ A/B/C, РµСЃР»Рё СЌС‚Рѕ РґРµР№СЃС‚РІРёС‚РµР»СЊРЅРѕ РЅСѓР¶РЅРѕ.',
                                        'Р–ТЇР№Рµ РєСЂРµРґРёС‚С‚РµСЂРґС–, СЃРµРјРµСЃС‚СЂ Р¶ТЇРєС‚РµРјРµСЃС–РЅ, РїСЂРµСЂРµРєРІРёР·РёС‚С‚РµСЂРґС–, РѕТ›Сѓ РЅУ™С‚РёР¶РµР»РµСЂС–РЅ Т›Р°РјС‚СѓРґС‹, РїУ™РЅРґС–Рє СЃУ™Р№РєРµСЃС‚С–РєС‚С– Р¶У™РЅРµ РјС–РЅРґРµС‚С‚С– РњР–РњР‘РЎ РєРѕРјРїРѕРЅРµРЅС‚С‚РµСЂС–РЅ Т›РѕСЂТ“Р°СѓРґС‹ С‚РµРєСЃРµСЂРµРґС–. РўУ©РјРµРЅРґРµРіС– Р±Р°С‚С‹СЂРјР° С‚РµРє Р°СѓС‹СЃС‚С‹СЂСѓТ“Р° Р±РѕР»Р°С‚С‹РЅ У™Р»СЃС–Р· РїУ™РЅРґРµСЂРґС– Р°Р»С‹Рї С‚Р°СЃС‚Р°Р№РґС‹, РњР–РњР‘РЎ-С‚С‹ Т›РѕСЂТ“Р°Р№РґС‹ Р¶У™РЅРµ Т›Р°Р¶РµС‚ Р±РѕР»СЃР° A/B/C Т›Р°Р№С‚Р° Т›Т±СЂР°РґС‹.',
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
                                        {applyingQuality ? t('applying_quality_improvements') : `вњЁ ${t('apply_all_quality_improvements')}`}
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
                                                        {localText('Р§С‚Рѕ РїСЂРѕРІРµСЂСЏРµС‚ СЃРёСЃС‚РµРјР°', 'Р–ТЇР№Рµ РЅРµРЅС– С‚РµРєСЃРµСЂРµРґС–', 'What the system checks')}
                                                    </div>
                                                    <div>
                                                        {localText('Р РµР»РµРІР°РЅС‚РЅС‹Рµ РґРёСЃС†РёРїР»РёРЅС‹', 'РЎУ™Р№РєРµСЃ РїУ™РЅРґРµСЂ', 'Relevant courses')}: {rel.relevant_courses}/{rel.total_courses}.
                                                        {' '}{localText('РР· РЅРёС… Р·Р°С‰РёС‰РµРЅС‹ РєР°Рє Р“РћРЎРћ Р Рљ', 'РћРЅС‹ТЈ С–С€С–РЅРґРµ ТљР  РњР–РњР‘РЎ СЂРµС‚С–РЅРґРµ Т›РѕСЂТ“Р°Р»Т“Р°РЅ', 'Protected as RK regulatory')}: {rel.regulatory_protected_courses}.
                                                        {' '}{localText('РњРѕР¶РЅРѕ Р·Р°РјРµРЅРёС‚СЊ Р±РµР· СЂРёСЃРєР°', 'ТљР°СѓС–РїСЃС–Р· Р°СѓС‹СЃС‚С‹СЂСѓТ“Р° Р±РѕР»Р°РґС‹', 'Safely replaceable')}: {rel.replaceable_unsupported_courses}.
                                                    </div>
                                                    {rel.regulatory_examples?.length > 0 && (
                                                        <div style={{ marginTop: 6, color: '#475467' }}>
                                                            {localText('Р“РћРЎРћ РЅРµ СѓРґР°Р»СЏРµС‚СЃСЏ', 'РњР–РњР‘РЎ Р¶РѕР№С‹Р»РјР°Р№РґС‹', 'Regulatory courses are not removed')}: {rel.regulatory_examples.slice(0, 3).map(row => row.title).join('; ')}
                                                        </div>
                                                    )}
                                                    {rel.unsupported_examples?.length > 0 && (
                                                        <div style={{ marginTop: 6, color: '#8a4b00' }}>
                                                            {localText('РљР°РЅРґРёРґР°С‚С‹ РЅР° Р·Р°РјРµРЅСѓ', 'РђСѓС‹СЃС‚С‹СЂСѓТ“Р° ТЇРјС–С‚РєРµСЂР»РµСЂ', 'Replacement candidates')}: {rel.unsupported_examples.slice(0, 3).map(row => row.title).join('; ')}
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
                                                {check.passed ? 'вњ…' : 'вљ пёЏ'} {t(check.name)}
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
                                                                    {localizedCourseField(c.description_translations, c.description).slice(0, 220)}{localizedCourseField(c.description_translations, c.description).length > 220 ? 'вЂ¦' : ''}
                                                                </div>
                                                            )}
                                                            <div style={{ fontSize: '11px', color: '#666', marginTop: '2px' }}>
                                                                {c.academic_cycle && <>{localText('Р¦РёРєР»', 'Р¦РёРєР»', 'Cycle')}: <b>{c.academic_cycle}</b>{c.academic_cycle_source === 'inferred' ? ` (${localText('СЂР°СЃС‡С‘С‚ СЃРёСЃС‚РµРјС‹', 'Р¶ТЇР№Рµ РµСЃРµР±С–', 'system estimate')})` : ''}{' В· '}</>}
                                                                {localText('РљРѕРјРїРѕРЅРµРЅС‚', 'РљРѕРјРїРѕРЅРµРЅС‚', 'Component')}: {c.academic_component || componentLabel(c.cycle_component || c.type)}
                                                                {' В· '}{localText('РСЃС‚РѕС‡РЅРёРє', 'Р”РµСЂРµРєРєУ©Р·', 'Source')}: {
                                                                    c.course_source === 'rk_mandatory' ? localText('РѕР±СЏР·Р°С‚РµР»СЊРЅР°СЏ РґРёСЃС†РёРїР»РёРЅР° Р Рљ', 'ТљР  РјС–РЅРґРµС‚С‚С– РїУ™РЅС–', 'RK mandatory course')
                                                                    : c.course_source === 'ai_confirmed' ? localText('РїРѕРґС‚РІРµСЂР¶РґС‘РЅРЅР°СЏ Р·Р°РјРµРЅР° РР', 'Р–Р СЂР°СЃС‚Р°Р»Т“Р°РЅ Р°СѓС‹СЃС‚С‹СЂСѓ', 'AI-confirmed replacement')
                                                                    : c.course_source === 'bridge' ? localText('bridge-РјРѕРґСѓР»СЊ', 'bridge-РјРѕРґСѓР»СЊ', 'bridge module')
                                                                    : localText('СЂРµРїРѕР·РёС‚РѕСЂРёР№ РґРёСЃС†РёРїР»РёРЅ', 'РїУ™РЅРґРµСЂ СЂРµРїРѕР·РёС‚РѕСЂРёР№С–', 'course repository')
                                                                }
                                                                {c.course_code ? ` В· ${localText('РљРѕРґ', 'РљРѕРґ', 'Code')}: ${c.course_code}` : ''}
                                                            </div>
                                                            {c.course_id && !c.protected_by_goso && (
                                                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 5, fontSize: 11, color: excludedCourses[c.course_id] ? '#b71c1c' : '#5d6470', cursor: 'pointer' }}>
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={Boolean(excludedCourses[c.course_id])}
                                                                        onChange={() => toggleCourseExclusion(c.course_id, c.title)}
                                                                    />
                                                                    {excludedCourses[c.course_id]
                                                                        ? localText('Р‘СѓРґРµС‚ СѓР±СЂР°РЅР° РїСЂРё РїРµСЂРµРіРµРЅРµСЂР°С†РёРё', 'ТљР°Р№С‚Р° Т›Т±СЂСѓ РєРµР·С–РЅРґРµ Р°Р»С‹РЅР°РґС‹', 'Will be removed on regeneration')
                                                                        : localText('Р—Р°РјРµРЅРёС‚СЊ/СѓР±СЂР°С‚СЊ РїСЂРё СЃР»РµРґСѓСЋС‰РµР№ РіРµРЅРµСЂР°С†РёРё', 'РљРµР»РµСЃС– Т›Т±СЂСѓРґР° Р°СѓС‹СЃС‚С‹СЂСѓ/Р°Р»С‹Рї С‚Р°СЃС‚Р°Сѓ', 'Replace/remove on next generation')}
                                                                </label>
                                                            )}
                                                            {c.protected_by_goso && (
                                                                <div style={{ marginTop: 5, fontSize: 11, color: '#1b5e20', fontWeight: 600 }}>
                                                                    рџ›Ў {localText('РћР±СЏР·Р°С‚РµР»СЊРЅР°СЏ РґРёСЃС†РёРїР»РёРЅР° Р“РћРЎРћ Р Рљ вЂ” Р·Р°С‰РёС‰РµРЅР° РѕС‚ СѓРґР°Р»РµРЅРёСЏ Рё Р·Р°РјРµРЅС‹', 'ТљР  РњР–РњР‘РЎ РјС–РЅРґРµС‚С‚С– РїУ™РЅС– вЂ” Р¶РѕСЋРґР°РЅ Р¶У™РЅРµ Р°СѓС‹СЃС‚С‹СЂСѓРґР°РЅ Т›РѕСЂТ“Р°Р»Т“Р°РЅ', 'RK mandatory course вЂ” protected from removal and replacement')}
                                                                </div>
                                                            )}
                                                            {c.why_selected && (
                                                                <details style={{ marginTop: 6, fontSize: 11, color: '#586174' }}>
                                                                    <summary style={{ cursor: 'pointer', color: '#366092', fontWeight: 600 }}>
                                                                        {localText('РџРѕС‡РµРјСѓ РІС‹Р±СЂР°РЅР°?', 'РќРµРіРµ С‚Р°ТЈРґР°Р»РґС‹?', 'Why selected?')}
                                                                    </summary>
                                                                    <div style={{ marginTop: 5, lineHeight: 1.45 }}>
                                                                        <div>{c.why_selected.selection_reason}</div>
                                                                        <div>{c.why_selected.semester_reason}</div>
                                                                        <div style={{ marginTop: 5, padding: '6px 8px', background: '#f5f7fb', borderRadius: 6 }}>
                                                                            {localText(
                                                                                'РџСЂРѕС†РµРЅС‚С‹ РѕС‚РЅРѕСЃСЏС‚СЃСЏ Рє СЃРІСЏР·Рё РѕРґРЅРѕР№ РґРёСЃС†РёРїР»РёРЅС‹ СЃ РѕРґРЅРёРј LO. РР вЂ” РїСЂРѕРіРЅРѕР· РјРѕРґРµР»Рё РїРѕ С‚РµРєСЃС‚Р°Рј. Р•РџР’Рћ вЂ” РїРѕРґРґРµСЂР¶РєР° СЌС‚РѕР№ Р¶Рµ СЃРІСЏР·Рё РІ СЌРєСЃРїРµСЂС‚РЅС‹С… РґР°РЅРЅС‹С… Р•РџР’Рћ. РћРЅРё РЅРµ СЃРєР»Р°РґС‹РІР°СЋС‚СЃСЏ; РёС‚РѕРі Р±РµСЂС‘С‚СЃСЏ РїРѕ РЅР°РёР±РѕР»РµРµ РЅР°РґС‘Р¶РЅРѕРјСѓ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЋ.',
                                                                                'РџР°Р№С‹Р·РґР°СЂ Р±С–СЂ РїУ™РЅ РјРµРЅ Р±С–СЂ LO Р±Р°Р№Р»Р°РЅС‹СЃС‹РЅР° Р¶Р°С‚Р°РґС‹. Р–Р вЂ” РјУ™С‚С–РЅРґРµСЂ Р±РѕР№С‹РЅС€Р° РјРѕРґРµР»СЊ Р±РѕР»Р¶Р°РјС‹. Р–РћРћР‘Р‘ вЂ” СЃРѕР» Р±Р°Р№Р»Р°РЅС‹СЃС‚С‹ТЈ СЃР°СЂР°РїС‚Р°РјР°Р»С‹Т› РґРµСЂРµРєС‚РµСЂРґРµРіС– Т›РѕР»РґР°СѓС‹. РћР»Р°СЂ Т›РѕСЃС‹Р»РјР°Р№РґС‹.',
                                                                                'Percentages describe one course-to-LO link. AI is the text-model estimate; EPVO is expert support for the same link. They are not added.'
                                                                            )}
                                                                        </div>
                                                                        {c.why_selected.top_lo_matches?.length > 0 && (
                                                                            <div style={{ marginTop: 4 }}>
                                                                        <div style={{ fontWeight: 600, marginBottom: 3 }}>
                                                                            {localText('РЎРІСЏР·Рё СЃ СЂРµР·СѓР»СЊС‚Р°С‚Р°РјРё РѕР±СѓС‡РµРЅРёСЏ:', 'РћТ›Сѓ РЅУ™С‚РёР¶РµР»РµСЂС–РјРµРЅ Р±Р°Р№Р»Р°РЅС‹СЃ:', 'Learning-outcome links:')}
                                                                        </div>
                                                                        <div style={{ marginBottom: 5, color: '#607d8b', fontSize: 11 }}>
                                                                            {localText(
                                                                                'РљР°Рє С‡РёС‚Р°С‚СЊ: вЂњРёС‚РѕРівЂќ вЂ” РЅР°СЃРєРѕР»СЊРєРѕ РґРёСЃС†РёРїР»РёРЅР° СЂРµР°Р»СЊРЅРѕ Р·Р°РєСЂС‹РІР°РµС‚ СЌС‚РѕС‚ LO РІ РїР»Р°РЅРµ; вЂњРРвЂќ вЂ” РїСЂРѕРіРЅРѕР· РјРѕРґРµР»Рё РїРѕ С‚РµРєСЃС‚Р°Рј; вЂњР•РџР’РћвЂќ вЂ” РїРѕС…РѕР¶Р°СЏ СЌРєСЃРїРµСЂС‚РЅР°СЏ РѕС†РµРЅРєР° РёР· Р±Р°Р·С‹ Р•РџР’Рћ. Р­С‚Рѕ С‚СЂРё СЂР°Р·РЅС‹С… РїСЂРёР·РЅР°РєР° РѕРґРЅРѕР№ СЃРІСЏР·Рё, РѕРЅРё РЅРµ СЃСѓРјРјРёСЂСѓСЋС‚СЃСЏ.',
                                                                                'РћТ›Сѓ С‚У™СЂС‚С–Р±С–: вЂњТ›РѕСЂС‹С‚С‹РЅРґС‹вЂќ вЂ” РїУ™РЅ РѕСЃС‹ LO-РЅС‹ Р¶РѕСЃРїР°СЂРґР° Т›Р°РЅС€Р°Р»С‹Т›С‚С‹ Р¶Р°Р±Р°РґС‹; вЂњР–РвЂќ вЂ” РјУ™С‚С–РЅРґРµСЂ Р±РѕР№С‹РЅС€Р° РјРѕРґРµР»СЊ Р±РѕР»Р¶Р°РјС‹; вЂњР•РџР’РћвЂќ вЂ” Р•РџР’Рћ Р±Р°Р·Р°СЃС‹РЅРґР°Т“С‹ Т±Т›СЃР°СЃ СЃР°СЂР°РїС‚Р°РјР°Р»С‹Т› Р±Р°Т“Р°. Р‘Т±Р»Р°СЂ Р±С–СЂ Р±Р°Р№Р»Р°РЅС‹СЃС‚С‹ТЈ ТЇС€ Р±У©Р»РµРє Р±РµР»РіС–СЃС–, Т›РѕСЃС‹Р»РјР°Р№РґС‹.',
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
                                                                                            {lo.lo_code} В· {localText('РёС‚РѕРі', 'Т›РѕСЂС‹С‚С‹РЅРґС‹', 'effective')}: {Math.round((lo.effective_score ?? lo.score ?? 0) * 100)}%
                                                                                            {lo.ai_score != null && (
                                                                                                <small style={{ marginLeft: 5, color: '#455a64' }}>
                                                                                                    {localText('РР', 'Р–Р', 'AI')} {Math.round((lo.ai_score || 0) * 100)}%
                                                                                                </small>
                                                                                            )}
                                                                                            {lo.expert_score != null && (
                                                                                                <small style={{ marginLeft: 5, color: '#6a4f00' }}>
                                                                                                    {localText('Р•РџР’Рћ', 'Р•РџР’Рћ', 'EPVO')} {Math.round((lo.expert_score || 0) * 100)}%
                                                                                                </small>
                                                                                            )}
                                                                                            {lo.source === 'bridge_target' && (
                                                                                                <small style={{ marginLeft: 5, color: '#7b1fa2' }}>
                                                                                                    {localText('bridge', 'bridge', 'bridge')}
                                                                                                </small>
                                                                                            )}
                                                                                            {lo.weak_evidence && (
                                                                                                <small style={{ marginLeft: 5, color: '#b26a00' }}>
                                                                                                    {localText('СЃР»Р°Р±Р°СЏ СЃРІСЏР·СЊ', 'У™Р»СЃС–Р· Р±Р°Р№Р»Р°РЅС‹СЃ', 'weak link')}
                                                                                                </small>
                                                                                            )}
                                                                                            {(matchFeedbackState[`${c.course_id}:${lo.lo_id}`] || lo.expert_feedback?.verdict) && (
                                                                                                <small style={{ marginLeft: 5, color: '#1b5e20' }}>вњ“ {matchFeedbackState[`${c.course_id}:${lo.lo_id}`] || lo.expert_feedback?.verdict}</small>
                                                                                            )}
                                                                                        </span>
                                                                                        <div style={{ marginTop: 2, maxWidth: 340, color: '#607d8b', fontSize: 11 }}>
                                                                                            {localText(
                                                                                                'РС‚РѕРі вЂ” РёС‚РѕРіРѕРІР°СЏ СЃРёР»Р° СЃРІСЏР·Рё СЌС‚РѕР№ РґРёСЃС†РёРїР»РёРЅС‹ СЃ СЌС‚РёРј LO. РР вЂ” РїСЂРѕРіРЅРѕР· РјРѕРґРµР»Рё РїРѕ С‚РµРєСЃС‚Р°Рј. Р•РџР’Рћ вЂ” РІРѕСЃРїСЂРѕРёР·РІРµРґС‘РЅРЅР°СЏ СЌРєСЃРїРµСЂС‚РЅР°СЏ РѕС†РµРЅРєР° РёР· Р±Р°Р·С‹. РћРЅРё РЅРµ СЃРєР»Р°РґС‹РІР°СЋС‚СЃСЏ.',
                                                                                                'ТљРѕСЂС‹С‚С‹РЅРґС‹ вЂ” РѕСЃС‹ РїУ™РЅРЅС–ТЈ РѕСЃС‹ РћРќ-РјРµРЅ Р±Р°Р№Р»Р°РЅС‹СЃ РєТЇС€С–. Р–Р вЂ” РјУ™С‚С–РЅРґРµСЂ Р±РѕР№С‹РЅС€Р° РјРѕРґРµР»СЊ Р±РѕР»Р¶Р°РјС‹. Р•РџР’Рћ вЂ” Р±Р°Р·Р°РґР°Т“С‹ СЃР°СЂР°РїС‚Р°РјР°Р»С‹Т› Р±Р°Т“Р°РЅС‹ Т›Р°Р»РїС‹РЅР° РєРµР»С‚С–СЂСѓ. РћР»Р°СЂ Т›РѕСЃС‹Р»РјР°Р№РґС‹.',
                                                                                                'Effective is the final strength for this courseв†’LO link. AI is the text model prediction. EPVO is reconstructed expert evidence. They are not added together.'
                                                                                            )}
                                                                                        </div>
                                                                                        <div style={{ marginTop: 2, maxWidth: 310, color: '#4f5d6b' }}>
                                                                                            <b>{lo.lo_code}:</b> {lo.lo_text}
                                                                                        </div>
                                                                                        {lo.explanation && (
                                                                                            <div style={{ marginTop: 3, maxWidth: 360, color: '#37474f', fontSize: 11, background: '#fffde7', border: '1px solid #fff59d', borderRadius: 6, padding: '5px 7px' }}>
                                                                                                {lo.explanation}
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
                                                                                    {localText('РџСЂРµ- Рё РїРѕСЃС‚СЂРµРєРІРёР·РёС‚С‹ РІ СЌС‚РѕРј РїР»Р°РЅРµ', 'РћСЃС‹ Р¶РѕСЃРїР°СЂРґР°Т“С‹ РїСЂРµ- Р¶У™РЅРµ РїРѕСЃС‚СЂРµРєРІРёР·РёС‚С‚РµСЂ', 'Pre- and post-requisites in this plan')}
                                                                                </div>
                                                                                <div style={{ color: '#607d8b', marginBottom: 5 }}>
                                                                                    {localText(
                                                                                        'РџРѕРєР°Р·С‹РІР°СЋС‚СЃСЏ С‚РѕР»СЊРєРѕ РґРёСЃС†РёРїР»РёРЅС‹, РєРѕС‚РѕСЂС‹Рµ СЂРµР°Р»СЊРЅРѕ РµСЃС‚СЊ РІ С‚РµРєСѓС‰РµРј РІР°СЂРёР°РЅС‚Рµ РїР»Р°РЅР°.',
                                                                                        'РўРµРє Р°Т“С‹РјРґР°Т“С‹ Р¶РѕСЃРїР°СЂ РЅТ±СЃТ›Р°СЃС‹РЅРґР° Р±Р°СЂ РїУ™РЅРґРµСЂ РєУ©СЂСЃРµС‚С–Р»РµРґС–.',
                                                                                        'Only courses that are actually present in the current plan variant are shown.'
                                                                                    )}
                                                                                </div>
                                                                                <div style={{ display: 'grid', gap: 5 }}>
                                                                                    <div>
                                                                                        <b>{localText('Р”Рѕ СЌС‚РѕР№ РґРёСЃС†РёРїР»РёРЅС‹:', 'РћСЃС‹ РїУ™РЅРіРµ РґРµР№С–РЅ:', 'Before this course:')}</b>{' '}
                                                                                        {c.plan_requisites?.prerequisites?.length > 0
                                                                                            ? c.plan_requisites.prerequisites.map(item => (
                                                                                                <span key={`pre-${item.course_id}`} title={`${localText('РЎРµРјРµСЃС‚СЂ', 'РЎРµРјРµСЃС‚СЂ', 'Semester')} ${item.semester} В· ${item.credits} ${localText('РєСЂРµРґРёС‚РѕРІ', 'РєСЂРµРґРёС‚', 'credits')}`} style={{ display: 'inline-block', margin: '2px 4px 2px 0', padding: '2px 6px', borderRadius: 999, background: '#eef4ff', color: '#244b78' }}>
                                                                                                    {localText('РЎРµРј.', 'РЎРµРј.', 'Sem.')} {item.semester}: {item.title}
                                                                                                </span>
                                                                                            ))
                                                                                            : <span style={{ color: '#8a96a3' }}>{localText('РІ РїР»Р°РЅРµ РЅРµС‚ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹С… РїСЂРµРґС€РµСЃС‚РІСѓСЋС‰РёС… РґРёСЃС†РёРїР»РёРЅ', 'Р¶РѕСЃРїР°СЂРґР° РјС–РЅРґРµС‚С‚С– Р°Р»РґС‹ТЈТ“С‹ РїУ™РЅРґРµСЂ Р¶РѕТ›', 'no required earlier courses in the plan')}</span>
                                                                                        }
                                                                                    </div>
                                                                                    <div>
                                                                                        <b>{localText('РџРѕСЃР»Рµ РЅРµС‘ РѕРїРёСЂР°СЋС‚СЃСЏ:', 'РћРґР°РЅ РєРµР№С–РЅ СЃТЇР№РµРЅРµС‚С–РЅ РїУ™РЅРґРµСЂ:', 'Courses that depend on it:')}</b>{' '}
                                                                                        {c.plan_requisites?.postrequisites?.length > 0
                                                                                            ? c.plan_requisites.postrequisites.map(item => (
                                                                                                <span key={`post-${item.course_id}`} title={`${localText('РЎРµРјРµСЃС‚СЂ', 'РЎРµРјРµСЃС‚СЂ', 'Semester')} ${item.semester} В· ${item.credits} ${localText('РєСЂРµРґРёС‚РѕРІ', 'РєСЂРµРґРёС‚', 'credits')}`} style={{ display: 'inline-block', margin: '2px 4px 2px 0', padding: '2px 6px', borderRadius: 999, background: '#eefaf3', color: '#1b5e20' }}>
                                                                                                    {localText('РЎРµРј.', 'РЎРµРј.', 'Sem.')} {item.semester}: {item.title}
                                                                                                </span>
                                                                                            ))
                                                                                            : <span style={{ color: '#8a96a3' }}>{localText('РІ С‚РµРєСѓС‰РµРј РїР»Р°РЅРµ РЅРµС‚ РґРёСЃС†РёРїР»РёРЅ, РєРѕС‚РѕСЂС‹Рµ СЏРІРЅРѕ С‚СЂРµР±СѓСЋС‚ РµС‘ РєР°Рє РїСЂРµСЂРµРєРІРёР·РёС‚', 'Р°Т“С‹РјРґР°Т“С‹ Р¶РѕСЃРїР°СЂРґР° РѕРЅС‹ РїСЂРµСЂРµРєРІРёР·РёС‚ СЂРµС‚С–РЅРґРµ С‚Р°Р»Р°Рї РµС‚РµС‚С–РЅ РїУ™РЅРґРµСЂ Р¶РѕТ›', 'no later courses explicitly require it in this plan')}</span>
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
                                                    >{lo.code}<span className="semester-lo-tooltip"><strong>{lo.code} В· {t(lo.kind === 'course' ? 'course_outcome' : 'programme_outcome')}</strong>{lo.text}<small>{t('evidence_courses')}: {lo.courses.join(', ')}</small>{lo.score != null && <small>{t('connection_strength')}: {Math.round(lo.score * 100)}%</small>}</span></span>)}
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

