import { createContext, useContext, useState, useEffect } from 'react'
import axios from 'axios'
import { useLanguage } from './LanguageContext'

const AuthContext = createContext(null)

axios.defaults.withCredentials = true

export const AuthProvider = ({ children }) => {
    const { t } = useLanguage()
    const [user, setUser] = useState(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        // Browser authentication is kept in an HttpOnly cookie. Clear legacy
        // JavaScript-readable tokens once without copying them to a new store.
        localStorage.removeItem('token')
        sessionStorage.removeItem('token')
        fetchCurrentUser()
    }, [])

    useEffect(() => {
        const interceptor = axios.interceptors.response.use(
            response => response,
            error => {
                const status = error.response?.status
                const url = String(error.config?.url || '')
                if (status === 401 && !url.includes('/auth/login')) {
                    setUser(null)
                    error.authExpired = true
                    if (window.location.pathname !== '/login') {
                        sessionStorage.setItem('postLoginPath', `${window.location.pathname}${window.location.search}`)
                        window.location.assign('/login?reason=session_expired')
                    }
                }
                return Promise.reject(error)
            }
        )
        return () => axios.interceptors.response.eject(interceptor)
    }, [])

    const fetchCurrentUser = async () => {
        try {
            const response = await axios.get('/api/auth/me')
            setUser(response.data)
        } catch (error) {
            setUser(null)
        } finally {
            setLoading(false)
        }
    }

    const login = async (email, password) => {
        const params = new URLSearchParams()
        params.append('username', email)
        params.append('password', password)

        const response = await axios.post('/api/auth/login', params)
        await fetchCurrentUser()
    }

    const logout = async () => {
        try {
            await axios.post('/api/auth/logout')
        } catch (_) {
            // Local state must still be cleared if the server is unavailable.
        }
        setUser(null)
    }

    // Do not mount data-fetching pages until a persisted token has been
    // restored and validated. Otherwise direct links can race the auth check
    // and issue their first API request without the Authorization header.
    if (loading) {
        return <div style={{ padding: '40px', textAlign: 'center' }}>{t('loading')}</div>
    }

    return (
        <AuthContext.Provider value={{ user, login, logout, loading }}>
            {children}
        </AuthContext.Provider>
    )
}

export const useAuth = () => {
    const context = useContext(AuthContext)
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider')
    }
    return context
}
