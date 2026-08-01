import { createContext, useContext, useState } from 'react';
import { translations } from '../translations';
import generatedKk from '../translations_kk_generated.json';

const LanguageContext = createContext(null);

export const LanguageProvider = ({ children }) => {
    const [language, setLanguage] = useState(localStorage.getItem('language') || 'ru');
    const normalizedLanguage = language === 'kz' ? 'kk' : language;
    const clean = {
        ru: { domains: 'Предметные области', domain: 'Предметная область', education_area: 'Область образования', cycle_component: 'Компонент цикла', course_domain: 'Предметная область' },
        kk: { domains: 'Пәндік салалар', domain: 'Пәндік сала', education_area: 'Білім беру саласы', cycle_component: 'Цикл компоненті', course_domain: 'Пәндік сала' },
        en: { domains: 'Subject areas', domain: 'Subject area', education_area: 'Education area', cycle_component: 'Cycle component', course_domain: 'Subject area' },
    };
    const t = (key) => {
        if (clean[normalizedLanguage]?.[key]) return clean[normalizedLanguage][key];
        if (normalizedLanguage === 'kk') return translations.kk?.[key] || generatedKk[key] || translations.ru[key] || key;
        return translations[normalizedLanguage]?.[key] || translations.ru[key] || key;
    };
    const localize = (value) => {
        if (value == null) return '';
        if (typeof value === 'object') return value[normalizedLanguage] || value[normalizedLanguage === 'kk' ? 'kz' : language] || value.ru || value.en || Object.values(value)[0] || '';
        const text = String(value);
        return translations[normalizedLanguage]?.[text] || translations.ru?.[text] || text;
    };
    const localizeCycle = (value) => {
        const key = String(value || '').trim().toUpperCase();
        const labels = {
            ru: { БД: 'БД — базовые дисциплины', ПД: 'ПД — профильные дисциплины', ООД: 'ООД — общеобразовательные дисциплины', КВ: 'КВ — компонент по выбору', ВК: 'ВК — вузовский компонент' },
            kk: { БД: 'БД — базалық пәндер', ПД: 'ПД — бейіндік пәндер', ООД: 'ООД — жалпы білім беретін пәндер', КВ: 'КВ — таңдау компоненті', ВК: 'ВК — жоғары оқу орны компоненті' },
            en: { БД: 'BD — basic disciplines', BD: 'BD — basic disciplines', ПД: 'PD — profile disciplines', PD: 'PD — profile disciplines', ООД: 'GED — general education disciplines', GED: 'GED — general education disciplines', КВ: 'EC — elective component', EC: 'EC — elective component', ВК: 'UC — university component', UC: 'UC — university component' },
        };
        return labels[normalizedLanguage]?.[key] || localize(value);
    };
    const changeLanguage = (lang) => { setLanguage(lang); localStorage.setItem('language', lang); };
    return <LanguageContext.Provider value={{ language, t, localize, localizeCycle, changeLanguage }}>{children}</LanguageContext.Provider>;
};

export const useLanguage = () => {
    const context = useContext(LanguageContext);
    if (!context) throw new Error('useLanguage must be used within a LanguageProvider');
    return context;
};
