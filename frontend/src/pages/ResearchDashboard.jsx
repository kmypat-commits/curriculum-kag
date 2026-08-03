import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'
import { useLanguage } from '../contexts/LanguageContext'
import LanguageSelector from '../components/LanguageSelector'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatApiError } from '../utils/errors'

const pct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
const num = value => Number(value || 0).toLocaleString()

export default function ResearchDashboard() {
    const { t, language } = useLanguage()
    const [data, setData] = useState(null)
    const [feedback, setFeedback] = useState(null)
    const [baseline, setBaseline] = useState(null)
    const [gnnManifest, setGnnManifest] = useState(null)
    const [gnnStatus, setGnnStatus] = useState(null)
    const [lstmStatus, setLstmStatus] = useState(null)
    const [articleReport, setArticleReport] = useState(null)
    const [startingGnn, setStartingGnn] = useState(false)
    const [startingLstm, setStartingLstm] = useState(false)
    const [error, setError] = useState(null)

    const l = (ru, kk, en) => language === 'kk' ? kk : language === 'en' ? en : ru

    const loadAll = async () => {
        try {
            const [passportRes, feedbackRes, baselineRes, manifestRes, statusRes, lstmStatusRes, articleReportRes] = await Promise.allSettled([
                axios.get('/api/epvo/dataset-passport'),
                axios.get('/api/epvo/expert-feedback?limit=20'),
                axios.get('/api/epvo/reproducible-baseline'),
                axios.get('/api/epvo/lstm-gnn-manifest'),
                axios.get('/api/epvo/lstm-gnn-smoke/status'),
                axios.get('/api/epvo/lstm-smoke/status'),
                axios.get('/api/epvo/article-experiment-report'),
            ])
            if (passportRes.status === 'fulfilled') setData(passportRes.value.data)
            else setError(formatApiError(passportRes.reason, t('error')))
            setFeedback(feedbackRes.status === 'fulfilled' ? feedbackRes.value.data : { total: 0, verdict_counts: {}, recent: [] })
            setBaseline(baselineRes.status === 'fulfilled' ? baselineRes.value.data : null)
            setGnnManifest(manifestRes.status === 'fulfilled' ? manifestRes.value.data : null)
            setGnnStatus(statusRes.status === 'fulfilled' ? statusRes.value.data : null)
            setLstmStatus(lstmStatusRes.status === 'fulfilled' ? lstmStatusRes.value.data : null)
            setArticleReport(articleReportRes.status === 'fulfilled' ? articleReportRes.value.data : null)
        } catch (err) {
            setError(formatApiError(err, t('error')))
        }
    }

    useEffect(() => {
        loadAll()
    }, [])

    const bestModel = baseline?.best_model || data?.benchmarks?.[0]
    const gnnTest = gnnStatus?.test
    const gnnBeatsBest = useMemo(() => {
        if (gnnStatus?.comparison) return Boolean(gnnStatus.comparison.beats_baseline)
        if (!gnnTest || !bestModel) return false
        return Number(gnnTest.roc_auc || 0) > Number(bestModel.roc_auc || 0)
            && Number(gnnTest.pr_auc || 0) > Number(bestModel.pr_auc || 0)
            && Number(gnnTest.f1 || 0) >= Number(bestModel.f1 || 0)
    }, [gnnTest, bestModel, gnnStatus?.comparison])

    const downloadPassportCsv = async () => {
        const response = await axios.get('/api/epvo/dataset-passport/export.csv', { responseType: 'blob' })
        const url = URL.createObjectURL(response.data)
        const link = document.createElement('a')
        link.href = url
        link.download = 'dataset-passport.csv'
        link.click()
        URL.revokeObjectURL(url)
    }

    const downloadArticleMarkdown = async () => {
        const response = await axios.get('/api/epvo/article-experiment-report.md', { responseType: 'blob' })
        const url = URL.createObjectURL(response.data)
        const link = document.createElement('a')
        link.href = url
        link.download = 'article-experiment-report.md'
        link.click()
        URL.revokeObjectURL(url)
    }

    const startGnnSmoke = async () => {
        const ok = window.confirm(l(
            'Запустить небольшой локальный GNN smoke-run? Это щадящий тест, не полный тяжёлый прогон.',
            'Шағын жергілікті GNN smoke-run іске қосылсын ба? Бұл толық ауыр оқыту емес, жеңіл тест.',
            'Start a small local GNN smoke run? This is a light test, not full heavy training.',
        ))
        if (!ok) return
        setStartingGnn(true)
        try {
            const response = await axios.post('/api/epvo/lstm-gnn-smoke/run', {})
            setGnnStatus(response.data)
        } finally {
            setStartingGnn(false)
        }
    }

    const refreshGnnStatus = async () => {
        const response = await axios.get('/api/epvo/lstm-gnn-smoke/status')
        setGnnStatus(response.data)
    }

    const startLstmSmoke = async () => {
        const ok = window.confirm(l(
            'Запустить небольшой LSTM smoke-run? Это короткий тест, не полный ночной прогон.',
            'Шағын LSTM smoke-run іске қосылсын ба? Бұл толық түнгі прогон емес, қысқа тест.',
            'Start a small LSTM smoke run? This is a short test, not a full overnight run.',
        ))
        if (!ok) return
        setStartingLstm(true)
        try {
            const response = await axios.post('/api/epvo/lstm-smoke/run', {})
            setLstmStatus(response.data)
        } finally {
            setStartingLstm(false)
        }
    }

    const refreshLstmStatus = async () => {
        const response = await axios.get('/api/epvo/lstm-smoke/status')
        setLstmStatus(response.data)
    }

    if (error) {
        return (
            <div className="workspace-page">
                <header className="workspace-header"><div className="container"><Link to="/">← {t('back')}</Link><h1>{t('research_dashboard')}</h1></div></header>
                <main className="container workspace-main"><div className="card" style={{ borderLeft: '5px solid #c62828' }}>{error}</div></main>
            </div>
        )
    }
    if (!data) return <LoadingSpinner />

    const n = data.normalized || {}
    const counts = data.counts || {}
    const created = data.created_at ? new Date(data.created_at).toLocaleString(language === 'en' ? 'en-US' : language === 'kk' ? 'kk-KZ' : 'ru-RU') : '—'
    const planSummary = baseline?.plan_audit?.summary || {}
    const readiness = baseline?.readiness || {}

    return (
        <div className="workspace-page">
            <header className="workspace-header">
                <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <Link to="/">← {t('back')}</Link>
                        <h1>{t('research_dashboard')}</h1>
                        <p className="page-subtitle">{l('Паспорт данных, benchmark моделей и готовность LSTM/GNN.', 'Деректер паспорты, модель benchmark және LSTM/GNN дайындығы.', 'Dataset passport, model benchmark, and LSTM/GNN readiness.')}</p>
                    </div>
                    <LanguageSelector />
                </div>
            </header>
            <main className="container workspace-main">
                <section className="card" style={{ borderLeft: '4px solid #2f80ed' }}>
                    <h2 style={{ marginTop: 0 }}>Коротко о качестве системы</h2>
                    <div className="quick-grid">
                        <div><b>Данные</b><br />Система использует нормализованные программы и дисциплины ЕПВО, а не случайный список предметов.</div>
                        <div><b>Что проверяется</b><br />Связь дисциплины с результатом обучения, порядок пререквизитов, кредиты и нагрузка по семестрам.</div>
                        <div><b>Как понимать оценку</b><br />Модель предлагает связь, но эксперт может подтвердить, ослабить или отклонить её. Решение остаётся за экспертом.</div>
                    </div>
                    <p className="page-subtitle" style={{ marginBottom: 0 }}>Подробные метрики нужны для исследования; для работы с ОП достаточно смотреть качество плана и экспертные подтверждения.</p>
                </section>
                <div className="stat-grid">
                    <div className="stat-card"><div className="stat-value">{num(n.raw_programs)}</div><div className="stat-label">{t('epvo_programs')}</div></div>
                    <div className="stat-card"><div className="stat-value">{num(n.normalized_disciplines)}</div><div className="stat-label">{t('normalized_courses')}</div></div>
                    <div className="stat-card"><div className="stat-value">{num(n.expert_links)}</div><div className="stat-label">{t('expert_links')}</div></div>
                    <div className="stat-card"><div className="stat-value">{num(feedback?.total || n.expert_feedback)}</div><div className="stat-label">{l('Экспертные правки', 'Сарапшы түзетулері', 'Expert feedback')}</div></div>
                </div>

                <section className="card">
                    <div className="section-head">
                        <h2>{t('dataset_passport')}</h2>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <button className="btn btn-secondary" onClick={downloadPassportCsv}>CSV</button>
                            <span className="status-pill status-active">seed {data.seed}</span>
                        </div>
                    </div>
                    <p className="page-subtitle" style={{ fontSize: 13 }}>{l('Сформирован', 'Құрылған', 'Created')}: {created}. {data.split_policy}</p>
                    <div className="quick-grid">
                        <div>
                            <p><b>{l('Обучение', 'Оқыту', 'Train')}:</b> {num(counts.pairs_train)}</p>
                            <p><b>{l('Валидация', 'Валидация', 'Validation')}:</b> {num(counts.pairs_validation)}</p>
                            <p><b>{l('Тест', 'Тест', 'Test')}:</b> {num(counts.pairs_test)}</p>
                            <p><b>{l('Размеченные пары', 'Белгіленген жұптар', 'Labeled pairs')}:</b> {num(counts.labeled_pairs)}</p>
                            <p><b>{l('Сырые экспертные проверки', 'Шикі сарапшы тексерулері', 'Raw expert checks')}:</b> {num(n.raw_expert_checks)}</p>
                        </div>
                        <div>
                            {(data.files || []).map(file => (
                                <p key={file.name}><b>{file.name}</b><br /><code title={file.sha256}>SHA-256: {String(file.sha256 || '').slice(0, 16)}…</code></p>
                            ))}
                        </div>
                    </div>
                </section>

                <section className="card">
                    <div className="section-head">
                        <h2>{t('model_benchmark')}</h2>
                        <span>{t('independent_test')}</span>
                    </div>
                    <div className="table-wrap">
                        <table className="table">
                            <thead><tr><th>{t('model')}</th><th>{l('ROC-AUC', 'ROC-AUC', 'ROC-AUC')}</th><th>{l('PR-AUC', 'PR-AUC', 'PR-AUC')}</th><th>F1</th><th>{l('Полнота', 'Толықтық', 'Recall')}</th><th>{l('Полнота@10', 'Толықтық@10', 'Recall@10')}</th><th>MRR</th><th>nDCG@10</th><th>{t('examples')}</th></tr></thead>
                            <tbody>
                                {(data.benchmarks || []).map(row => (
                                    <tr key={row.name}>
                                        <td><b>{row.name}</b>{bestModel?.name === row.name && <span className="status-pill status-active" style={{ marginLeft: 8 }}>{l('лучший', 'үздік', 'best')}</span>}</td>
                                        <td>{pct(row.roc_auc)}</td>
                                        <td>{pct(row.pr_auc)}</td>
                                        <td>{pct(row.f1)}</td>
                                        <td>{pct(row.recall)}</td>
                                        <td>{pct(row.recall_at_10)}</td>
                                        <td>{pct(row.mrr)}</td>
                                        <td>{pct(row.ndcg_at_10)}</td>
                                        <td>{row.examples}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <p className="page-subtitle" style={{ fontSize: 13 }}>{data.ranking_metrics_note}</p>
                </section>

                <section className="card">
                    <div className="section-head">
                        <h2>{l('Baseline перед LSTM/GNN', 'LSTM/GNN алдындағы baseline', 'Baseline before LSTM/GNN')}</h2>
                        <span className={planSummary.active_plans_with_hard_violations ? 'status-pill status-draft' : 'status-pill status-active'}>
                            {l('Активные планы с жёсткими нарушениями', 'Қатаң бұзушылықтары бар белсенді жоспарлар', 'Active plans with hard violations')}: {planSummary.active_plans_with_hard_violations ?? '—'}
                        </span>
                    </div>
                    <div className="quick-grid">
                        <div><b>{l('Проекты', 'Жобалар', 'Projects')}</b><br />{num(planSummary.projects)}</div>
                        <div><b>{l('Планы', 'Жоспарлар', 'Plans')}</b><br />{num(planSummary.plans)}</div>
                        <div><b>{l('Одинаковые A/B/C', 'Бірдей A/B/C', 'Non-distinct A/B/C')}</b><br />{num(planSummary.non_distinct_abc)}</div>
                        <div><b>{l('Hard violations всего', 'Hard violations барлығы', 'Hard violations total')}</b><br />{num(planSummary.plans_with_hard_violations)}</div>
                    </div>
                    <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {Object.entries(readiness).filter(([key]) => key !== 'note').map(([key, value]) => (
                            <span key={key} className={value === true ? 'status-pill status-active' : value === false ? 'status-pill status-draft' : 'status-pill'} title={key}>
                                {key}: {String(value)}
                            </span>
                        ))}
                    </div>
                    <p className="page-subtitle" style={{ fontSize: 13 }}>{readiness.note}</p>
                </section>

                <section className="card">
                    <div className="section-head">
                        <h2>{l('Controlled LSTM/GNN', 'Controlled LSTM/GNN', 'Controlled LSTM/GNN')}</h2>
                        <span className="status-pill">{gnnStatus?.state || 'idle'}</span>
                    </div>
                    <p className="page-subtitle" style={{ fontSize: 13 }}>
                        {l(
                            'Правило внедрения: GNN/LSTM можно подключать к генератору только если на frozen split он устойчиво лучше SBERT 40k.',
                            'Енгізу ережесі: GNN/LSTM frozen split бойынша SBERT 40k моделінен тұрақты жақсы болса ғана генераторға қосылады.',
                            'Integration rule: GNN/LSTM can be connected to generation only if it consistently beats SBERT 40k on the frozen split.',
                        )}
                    </p>
                    <div className="quick-grid">
                        <div>
                            <b>{l('Текущий лучший baseline', 'Қазіргі үздік baseline', 'Current best baseline')}</b><br />
                            {bestModel?.name || '—'} · ROC-AUC {pct(bestModel?.roc_auc)} · PR-AUC {pct(bestModel?.pr_auc)} · F1 {pct(bestModel?.f1)}
                        </div>
                        <div>
                            <b>{l('Проверка GNN', 'GNN тексеруі', 'GNN smoke')}</b><br />
                            {gnnTest ? <>ROC-AUC {pct(gnnTest.roc_auc)} · PR-AUC {pct(gnnTest.pr_auc)} · F1 {pct(gnnTest.f1)}</> : l('метрик пока нет', 'метрика әлі жоқ', 'no metrics yet')}
                        </div>
                        <div>
                            <b>{l('Проверка LSTM', 'LSTM тексеруі', 'LSTM smoke')}</b><br />
                            {lstmStatus?.test ? <>ROC-AUC {pct(lstmStatus.test.roc_auc)} · PR-AUC {pct(lstmStatus.test.pr_auc)} · F1 {pct(lstmStatus.test.f1)}</> : `${lstmStatus?.state || 'idle'} · ${l('метрик пока нет', 'метрика әлі жоқ', 'no metrics yet')}`}
                        </div>
                        <div>
                            <b>{l('Решение', 'Шешім', 'Decision')}</b><br />
                            <span style={{ color: gnnBeatsBest ? '#1b5e20' : '#8a5a00' }}>
                                {gnnBeatsBest
                                    ? l('можно готовить интеграцию', 'интеграция дайындауға болады', 'integration can be prepared')
                                    : l('не внедрять, оставить как эксперимент', 'енгізбеу, эксперимент ретінде қалдыру', 'do not integrate; keep as experiment')}
                            </span>
                        </div>
                    </div>
                    {gnnStatus?.comparison?.deltas && (
                        <div style={{ marginTop: 10, fontSize: 13, color: '#566' }}>
                            Δ ROC-AUC {pct(gnnStatus.comparison.deltas.roc_auc)}, Δ PR-AUC {pct(gnnStatus.comparison.deltas.pr_auc)}, Δ F1 {pct(gnnStatus.comparison.deltas.f1)}
                            <br />{gnnStatus.comparison.guardrail}
                        </div>
                    )}
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
                        <button className="btn btn-primary" onClick={startGnnSmoke} disabled={startingGnn || gnnStatus?.state === 'running'}>
                            {startingGnn ? l('Запуск…', 'Іске қосу…', 'Starting…') : l('Запустить GNN smoke', 'GNN smoke іске қосу', 'Run GNN smoke')}
                        </button>
                        <button className="btn btn-secondary" onClick={refreshGnnStatus}>{l('Обновить статус', 'Күйді жаңарту', 'Refresh status')}</button>
                        <button className="btn btn-primary" onClick={startLstmSmoke} disabled={startingLstm || lstmStatus?.state === 'running'}>
                            {startingLstm ? l('Запуск…', 'Іске қосу…', 'Starting…') : l('Запустить LSTM smoke', 'LSTM smoke іске қосу', 'Run LSTM smoke')}
                        </button>
                        <button className="btn btn-secondary" onClick={refreshLstmStatus}>{l('Обновить LSTM', 'LSTM жаңарту', 'Refresh LSTM')}</button>
                    </div>
                    {gnnStatus?.message && <p className="page-subtitle" style={{ fontSize: 13 }}>{gnnStatus.message}</p>}
                    {lstmStatus?.message && <p className="page-subtitle" style={{ fontSize: 13 }}>{lstmStatus.message}</p>}
                    {gnnManifest?.experiments?.length > 0 && (
                        <details style={{ marginTop: 10 }}>
                            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>{l('Команды controlled-run', 'Controlled-run командалары', 'Controlled-run commands')}</summary>
                            <div style={{ display: 'grid', gap: 10, marginTop: 8 }}>
                                {gnnManifest.experiments.map(exp => (
                                    <div key={exp.name} style={{ padding: 8, borderRadius: 7, background: '#f7f9fc', border: '1px solid #e4edf7' }}>
                                        <b>{exp.name}</b> <span className="status-pill">{exp.status || 'ready'}</span>
                                        <div style={{ fontSize: 12, color: '#566', marginTop: 4 }}>{exp.leakage_control || exp.guardrail}</div>
                                        {exp.safe_smoke_command && <code style={{ display: 'block', whiteSpace: 'pre-wrap', marginTop: 8 }}>{exp.safe_smoke_command}</code>}
                                    </div>
                                ))}
                            </div>
                        </details>
                    )}
                    {gnnStatus?.['gnn-smoke.stderr.log'] && (
                        <details style={{ marginTop: 10 }}>
                            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>{l('Хвост stderr', 'stderr соңғы жолдары', 'stderr tail')}</summary>
                            <code style={{ display: 'block', whiteSpace: 'pre-wrap', marginTop: 8 }}>{gnnStatus['gnn-smoke.stderr.log']}</code>
                        </details>
                    )}
                </section>

                {articleReport && (
                    <section className="card">
                        <div className="section-head">
                            <h2>{l('Отчёт для научной статьи', 'Ғылыми мақалаға есеп', 'Article-ready report')}</h2>
                            <button className="btn btn-secondary" onClick={downloadArticleMarkdown}>{l('Markdown', 'Markdown', 'Markdown')}</button>
                        </div>
                        <p className="page-subtitle" style={{ fontSize: 13 }}>{articleReport.title_ru}</p>
                        <div className="quick-grid">
                            <div><b>{l('Моделей в сравнении', 'Салыстырылған модельдер', 'Compared models')}</b><br />{articleReport.models?.length || 0}</div>
                            <div><b>{l('Лучший baseline', 'Үздік baseline', 'Best baseline')}</b><br />{articleReport.best_model?.name || '—'}</div>
                            <div><b>GNN</b><br />{articleReport.controlled_experiment?.gnn_available ? l('результат сохранён', 'нәтиже сақталды', 'result saved') : '—'}</div>
                            <div><b>{l('LSTM', 'LSTM', 'LSTM')}</b><br />{articleReport.controlled_experiment?.lstm_available ? l('результат сохранён', 'нәтиже сақталды', 'result saved') : l('ожидает запуска', 'іске қосуды күтеді', 'waiting for run')}</div>
                        </div>
                        <p style={{ marginTop: 12, fontSize: 13 }}>{articleReport.conclusion_ru}</p>
                    </section>
                )}

                <section className="card">
                    <div className="section-head">
                        <h2>{l('Training Data / экспертные правки', 'Training Data / сарапшы түзетулері', 'Training Data / Expert Feedback')}</h2>
                        <span>{num(feedback?.total)}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                        {Object.entries(feedback?.verdict_counts || {}).map(([verdict, count]) => <span key={verdict} className="status-pill">{verdict}: {count}</span>)}
                    </div>
                    <div className="table-wrap">
                        <table className="table">
                            <thead><tr><th>{l('Решение эксперта', 'Сарапшы шешімі', 'Verdict')}</th><th>{l('Дисциплина', 'Пән', 'Course')}</th><th>LO</th><th>{l('Оценка модели', 'Модель бағасы', 'Model score')}</th><th>{l('Дата', 'Күні', 'Date')}</th></tr></thead>
                            <tbody>
                                {(feedback?.recent || []).map(row => (
                                    <tr key={row.id}>
                                        <td><b>{row.verdict}</b></td>
                                        <td>{row.course_title}</td>
                                        <td title={row.lo_text}>{row.lo_code}</td>
                                        <td>{row.model_score == null ? '—' : Math.round(row.model_score * 100) + '%'}</td>
                                        <td>{row.created_at ? new Date(row.created_at).toLocaleString(language === 'en' ? 'en-US' : language === 'kk' ? 'kk-KZ' : 'ru-RU') : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            </main>
        </div>
    )
}
