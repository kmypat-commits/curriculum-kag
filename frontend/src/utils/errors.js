export function formatApiError(error, fallback = 'Неизвестная ошибка') {
    const detail = error?.response?.data?.detail ?? error?.detail
    if (Array.isArray(detail)) {
        return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join('; ')
    }
    if (detail && typeof detail === 'object') {
        return detail.message || detail.error || JSON.stringify(detail)
    }
    return detail || error?.message || fallback
}
