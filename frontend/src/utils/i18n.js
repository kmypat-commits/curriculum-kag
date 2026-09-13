export const localizedCopy = (language, ru, kk, en) => {
    if (language === 'kk') return kk
    if (language === 'en') return en
    return ru
}
