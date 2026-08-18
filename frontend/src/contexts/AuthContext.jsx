import { createContext, useContext, useState, useEffect } from 'react'
import axios from 'axios'
import { useLanguage } from './LanguageContext'

const AuthContext = createContext(null)

export const AuthProvider = ({ children }) => {
    const { t } = useLanguage()
    const [user, setUser] = useState(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        // Check if user is logged in
        // Keep the access token for the current browser session only.  Migrate
        // an older localStorage token once, then remove the persistent copy.
        const legacyToken = localStorage.getItem('token')
        const token = sessionStorage.getItem('token') || legacyToken
        if (legacyToken && !sessionStorage.getItem('token')) sessionStorage.setItem('token', legacyToken)
        if (legacyToken) localStorage.removeItem('token')
        if (token) {
            axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
            fetchCurrentUser()
        } else {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        const interceptor = axios.interceptors.response.use(
            response => response,
            error => {
                const status = error.response?.status
                const url = String(error.config?.url || '')
                if (status === 401 && !url.includes('/auth/login')) {
                    sessionStorage.removeItem('token')
                    delete axios.defaults.headers.common['Authorization']
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
            sessionStorage.removeItem('token')
            delete axios.defaults.headers.common['Authorization']
        } finally {
            setLoading(false)
        }
    }

    const login = async (email, password) => {
        const params = new URLSearchParams()
        params.append('username', email)
        params.append('password', password)

        const response = await axios.post('/api/auth/login', params)
        const { access_token } = response.data

        sessionStorage.setItem('token', access_token)
        axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`

        await fetchCurrentUser()
    }

    const logout = () => {
        sessionStorage.removeItem('token')
        delete axios.defaults.headers.common['Authorization']
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
