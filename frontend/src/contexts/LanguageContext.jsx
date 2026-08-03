import { createContext, useContext, useState } from 'react';
import { translations } from '../translations';
import generatedKk from '../translations_kk_generated.json';

const LanguageContext = createContext(null);

export const LanguageProvider = ({ children }) => {
    const [language, setLanguage] = useState(localStorage.getItem('language') || 'ru');
    const normalizedLanguage = ({
        ru: 'ru', rus: 'ru', russian: 'ru',
        kk: 'kk', kz: 'kk', kaz: 'kk', kazakh: 'kk',
        en: 'en', eng: 'en', english: 'en',
    })[String(language || '').trim().toLowerCase()] || 'ru';
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
    const localizeDomain = (value) => {
        const text = String(value || '').trim();
        const key = text.toLowerCase();
        const cleanDomains = {
            'информационно-коммуникационные технологии': { ru: 'Информационно-коммуникационные технологии', kk: 'Ақпараттық-коммуникациялық технологиялар', en: 'Information and Communication Technologies' },
            'information and communication technologies': { ru: 'Информационно-коммуникационные технологии', kk: 'Ақпараттық-коммуникациялық технологиялар', en: 'Information and Communication Technologies' },
            'стандартизация, сертификация и метрология (по отраслям)': { ru: 'Стандартизация, сертификация и метрология (по отраслям)', kk: 'Стандарттау, сертификаттау және метрология (салалар бойынша)', en: 'Standardization, Certification and Metrology (by industry)' },
            'standardization, certification and metrology (by industry)': { ru: 'Стандартизация, сертификация и метрология (по отраслям)', kk: 'Стандарттау, сертификаттау және метрология (салалар бойынша)', en: 'Standardization, Certification and Metrology (by industry)' },
        };
        if (cleanDomains[key]?.[normalizedLanguage]) return cleanDomains[key][normalizedLanguage];
        const labels = {
            'информационно-коммуникационные технологии': { ru: 'Информационно-коммуникационные технологии', kk: 'Ақпараттық-коммуникациялық технологиялар', en: 'Information and Communication Technologies' },
            'information and communication technologies': { ru: 'Информационно-коммуникационные технологии', kk: 'Ақпараттық-коммуникациялық технологиялар', en: 'Information and Communication Technologies' },
            'информационная безопасность': { ru: 'Информационная безопасность', kk: 'Ақпараттық қауіпсіздік', en: 'Information Security' },
            'information security': { ru: 'Информационная безопасность', kk: 'Ақпараттық қауіпсіздік', en: 'Information Security' },
            'сельское хозяйство и биоресурсы': { ru: 'Сельское хозяйство и биоресурсы', kk: 'Ауыл шаруашылығы және биоресурстар', en: 'Agriculture and Bioresources' },
            'agriculture and bioresources': { ru: 'Сельское хозяйство и биоресурсы', kk: 'Ауыл шаруашылығы және биоресурстар', en: 'Agriculture and Bioresources' },
            'инженерные, обрабатывающие и строительные отрасли': { ru: 'Инженерные, обрабатывающие и строительные отрасли', kk: 'Инженерлік, өңдеу және құрылыс салалары', en: 'Engineering and Manufacturing' },
            'engineering and manufacturing': { ru: 'Инженерные, обрабатывающие и строительные отрасли', kk: 'Инженерлік, өңдеу және құрылыс салалары', en: 'Engineering and Manufacturing' },
            'здравоохранение': { ru: 'Здравоохранение', kk: 'Денсаулық сақтау', en: 'Healthcare' },
            'healthcare': { ru: 'Здравоохранение', kk: 'Денсаулық сақтау', en: 'Healthcare' },
        };
        return labels[key]?.[normalizedLanguage] || text;
    };
    const localizeCycle = (value) => {
        const key = String(value || '').trim().toUpperCase();
        const cleanCycle = { '\u0411\u0414': 'BD', 'BD': 'BD', '\u041f\u0414': 'PD', 'PD': 'PD', '\u041e\u041e\u0414': 'GED', 'OOD': 'GED', '\u041a\u0412': 'EC', 'EC': 'EC', '\u0412\u041a': 'UC', 'UC': 'UC' };
        const cleanCode = cleanCycle[key];
        if (cleanCode) {
            const cleanLabels = {
                ru: { BD: '\u0411\u0414 — \u0431\u0430\u0437\u043e\u0432\u044b\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b', PD: '\u041f\u0414 — \u043f\u0440\u043e\u0444\u0438\u043b\u044c\u043d\u044b\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b', GED: '\u041e\u041e\u0414 — \u043e\u0431\u0449\u0435\u043e\u0431\u0440\u0430\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u0434\u0438\u0441\u0446\u0438\u043f\u043b\u0438\u043d\u044b', EC: '\u041a\u0412 — \u043a\u043e\u043c\u043f\u043e\u043d\u0435\u043d\u0442 \u043f\u043e \u0432\u044b\u0431\u043e\u0440\u0443', UC: '\u0412\u041a — \u0432\u0443\u0437\u043e\u0432\u0441\u043a\u043e\u0439 \u043a\u043e\u043c\u043f\u043e\u043d\u0435\u043d\u0442' },
                kk: { BD: '\u0411\u0414 — \u0431\u0430\u0437\u0430\u043b\u044b\u049b \u043f\u04d9\u043d\u0434\u0435\u0440', PD: '\u041f\u0414 — \u0431\u0435\u0439\u0456\u043d\u0434\u0456\u043a \u043f\u04d9\u043d\u0434\u0435\u0440', GED: '\u0416\u0411\u0411 — \u0436\u0430\u043b\u043f\u044b \u0431\u0456\u043b\u0456\u043c \u0431\u0435\u0440\u0435\u0442\u0456\u043d \u043f\u04d9\u043d\u0434\u0435\u0440', EC: '\u0422\u041a — \u0442\u0430\u04a3\u0434\u0430\u0443 \u043a\u043e\u043c\u043f\u043e\u043d\u0435\u043d\u0442\u0456', UC: '\u0416\u041a — \u0436\u043e\u0493\u0430\u0440\u044b \u043e\u049b\u0443 \u043e\u0440\u043d\u044b \u043a\u043e\u043c\u043f\u043e\u043d\u0435\u043d\u0442\u0456' },
                en: { BD: 'BD — basic disciplines', PD: 'PD — profile disciplines', GED: 'GED — general education disciplines', EC: 'EC — elective component', UC: 'UC — university component' },
            };
            return cleanLabels[normalizedLanguage]?.[cleanCode] || cleanCode;
        }
        const aliases = {
            'БД': 'BD', BD: 'BD', 'БАЗОВЫЕ ДИСЦИПЛИНЫ': 'BD', 'BASIC DISCIPLINES': 'BD',
            'ПД': 'PD', PD: 'PD', 'ПРОФИЛЬНЫЕ ДИСЦИПЛИНЫ': 'PD', 'PROFILE DISCIPLINES': 'PD',
            'ООД': 'GED', OOD: 'GED', 'ОБЩЕОБРАЗОВАТЕЛЬНЫЕ ДИСЦИПЛИНЫ': 'GED', 'GENERAL EDUCATION DISCIPLINES': 'GED',
            'КВ': 'EC', EC: 'EC', 'КОМПОНЕНТ ПО ВЫБОРУ': 'EC', 'ELECTIVE COMPONENT': 'EC',
            'ВК': 'UC', UC: 'UC', 'ВУЗОВСКИЙ КОМПОНЕНТ': 'UC', 'UNIVERSITY COMPONENT': 'UC',
        };
        const code = aliases[key];
        if (code) {
            const labels = {
                ru: { BD: 'БД — базовые дисциплины', PD: 'ПД — профильные дисциплины', GED: 'ООД — общеобразовательные дисциплины', EC: 'КВ — компонент по выбору', UC: 'ВК — вузовский компонент' },
                kk: { BD: 'БД — базалық пәндер', PD: 'ПД — бейіндік пәндер', GED: 'ЖББ — жалпы білім беретін пәндер', EC: 'ТК — таңдау компоненті', UC: 'ЖК — жоғары оқу орны компоненті' },
                en: { BD: 'BD — basic disciplines', PD: 'PD — profile disciplines', GED: 'GED — general education disciplines', EC: 'EC — elective component', UC: 'UC — university component' },
            };
            return labels[normalizedLanguage]?.[code] || value || '';
        }
        const labels = {
            ru: { БД: 'БД — базовые дисциплины', BD: 'БД — базовые дисциплины', БАЗОВЫЕ: 'БД — базовые дисциплины', ПД: 'ПД — профильные дисциплины', PD: 'ПД — профильные дисциплины', ООД: 'ООД — общеобразовательные дисциплины', OOD: 'ООД — общеобразовательные дисциплины', КВ: 'КВ — компонент по выбору', 'КОМПОНЕНТ ПО ВЫБОРУ': 'КВ — компонент по выбору', ВК: 'ВК — вузовский компонент', 'ВУЗОВСКИЙ КОМПОНЕНТ': 'ВК — вузовский компонент' },
            kk: { БД: 'БД — базалық пәндер', BD: 'БД — базалық пәндер', ПД: 'ПД — бейіндік пәндер', PD: 'ПД — бейіндік пәндер', ООД: 'ООД — жалпы білім беретін пәндер', OOD: 'ООД — жалпы білім беретін пәндер', КВ: 'КВ — таңдау компоненті', ВК: 'ВК — жоғары оқу орны компоненті' },
            en: { БД: 'BD — basic disciplines', BD: 'BD — basic disciplines', ПД: 'PD — profile disciplines', PD: 'PD — profile disciplines', ООД: 'GED — general education disciplines', OOD: 'GED — general education disciplines', КВ: 'EC — elective component', EC: 'EC — elective component', ВК: 'UC — university component', UC: 'UC — university component', 'ELECTIVE COMPONENT': 'EC — elective component', 'UNIVERSITY COMPONENT': 'UC — university component' },
        };
        return labels[normalizedLanguage]?.[key] || localize(value);
    };
    const changeLanguage = (lang) => { setLanguage(lang); localStorage.setItem('language', lang); };
    return <LanguageContext.Provider value={{ language: normalizedLanguage, t, localize, localizeDomain, localizeCycle, changeLanguage }}>{children}</LanguageContext.Provider>;
};

export const useLanguage = () => {
    const context = useContext(LanguageContext);
    if (!context) throw new Error('useLanguage must be used within a LanguageProvider');
    return context;
};
