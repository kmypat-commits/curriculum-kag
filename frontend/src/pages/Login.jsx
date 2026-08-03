import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLanguage } from '../contexts/LanguageContext'
import { formatApiError } from '../utils/errors'
import LanguageSelector from '../components/LanguageSelector'

export default function Login() {
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const { login } = useAuth()
    const { t } = useLanguage()
    const navigate = useNavigate()

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')

        try {
            await login(email, password)
            const returnPath = sessionStorage.getItem('postLoginPath') || '/'
            sessionStorage.removeItem('postLoginPath')
            navigate(returnPath)
        } catch (err) {
            const message = formatApiError(err, 'Network or server error');
            setError(message === 'Incorrect email or password' ? t('error') : message);
            console.error('Login error:', err);
        }
    }

    return (
        <div style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
        }}>
            <div className="card" style={{ maxWidth: '400px', width: '100%' }}>
                <h1 style={{ marginBottom: '20px', textAlign: 'center' }}>
                    Curriculum-KAG Generator
                </h1>
                <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '20px' }}>
                    <LanguageSelector />
                </div>
                <form onSubmit={handleSubmit}>
                    <div className="form-group">
                        <label className="form-label">{t('login')}</label>
                        <input
                            type="email"
                            className="form-control"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('password')}</label>
                        <input
                            type="password"
                            className="form-control"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>
                    {error && (
                        <div style={{ color: 'red', marginBottom: '10px' }}>{error}</div>
                    )}
                    <button type="submit" className="btn btn-primary" style={{ width: '100%' }}>
                        {t('login')}
                    </button>
                </form>
            </div>
        </div>
    )
}
