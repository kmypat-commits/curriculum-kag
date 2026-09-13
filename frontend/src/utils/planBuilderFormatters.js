export function localizedCourseField(translations, fallback = '', localize) {
    const translated = translations && typeof translations === 'object'
        ? localize(translations)
        : translations
    return String(translated || fallback || '').trim()
}

export function epvoSyncMessage(sync, translate) {
    if (!sync) return null
    return translate('epvo_sync_summary')
        .replace('{created}', sync.created ?? 0)
        .replace('{linked}', sync.linked ?? 0)
        .replace('{scope}', sync.group_code || sync.direction_code || sync.scope || translate('all_domains'))
}

export function localizedCourse(course = {}, localize) {
    const translations = course.title_translations || (
        course.title_ru || course.title_kk || course.title_en
            ? { ru: course.title_ru, kk: course.title_kk || course.title_kz, en: course.title_en }
            : null
    )
    return localizedCourseField(translations, course.title, localize)
}

export function componentLabel(value = '', { localizeCycle, t }) {
    const cycle = localizeCycle(value)
    if (cycle !== String(value || '').trim()) return cycle
    const normalized = String(value).trim().toLowerCase()
    if (['bd', 'бд', 'basic', 'basic disciplines', 'базовые дисциплины'].includes(normalized)) return localizeCycle('БД')
    if (['pd', 'пд', 'profile', 'profile disciplines', 'профильные дисциплины'].includes(normalized)) return localizeCycle('ПД')
    if (['ged', 'ood', 'оод', 'general', 'general education'].includes(normalized)) return localizeCycle('ООД')
    if (['elective', 'elective component', 'компонент по выбору'].includes(normalized)) return t('elective')
    if (['university', 'university component', 'вузовский компонент'].includes(normalized)) return t('university')
    return t('mandatory')
}

export function errorMessage(error, language, t) {
    const detail = error?.response?.data?.detail
    if (Array.isArray(detail)) {
        return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join('; ')
    }
    if (detail && typeof detail === 'object') {
        return detail.message_by_language?.[language] || detail.message || detail.error || JSON.stringify(detail)
    }
    return detail || error?.message || t('unknown_error')
}
