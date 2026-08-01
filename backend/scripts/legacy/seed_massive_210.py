import os
import sqlite3
import json
import traceback
from app.kag.embedding_service import embedding_service

DB_PATH = os.path.join(os.getcwd(), "curriculum_kag.db")

# 1. CORE DOMAIN (70 courses)
core_sequences = [
    # Math (15)
    ["Математический анализ 1", "Математический анализ 2", "Математический анализ 3"],
    ["Линейная алгебра", "Аналитическая геометрия", "Тензорное исчисление"],
    ["Дифференциальные уравнения", "Методы оптимизации"],
    ["Теория вероятностей", "Математическая статистика", "Анализ данных"],
    ["Дискретная математика", "Математическая логика"],
    ["Численные методы", "Математическое моделирование"],
    
    # Physics (10)
    ["Физика (Механика)", "Молекулярная физика и термодинамика", "Электромагнетизм", "Оптика", "Квантовая физика"],
    ["Теоретическая механика", "Электродинамика", "Физика твердого тела"],
    ["Ядерная физика", "Астрофизика"],
    
    # Humanities (15)
    ["Философия", "Логика", "Этика", "Эстетика"],
    ["История", "Всемирная история"],
    ["Социология", "Политология"],
    ["Культурология", "Психология", "Педагогика"],
    ["Основы права", "Биоэтика"],
    ["Иностранный язык 1", "Иностранный язык 2", "Профессиональный иностранный язык"],
    
    # Natural Sciences (10)
    ["Общая химия", "Органическая химия"],
    ["Биология", "Экология"],
    ["Концепции современного естествознания", "География", "Геология", "Астрономия"],
    ["Безопасность жизнедеятельности", "Физическая культура"],
    
    # Others & Economics (20)
    ["Микроэкономика", "Макроэкономика", "Мировая экономика"],
    ["Теория систем", "Системный анализ", "Исследование операций"],
    ["Менеджмент", "Маркетинг", "Управление проектами", "Инновационный менеджмент"],
    ["Основы предпринимательства", "Финансы и кредит", "Бухгалтерский учет"],
    ["Коммуникативные навыки", "Риторика", "Академическое письмо"],
    ["Управление качеством", "Теория государства и права", "Документоведение"]
]

# 2. IT DOMAIN (70 courses)
it_sequences = [
    # Programming (15)
    ["Введение в программирование", "Алгоритмы и структуры данных 1", "Алгоритмы и структуры данных 2", "Функциональное программирование"],
    ["Объектно-ориентированное программирование", "Программирование на C++", "Программирование на Rust"],
    ["Веб-разработка (Frontend)", "Веб-разработка (Backend)"],
    ["Программирование на Java", "Платформа .NET и C#", "Программирование на Go"],
    ["Мобильная разработка (Android)", "Мобильная разработка (iOS)"],
    ["Программирование на Python"],
    
    # Databases (10)
    ["Базы данных", "Разработка SQL баз данных", "Администрирование СУБД", "Оптимизация баз данных"],
    ["Нереляционные базы данных (NoSQL)", "Графовые базы данных"],
    ["Хранилища данных", "Распределенные базы данных"],
    ["ORM и доступ к данным", "Базы данных временных рядов"],
    
    # Architecture & OS (10)
    ["Архитектура компьютера", "Операционные системы", "Высокопроизводительные вычисления"],
    ["Администрирование Linux", "Администрирование Windows Server"],
    ["Облачные вычисления", "Виртуализация", "Контейнеризация"],
    ["Встраиваемые системы", "ОС реального времени"],
    
    # Networks (10)
    ["Компьютерные сети", "Сетевые протоколы", "Беспроводные сети"],
    ["Маршрутизация и коммутация", "Сети Интернета вещей (IoT)"],
    ["Программно-определяемые сети (SDN)", "Сетевые службы и сервисы"],
    ["IP-телефония", "Оптические сети", "Сетевое программирование"],
    
    # Software Engineering (10)
    ["Программная инженерия", "Архитектура программного обеспечения"],
    ["DevOps", "CI/CD практики"],
    ["Тестирование программного обеспечения", "Обеспечение качества ПО (QA)"],
    ["Системы контроля версий", "Инженерия требований"],
    ["Agile методологии", "UI/UX дизайн"],

    # Data Science & AI (15)
    ["Введение в Data Science", "Визуализация данных", "Майнинг данных"],
    ["Машинное обучение 1", "Машинное обучение 2", "Статистическое обучение"],
    ["Глубокое обучение", "Компьютерное зрение"],
    ["Обработка естественного языка (NLP)", "Распознавание речи"],
    ["Обработка больших данных (Big Data)", "Рекомендательные системы"],
    ["Обучение с подкреплением", "ML Ops", "Этика в искусственном интеллекте"]
]

