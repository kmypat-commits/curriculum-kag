import { useLanguage } from '../contexts/LanguageContext'

export default function LanguageSelector() {
    const { language, changeLanguage } = useLanguage()
    const languages = [
        { code: 'ru', label: 'Русский', flag: '🇷🇺' },
        { code: 'kk', label: 'Қазақша', flag: '🇰🇿' },
        { code: 'en', label: 'English', flag: '🇬🇧' }
    ]

    return (
        <div style={{ display: 'flex', gap: '5px' }}>
            {languages.map(lang => (
                <button
                    key={lang.code}
                    onClick={() => changeLanguage(lang.code)}
                    style={{
                        padding: '4px 8px', fontSize: '14px',
                        background: language === lang.code ? '#366092' : 'white',
                        color: language === lang.code ? 'white' : '#666',
                        border: '1px solid #e0e0e0', borderRadius: '4px', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: '5px', transition: 'all 0.2s'
                    }}
                >
                    <span>{lang.flag}</span>
                    <span className="lang-label">{lang.label}</span>
                </button>
            ))}
        </div>
    )
}
