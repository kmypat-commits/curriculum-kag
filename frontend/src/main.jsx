import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

class AppErrorBoundary extends React.Component {
    state = { error: null }
    static getDerivedStateFromError(error) { return { error } }
    render() {
        if (this.state.error) {
            const language = String(localStorage.getItem('language') || 'ru').toLowerCase()
            const copy = {
                ru: ['Не удалось отобразить страницу', 'Повторить загрузку'],
                kk: ['Бетті көрсету мүмкін болмады', 'Жүктеуді қайталау'],
                en: ['Could not render the page', 'Retry loading'],
            }[language] || ['Не удалось отобразить страницу', 'Повторить загрузку']
            return <div style={{ padding: 32, fontFamily: 'system-ui', color: '#b42318' }}>
                <h2>{copy[0]}</h2>
                <p>{this.state.error?.message || String(this.state.error)}</p>
                <button onClick={() => window.location.reload()}>{copy[1]}</button>
            </div>
        }
        return this.props.children
    }
}

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <AppErrorBoundary><App /></AppErrorBoundary>
    </React.StrictMode>,
)