# 3. FORENSICS DOMAIN (70 courses)
forensics_sequences = [
    # Legal & Foundational (15)
    ["Основы информационной безопасности", "Управление рисками ИБ", "Аудит информационной безопасности"],
    ["Введение в цифровую криминалистику", "Сбор и фиксация цифровых доказательств"],
    ["Киберправо", "Международное киберправо", "Законодательство в сфере конфиденциальности"],
    ["Процессуальные требования в ИТ", "Подготовка экспертного заключения", "Участие эксперта в суде"],
    ["Расследование киберпреступлений", "Киберстрахование", "Цифровое управление правами"],
    ["Этика в киберпространстве"],
    
    # OS & File System Forensics (15)
    ["Форензика Windows", "Анализ реестра и файлов подкачки", "Анализ артефактов выполнения программ"],
    ["Форензика Linux", "Форензика MacOS и iOS"],
    ["Форензика файловых систем NTFS и FAT", "Анализ файловых систем Ext4 и Btrfs", "Анализ файловых систем APFS"],
    ["Восстановление удаленных данных", "Анализ теневых копий томов"],
    ["Форензика оперативной памяти", "Живое реагирование (Live Response)", "Хронологический анализ (Timeline)"],
    ["Форензика процесса загрузки ОС", "Форензика Android"],
    
    # Network & Cloud Forensics (15)
    ["Сетевая криминалистика", "Анализ сетевого трафика (PCAP)", "Анализ атак на беспроводные сети"],
    ["Системы обнаружения вторжений (IDS/IPS)", "Анализ журналов межсетевых экранов"],
    ["Форензика веб-приложений", "Расследование инцидентов электронной почты"],
    ["Облачная форензика (AWS и Azure)", "Форензика распределенных архитектур"],
    ["Форензика IoT устройств", "Форензика VoIP систем"],
    ["Исследование Dark Web", "Расследование атак Ransomware", "Отслеживание криптовалют"],
    ["Анализ сетевых индикаторов компрометации"],
    
    # Malware & Reverse Eng (15)
    ["Основы анализа вредоносного ПО", "Статический анализ кода", "Динамический анализ в песочнице"],
    ["Реверс-инжиниринг (x86/x64)", "Разработка эксплойтов"],
    ["Реверс-инжиниринг ARM", "Анализ упакованного и обфусцированного кода"],
    ["Использование Windows API во вредоносном ПО", "Бестелесное вредоносное ПО (Fileless Malware)"],
    ["Анализ руткитов и буткитов", "Расширенное реагирование на инциденты (IR)"],
    ["Разработка YARA правил", "Охота за угрозами (Threat Hunting)"],
    ["Автоматизация анализа ВПО", "Анализ скриптовых вирусов"],
    
    # Specialized Tools & Techniques (10)
    ["Криптография", "Взлом паролей и дешифрование данных"],
    ["Стеганография и стегоанализ", "Аппаратная форензика"],
    ["Основы работы в EnCase и FTK", "Open Source форензика (SleuthKit, Volatility)"],
    ["Python для цифровой криминалистики", "Bash и PowerShell для автоматизации"],
    ["Криминалистика беспилотных аппаратов (БПЛА)", "Форензика автомобильных систем"]
]

def flatten_courses(sequences, domain):
    courses = []
    links = []
    
    # Flatten and build local prerequisites
    for seq in sequences:
        for i, title in enumerate(seq):
            courses.append({
                "title": title,
                "domain": domain,
                "desc": f"Фундаментальный курс по дисциплине '{title}' в рамках домена {domain.upper()}. Разработан для получения глубоких знаний и практических навыков."
            })
            if i > 0:
                links.append((title, seq[i-1])) # title depends on seq[i-1]
                
    return courses, links

