import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const NotificationContext = createContext(null)

export function NotificationProvider({ children }) {
    const [items, setItems] = useState([])
    const notify = useCallback((message, type = 'error') => {
        const id = `${Date.now()}-${Math.random()}`
        setItems(current => [...current, { id, message, type }])
        window.setTimeout(() => setItems(current => current.filter(item => item.id !== id)), 6000)
    }, [])
    const dismiss = id => setItems(current => current.filter(item => item.id !== id))
    return <NotificationContext.Provider value={{ notify, dismiss }}>
        {children}
        <div className="app-toast-stack" role="status" aria-live="polite">
            {items.map(item => <div key={item.id} className={`app-toast app-toast-${item.type}`}>
                <span>{item.message}</span><button type="button" onClick={() => dismiss(item.id)} aria-label="Закрыть">×</button>
            </div>)}
        </div>
    </NotificationContext.Provider>
}

export function useNotifications() {
    const value = useContext(NotificationContext)
    if (!value) throw new Error('useNotifications must be used inside NotificationProvider')
    return value
}
