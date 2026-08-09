const QUALITY_EVIDENCE_PATTERNS = {
    kk: [
        [/^Project feedback: (\d+); EPVO expert-supported links: (\d+); promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Кері байланыс: $1; CEER сарапшылары растаған байланыстар: $2; расталған bridge оқиғалары: $3; жоспардағы bridge модульдері: $4.'],
        [/^(\d+)\/(\d+) courses have direct EPVO scope, programme-LO evidence, domain evidence, or RK mandatory status; domain quota violations: (\d+)\.$/, '$1/$2 пәннің тікелей CEER бағыты, бағдарлама LO дәлелі, пәндік сала дәлелі немесе ҚР міндетті мәртебесі бар; пәндік квота бұзушылықтары: $3.'],
        [/^(\d+)\/(\d+) learning outcomes meet the coverage threshold\.$/, '$1/$2 оқу нәтижесі қамту шегіне жетті.'],
        [/^Hard violations: (\d+)\.$/, 'Қатаң бұзушылықтар: $1.'],
        [/^(\d+)\/(\d+) repository courses match the project domains\.$/, '$1/$2 пән репозиторийі жоба бағыттарына сәйкес келеді.'],
        [/^(\d+)\/(\d+) courses are supported by the selected EPVO scope, programme LO evidence, or RK mandatory requirements\.$/, '$1/$2 пән CEER бағытымен, ОН байланысымен немесе ҚР міндетті талаптарымен расталды.'],
        [/^Interdisciplinary\/bridge units: (\d+)\.$/, 'Пәнаралық/bridge модульдер: $1.'],
        [/^Not applicable: this is a standard single-direction programme\.$/, 'Қолданылмайды: бұл стандартты бір бағытты бағдарлама.'],
        [/^(\d+)\/(\d+) learning units include assessment methods\.$/, '$1/$2 оқу бірлігі бағалау әдістерін қамтиды.'],
        [/^Promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Жаңартылған bridge оқиғалары: $1; жоспардағы bridge модульдер: $2.'],
        [/^Expert feedback: (\d+); promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Сарапшылық кері байланыс: $1; жаңартылған bridge оқиғалары: $2; жоспардағы bridge модульдер: $3.'],
    ],
    ru: [
        [/^Project feedback: (\d+); EPVO expert-supported links: (\d+); promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Обратная связь по проекту: $1; связей, подтверждённых экспертами CEER: $2; подтверждённых bridge-событий: $3; bridge-модулей в плане: $4.'],
        [/^(\d+)\/(\d+) courses have direct EPVO scope, programme-LO evidence, domain evidence, or RK mandatory status; domain quota violations: (\d+)\.$/, '$1/$2 дисциплин имеют подтверждение областью CEER, связью с РО программы, предметной областью или статус обязательной дисциплины РК; нарушений квот областей: $3.'],
        [/^(\d+)\/(\d+) learning outcomes meet the coverage threshold\.$/, '$1/$2 результатов обучения достигли порога покрытия.'],
        [/^Hard violations: (\d+)\.$/, 'Жёстких нарушений: $1.'],
        [/^(\d+)\/(\d+) repository courses match the project domains\.$/, '$1/$2 дисциплин соответствуют областям проекта.'],
        [/^(\d+)\/(\d+) courses are supported by the selected EPVO scope, programme LO evidence, or RK mandatory requirements\.$/, '$1/$2 дисциплин подтверждены выбранной областью CEER, связью с результатами обучения или обязательными требованиями РК.'],
        [/^Interdisciplinary\/bridge units: (\d+)\.$/, 'Междисциплинарных/bridge-модулей: $1.'],
        [/^Not applicable: this is a standard single-direction programme\.$/, 'Не применяется: это стандартная программа одного направления.'],
        [/^(\d+)\/(\d+) learning units include assessment methods\.$/, '$1/$2 учебных единиц содержат методы оценивания.'],
        [/^Promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Подтверждений bridge-модулей: $1; bridge-модулей в плане: $2.'],
        [/^Expert feedback: (\d+); promoted bridge events: (\d+); bridge modules in plan: (\d+)\.$/, 'Экспертных оценок: $1; подтверждений bridge-модулей: $2; bridge-модулей в плане: $3.'],
    ],
}

const BUILD_STAGE_LABELS = {
    ru: { idle: 'Ожидание', matching: 'Сопоставляем результаты обучения с дисциплинами', epvo_repository: 'Подтягиваем дисциплины CEER по выбранным направлениям', scoring: 'Оцениваем связи дисциплина–результат обучения', variants: 'Готовим варианты A/B/C', variant_A_start: 'Строим вариант A', variant_A: 'Проверяем вариант A', variant_B_start: 'Строим вариант B', variant_B: 'Проверяем вариант B', variant_C_start: 'Строим вариант C', variant_C: 'Проверяем вариант C', saving: 'Сохраняем новые планы без порчи старого активного', complete: 'Готово', failed: 'Ошибка' },
    kk: { idle: 'Күту', matching: 'Оқу нәтижелерін пәндермен сәйкестендіру', epvo_repository: 'Таңдалған бағыттар бойынша CEER пәндерін қосу', scoring: 'Пән–оқу нәтижесі байланыстарын бағалау', variants: 'A/B/C нұсқаларын дайындау', variant_A_start: 'A нұсқасын құру', variant_A: 'A нұсқасын тексеру', variant_B_start: 'B нұсқасын құру', variant_B: 'B нұсқасын тексеру', variant_C_start: 'C нұсқасын құру', variant_C: 'C нұсқасын тексеру', saving: 'Ескі белсенді жоспарды бұзбай жаңа жоспарларды сақтау', complete: 'Дайын', failed: 'Қате' },
    en: { idle: 'Waiting', matching: 'Matching learning outcomes with courses', epvo_repository: 'Adding CEER courses for selected fields', scoring: 'Scoring course–learning outcome links', variants: 'Preparing A/B/C variants', variant_A_start: 'Building variant A', variant_A: 'Checking variant A', variant_B_start: 'Building variant B', variant_B: 'Checking variant B', variant_C_start: 'Building variant C', variant_C: 'Checking variant C', saving: 'Saving new plans without corrupting the active one', complete: 'Complete', failed: 'Failed' },
}

export const localizeQualityEvidenceText = (text = '', language = 'ru') => {
    if (language === 'en') return text
    return (QUALITY_EVIDENCE_PATTERNS[language] || QUALITY_EVIDENCE_PATTERNS.ru)
        .reduce((value, [pattern, replacement]) => pattern.test(value) ? value.replace(pattern, replacement) : value, text)
}

export const planBuildStageLabel = (stage = 'idle', language = 'ru') => {
    const labels = BUILD_STAGE_LABELS[language] || BUILD_STAGE_LABELS.ru
    return labels[stage] || stage
}

export const planBuildStageDetail = (status = {}, language = 'ru') => {
    if (status.stage === 'scoring' && status.lo_total) {
        const linkWord = language === 'kk' ? 'байланыс' : language === 'en' ? 'links' : 'связей'
        return `LO ${status.lo_index}/${status.lo_total}${status.lo_code ? ` — ${status.lo_code}` : ''}${status.matches ? `, ${linkWord}: ${status.matches}` : ''}`
    }
    if (status.stage?.startsWith?.('variant_')) {
        if (language === 'kk') return 'Пәндер таңдалып, кредиттер, пререквизиттер және домен шектеулері тексеріліп жатыр.'
        if (language === 'en') return 'Selecting courses and checking credits, prerequisites, and domain constraints.'
        return 'Идёт подбор дисциплин, проверка кредитов, пререквизитов и доменных ограничений.'
    }
    return null
}

export const planBuildElapsedLabel = (status = {}, language = 'ru') => {
    const total = Math.max(0, Math.round(Number(status.elapsed_seconds) || 0))
    if (!total) return null
    const minutes = Math.floor(total / 60)
    const seconds = total % 60
    const value = minutes ? `${minutes} ${language === 'en' ? 'min' : 'мин'} ${seconds} ${language === 'en' ? 'sec' : 'сек'}` : `${seconds} ${language === 'en' ? 'sec' : 'сек'}`
    if (language === 'kk') return `Өткен уақыт: ${value}`
    if (language === 'en') return `Elapsed: ${value}`
    return `Прошло: ${value}`
}

export const alreadyRunningText = language => language === 'kk'
    ? 'Құру процесі жүріп жатыр. Ағымдағы процесс аяқталғанын күтіңіз.'
    : language === 'en'
        ? 'Plan generation is already running. Please wait for the current process to finish.'
        : 'Построение уже идёт. Дождитесь завершения текущего процесса.'

export const longRunningHint = language => language === 'kk'
    ? 'CEER базасы үлкен болса, бұл кезең бірнеше минутқа созылуы мүмкін. Ескі белсенді жоспар барлық нұсқалар сәтті құрылғанша сақталады.'
    : language === 'en'
        ? 'If the CEER catalogue is large, this step may take several minutes. The old active plan is kept until all variants are built successfully.'
        : 'Если экспертная база CEER большая, этап может идти несколько минут. Старый активный план сохраняется до успешного построения всех вариантов.'