def seed_210_courses():
    print("=" * 60)
    print("MASSIVE SEED ENGINE - 210 COURSES (CORE, IT, FORENSICS)")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()

    try:
        # 1. CLEAN START (WIPE EVERYTHING)
        print("Wiping existing records for clean 210-course re-seed...")
        cursor.execute("DELETE FROM embeddings")
        cursor.execute("DELETE FROM match_scores")
        cursor.execute("DELETE FROM course_chunks")
        cursor.execute("DELETE FROM course_prerequisites")
        cursor.execute("DELETE FROM courses")
        conn.commit()

        print("Generating course lists...")
        core_courses, core_links = flatten_courses(core_sequences, "core")
        it_courses, it_links = flatten_courses(it_sequences, "it")
        forensics_courses, forensics_links = flatten_courses(forensics_sequences, "forensics")
        
        all_courses = core_courses + it_courses + forensics_courses
        
        # Verify counts
        print(f"Core courses: {len(core_courses)}")
        print(f"IT courses: {len(it_courses)}")
        print(f"Forensics courses: {len(forensics_courses)}")
        print(f"Total courses: {len(all_courses)}")
        
        if len(all_courses) != 210:
            print("WARNING: Total course count is not exactly 210. Please check the lists.")

        # 2. INSERT COURSES
        print("Populating database with courses...")
        course_map = {} # title -> id
        
        count = 1
        for c in all_courses:
            code = f"{c['domain'][:2].upper()}-{count:03d}"
            cursor.execute("""
                INSERT INTO courses (course_id, title, domain, credits, description, topics, language, cycle_component) 
                VALUES (?, ?, ?, ?, ?, ?, 'ru', 'обязательный компонент')
            """, (code, c['title'], c['domain'], 5, c['desc'], json.dumps([c['domain']])))
            c_id = cursor.lastrowid
            course_map[c['title']] = c_id
            count += 1
            
        conn.commit()

        # 3. SET PREREQUISITES
        print("Processing prerequisites (respecting strict domain rules)...")
        # Local links inside domains
        all_links = core_links + it_links + forensics_links
        unique_links = set()
        
        for child_title, parent_title in all_links:
            unique_links.add((course_map[child_title], course_map[parent_title]))
            
        # Cross-domain links (according to rules)
        # Core: ONLY Core as prereqs (ruled out by default since local links handle this and no external added)
        def add_cross_link(child, parent):
            if child in course_map and parent in course_map:
                unique_links.add((course_map[child], course_map[parent]))

        # IT: can have Core as prereqs
        add_cross_link("Введение в программирование", "Дискретная математика")
        add_cross_link("Введение в программирование", "Математическая логика")
        add_cross_link("Машинное обучение 1", "Теория вероятностей")
        add_cross_link("Машинное обучение 1", "Линейная алгебра")
        add_cross_link("Компьютерное зрение", "Аналитическая геометрия")

        # Forensics: can have Core and IT as prereqs
        add_cross_link("Основы информационной безопасности", "Компьютерные сети")
        add_cross_link("Сетевая криминалистика", "Сетевые протоколы")
        add_cross_link("Форензика веб-приложений", "Веб-разработка (Backend)")
        add_cross_link("Форензика оперативной памяти", "Архитектура компьютера")
        add_cross_link("Форензика оперативной памяти", "Операционные системы")
        add_cross_link("Статический анализ кода", "Объектно-ориентированное программирование")
        add_cross_link("Реверс-инжиниринг (x86/x64)", "Архитектура компьютера")

        # Filter out KeyError if typos exist
        final_links = []
        for child_id, parent_id in unique_links:
            final_links.append((child_id, parent_id))

        cursor.executemany("INSERT INTO course_prerequisites (course_id, prerequisite_id) VALUES (?, ?)", final_links)
        conn.commit()

        # 4. NEURAL MAPPING
        print("\n" + "=" * 60)
        print("PHASE 4: NEURAL MAPPING (High Precision)")
        print("=" * 60)
        
        total_courses = len(all_courses)
        print(f"Preparing to process {total_courses} courses...")
        
        course_data = []
        texts_to_encode = []
        
        cursor.execute("SELECT id, title, description FROM courses")
        db_courses = cursor.fetchall()
        
        for c_id, title, desc in db_courses:
            full_text = f"{title}. {desc}"
            cursor.execute("INSERT INTO course_chunks (course_id, chunk_type, chunk_text, chunk_index) VALUES (?, 'description', ?, 0)", (c_id, desc))
            chunk_id = cursor.lastrowid
            course_data.append((chunk_id, full_text))
            texts_to_encode.append(full_text)
        
        print(f"Generating embeddings for {total_courses} courses...")
        if hasattr(embedding_service, 'encode_batch'):
            vectors = embedding_service.encode_batch(texts_to_encode)
        else:
            vectors = [embedding_service.encode(t) for t in texts_to_encode]
            
        print("Inserting embeddings into database...")
        for i, (chunk_id, _) in enumerate(course_data):
            vector = vectors[i]
            cursor.execute("INSERT INTO embeddings (chunk_id, vector, model_version) VALUES (?, ?, ?)", 
                          (chunk_id, json.dumps(vector.tolist()), embedding_service.get_model_version()))
            if (i + 1) % 10 == 0 or (i + 1) == total_courses:
                print(f"  Progress: {i + 1}/{total_courses} courses processed")

        conn.commit()
        print(f"\n--- SUCCESS: DATABASE SEEDED WITH EXACTLY 210 COURSES ---")
        print(f"Total Courses: {total_courses}")
        print(f"Prerequisite Links: {len(final_links)}")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    seed_210_courses()
