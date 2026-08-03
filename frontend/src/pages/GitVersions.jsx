import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../contexts/AuthContext'
import LanguageSelector from '../components/LanguageSelector'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatApiError } from '../utils/errors'
import { useLanguage } from '../contexts/LanguageContext'

const statusLabels = {
    M: 'изменён',
    A: 'добавлен',
    D: 'удалён',
    R: 'переименован',
    C: 'скопирован',
    U: 'конфликт',
    '??': 'новый',
}

const statusLabelsByLanguage = {
    M: { ru: 'Изменён', kk: 'Өзгертілді', en: 'Modified' },
    A: { ru: 'Добавлен', kk: 'Қосылды', en: 'Added' },
    D: { ru: 'Удалён', kk: 'Жойылды', en: 'Deleted' },
    R: { ru: 'Переименован', kk: 'Атауы өзгертілді', en: 'Renamed' },
    C: { ru: 'Скопирован', kk: 'Көшірілді', en: 'Copied' },
    U: { ru: 'Конфликт', kk: 'Қайшылық', en: 'Conflict' },
    '??': { ru: 'Новый', kk: 'Жаңа', en: 'New' },
}

function statusLabel(status, language) {
    return statusLabelsByLanguage[status]?.[language] || statusLabels[status] || status
}

function formatDate(value, language = 'ru') {
    if (!value) return '—'
    try {
        const locale = language === 'en' ? 'en-US' : language === 'kk' ? 'kk-KZ' : 'ru-RU'
        return new Intl.DateTimeFormat(locale, {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(value))
    } catch {
        return value
    }
}

function diffTitle(mode, commit) {
    if (!commit) return 'Изменения'
    return mode === 'compare'
        ? `Сравнение ${commit.short_hash} с текущей версией`
        : `Изменения коммита ${commit.short_hash}`
}

export default function GitVersions() {
    const { user, logout } = useAuth()
    const { language } = useLanguage()
    const l = (ru, kk, en) => language === 'kk' ? kk : language === 'en' ? en : ru
    const navigate = useNavigate()
    const [overview, setOverview] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [selectedCommit, setSelectedCommit] = useState(null)
    const [diffMode, setDiffMode] = useState('commit')
    const [diff, setDiff] = useState('')
    const [diffTruncated, setDiffTruncated] = useState(false)
    const [diffLoading, setDiffLoading] = useState(false)
    const [branchName, setBranchName] = useState('')
    const [branchMessage, setBranchMessage] = useState('')

    const loadOverview = () => {
        setLoading(true)
        setError('')
        axios.get('/api/git/overview')
            .then(response => setOverview(response.data))
            .catch(err => setError(formatApiError(err, l('Не удалось загрузить Git-статус', 'Git күйін жүктеу мүмкін болмады', 'Could not load Git status'))))
            .finally(() => setLoading(false))
    }

    useEffect(() => {
        if (!user) {
            navigate('/login')
            return
        }
        loadOverview()
    }, [user, navigate])

    const loadDiff = async (commit, mode) => {
        setSelectedCommit(commit)
        setDiffMode(mode)
        setDiffLoading(true)
        setDiff('')
        setDiffTruncated(false)
        setBranchMessage('')
        try {
            const endpoint = mode === 'compare'
                ? `/api/git/commits/${commit.hash}/compare-current`
                : `/api/git/commits/${commit.hash}/diff`
            const response = await axios.get(endpoint)
            setDiff(response.data.diff || 'Изменений нет.')
            setDiffTruncated(Boolean(response.data.truncated))
        } catch (err) {
            setDiff(formatApiError(err, l('Не удалось получить изменения', 'Өзгерістерді алу мүмкін болмады', 'Could not load diff')))
        } finally {
            setDiffLoading(false)
        }
    }

    const createBranch = async (commit) => {
        const name = branchName.trim()
        if (!name) {
            setBranchMessage('Введите имя ветки.')
            return
        }
        try {
            const response = await axios.post(`/api/git/commits/${commit.hash}/branches`, { branch_name: name })
            setBranchMessage(`Ветка создана: ${response.data.branch}`)
            setBranchName('')
            loadOverview()
        } catch (err) {
            setBranchMessage(formatApiError(err, l('Не удалось создать ветку', 'Бұтақты жасау мүмкін болмады', 'Could not create branch')))
        }
    }

    if (loading) return <LoadingSpinner />

    return (
        <div className="app-shell">
            <header className="app-header">
                <div className="container">
                    <Link to="/" className="app-brand"><span className="app-brand-mark">CK</span><span>Curriculum KAG</span></Link>
                    <div className="app-nav">
                        <LanguageSelector />
                        <Link to="/" className="app-nav-link">Проекты</Link>
                        <Link to="/repository" className="app-nav-link">Репозиторий</Link>
                        <span className="user-chip">{user?.full_name || user?.email}</span>
                        <button onClick={() => { logout(); navigate('/login') }} className="btn btn-secondary">Выйти</button>
                    </div>
                </div>
            </header>

            <main className="container">
                <section className="page-hero">
                    <div>
                        <div className="eyebrow">Git / контроль версий</div>
                        <h1 className="page-title">Версии проекта</h1>
                        <p className="page-subtitle">Здесь можно посмотреть состояние репозитория, историю коммитов и создать ветку от выбранной версии.</p>
                    </div>
                    <button className="btn btn-secondary" onClick={loadOverview}>Обновить</button>
                </section>

                {error ? <div className="card" style={{ borderColor: '#ffd0d0', color: '#b00020' }}>{error}</div> : null}

                {overview ? (
                    <>
                        <section className="stat-grid">
                            <div className="stat-card"><span className="stat-dot" /><div className="stat-value">{overview.branch}</div><div className="stat-label">Текущая ветка</div></div>
                            <div className="stat-card"><span className="stat-dot" style={{ background: overview.clean ? '#248a3d' : '#ff9f0a', boxShadow: overview.clean ? '0 0 0 6px #e8f7ed' : '0 0 0 6px #fff6e5' }} /><div className="stat-value">{overview.clean ? 'Чисто' : 'Изменения'}</div><div className="stat-label">{overview.status_text}</div></div>
                            <div className="stat-card"><span className="stat-dot" style={{ background: '#5856d6', boxShadow: '0 0 0 6px #eeeeff' }} /><div className="stat-value">{overview.changed_files.length}</div><div className="stat-label">Изменённых файлов</div></div>
                        </section>

                        <section className="card">
                            <div className="section-head"><h2>Изменённые файлы</h2><span style={{ color: '#6e6e73', fontSize: 13 }}>{overview.changed_files.length}</span></div>
                            {overview.changed_files.length === 0 ? (
                                <p style={{ color: '#6e6e73' }}>Рабочая копия чистая.</p>
                            ) : (
                                <div className="table-wrap"><table className="table">
                                    <thead><tr><th>Статус</th><th>Файл</th></tr></thead>
                                    <tbody>{overview.changed_files.map(file => (
                                        <tr key={`${file.status}-${file.path}`}>
                                            <td><span className="badge">{statusLabel(file.status, language)}</span></td>
                                            <td><code>{file.path}</code></td>
                                        </tr>
                                    ))}</tbody>
                                </table></div>
                            )}
                        </section>

                        <section className="card">
                            <div className="section-head"><h2>Последние 20 коммитов</h2><span style={{ color: '#6e6e73', fontSize: 13 }}>{overview.commits.length}</span></div>
                            <div className="table-wrap"><table className="table">
                                <thead><tr><th>{l('Хэш', 'Хэш', 'Hash')}</th><th>{l('Сообщение', 'Хабарлама', 'Message')}</th><th>{l('Автор', 'Автор', 'Author')}</th><th>{l('Дата', 'Күні', 'Date')}</th><th>{l('Действия', 'Әрекеттер', 'Actions')}</th></tr></thead>
                                <tbody>{overview.commits.map(commit => (
                                    <tr key={commit.hash}>
                                        <td><code title={commit.hash}>{commit.short_hash}</code></td>
                                        <td>{commit.message}</td>
                                        <td>{commit.author}</td>
                                        <td>{formatDate(commit.date, language)}</td>
                                        <td>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                                <button className="btn btn-secondary" onClick={() => loadDiff(commit, 'commit')}>Изменения</button>
                                                <button className="btn btn-secondary" onClick={() => loadDiff(commit, 'compare')}>Сравнить</button>
                                                <button className="btn btn-primary" onClick={() => {
                                                    setSelectedCommit(commit)
                                                    setDiffMode('branch')
                                                    setDiff('')
                                                    setBranchName(`restore/${commit.short_hash}`)
                                                    setBranchMessage('')
                                                }}>Новая ветка</button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}</tbody>
                            </table></div>
                        </section>

                        {selectedCommit ? (
                            <section className="card">
                                <div className="section-head"><h2>{diffTitle(diffMode, selectedCommit)}</h2><code>{selectedCommit.hash}</code></div>
                                {diffMode === 'branch' ? (
                                    <div style={{ display: 'grid', gap: 12, maxWidth: 620 }}>
                                        <label>
                                            <span style={{ display: 'block', marginBottom: 6, color: '#6e6e73' }}>Имя новой ветки</span>
                                            <input className="form-input" value={branchName} onChange={event => setBranchName(event.target.value)} placeholder="feature/my-branch" />
                                        </label>
                                        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                                            <button className="btn btn-primary" onClick={() => createBranch(selectedCommit)}>Создать ветку</button>
                                            <span style={{ color: branchMessage.startsWith('Ветка создана') ? '#248a3d' : '#b00020' }}>{branchMessage}</span>
                                        </div>
                                        <p style={{ color: '#6e6e73', margin: 0 }}>Ветка создаётся от выбранного коммита, но текущая рабочая ветка не переключается.</p>
                                    </div>
                                ) : diffLoading ? (
                                    <LoadingSpinner />
                                ) : (
                                    <>
                                        {diffTruncated ? <p style={{ color: '#9a5b00' }}>Diff большой, поэтому показан безопасный фрагмент.</p> : null}
                                        <pre style={{ whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 620, background: '#111827', color: '#e5e7eb', borderRadius: 16, padding: 18, fontSize: 12 }}>{diff}</pre>
                                    </>
                                )}
                            </section>
                        ) : null}
                    </>
                ) : null}
            </main>
        </div>
    )
}
