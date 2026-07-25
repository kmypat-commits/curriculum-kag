import { createContext, useContext, useState, useEffect } from 'react';
import { translations } from '../translations';
import generatedKk from '../translations_kk_generated.json';

const LanguageContext = createContext(null);

export const LanguageProvider = ({ children }) => {
    const [language, setLanguage] = useState(localStorage.getItem('language') || 'ru');

    const t = (key) => {
        if (language === 'kk') return translations.kk?.[key] || generatedKk[key] || translations.ru[key] || key;
        return translations[language]?.[key] || translations.ru[key] || key;
    };

    const localize = (value) => {
        if (value == null) return '';
        if (typeof value === 'object') {
            return value[language] || value[language === 'kk' ? 'kz' : language] || value.ru || value.en || Object.values(value)[0] || '';
        }
        const text = String(value);
        return translations[language]?.[text] || translations.ru?.[text] || text;
    };

    const changeLanguage = (lang) => {
        setLanguage(lang);
        localStorage.setItem('language', lang);
    };

    return (
        <LanguageContext.Provider value={{ language, t, localize, changeLanguage }}>
            {children}
        </LanguageContext.Provider>
    );
};

export const useLanguage = () => {
    const context = useContext(LanguageContext);
    if (!context) {
        throw new Error('useLanguage must be used within a LanguageProvider');
    }
    return context;
};
