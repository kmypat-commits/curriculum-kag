import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

class AppErrorBoundary extends React.Component {
    state = { error: null }
    static getDerivedStateFromError(error) { return { error } }
    render() {
        if (this.state.error) {
            return <div style={{ padding: 32, fontFamily: 'system-ui', color: '#b42318' }}>
                <h2>Не удалось отобразить страницу</h2>
                <p>{this.state.error?.message || String(this.state.error)}</p>
                <button onClick={() => window.location.reload()}>Повторить загрузку</button>
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
