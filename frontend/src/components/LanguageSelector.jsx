import { useLanguage } from '../contexts/LanguageContext'

export default function LanguageSelector() {
    const { language, changeLanguage } = useLanguage()
    const languages = [
        { code: 'ru', label: 'Русский' },
        { code: 'kk', label: 'Қазақша' },
        { code: 'en', label: 'English' }
    ]

    return (
        <div className="language-selector" aria-label="Language">
            {languages.map(lang => (
                <button
                    key={lang.code}
                    onClick={() => changeLanguage(lang.code)}
                    className={`language-option ${language === lang.code ? 'is-selected' : ''}`}
                    aria-pressed={language === lang.code}
                    aria-label={lang.label}
                >
                    <span className="language-code" aria-hidden="true">{lang.code.toUpperCase()}</span>
                    <span className="lang-label">{lang.label}</span>
                </button>
            ))}
        </div>
    )
}
