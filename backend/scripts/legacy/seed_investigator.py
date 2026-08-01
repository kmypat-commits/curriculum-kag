import os
import sqlite3
import random
import json
from app.kag.embedding_service import embedding_service

# Absolute path to the database
DB_PATH = os.path.join(os.getcwd(), "curriculum_kag.db")

def seed_professional_forensics():
    print("=" * 60)
    print("CORE SEED ENGINE v7.0 - PROFESSIONAL FORENSICS EDITION")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()

    try:
        # 1. CLEAN START
        print("Wiping existing records for clean re-seed...")
        cursor.execute("DELETE FROM embeddings")
        cursor.execute("DELETE FROM match_scores")
        cursor.execute("DELETE FROM course_chunks")
        cursor.execute("DELETE FROM course_prerequisites")
        cursor.execute("DELETE FROM courses")
        conn.commit()

        # 2. DEFINING SEQUENTIAL CHAINS
        sequences = {
            "core": [
                ["Математика для инженеров", "Дискретная математика", "Теория вероятностей в ИБ"],
                ["Основы программирования", "Алгоритмы и структуры данных", "Объектно-ориентированный анализ"],
                ["Архитектура вычислительных систем", "Администрирование ОС Windows", "Администрирование ОС Linux"]
            ],
            "it": [
                ["Компьютерные сети", "Протоколы стека TCP/IP", "Маршрутизация и коммутация"],
                ["Основы информационной безопасности", "Прикладная криптография", "Защита сетевой инфраструктуры"],
                ["Базы данных и SQL", "Администрирование СУБД", "Безопасность облачных технологий"]
            ],
            "forensics": [
                ["Введение в цифровую криминалистику", "Сбор и фиксация цифровых доказательств", "Форензика файловых систем"],
                ["Расследование инцидентов в Windows", "Анализ реестра и артефактов ОС", "Хронологический анализ (Timeline)"],
                ["Сетевая форензика и анализ трафика", "Расследование Web-атак и логов"],
                ["Мобильная криминалистика (Android/iOS)", "Анализ мессенджеров и облачных бэкапов"]
            ],
            "advanced": [
                ["Реверс-инжиниринг и анализ кода", "Анализ вредоносного ПО (Malware Analysis)"],
                ["Форензика оперативной памяти (RAM)", "Обнаружение скрытого присутствия (Rootkits)"],
                ["Правовые основы киберпреступлений", "Процессуальные требования к доказательствам", "Подготовка экспертных заключений", "Участие эксперта в судебном процессе"]
            ]
        }

        # 3. TECHNICAL DESCRIPTIONS (Critical for LO mapping)
        specific_descriptions = {
            "Сбор и фиксация цифровых доказательств": "Комплексное применение методов цифровой криминалистики для идентификации, сбора и фиксации доказательств в строгом соответствии с юридическими стандартами и процедурой Chain of Custody.",
            "Анализ вредоносного ПО (Malware Analysis)": "Профессиональный анализ вредоносного ПО, охватывающий статический и динамический анализ, реверс-инжиниринг кода и выявление индикаторов компрометации (IOC).",
            "Подготовка экспертных заключений": "Синтез результатов технического расследования в формализованное экспертное заключение, готовое для представления в судебных органах, с соблюдением требований законодательства.",
            "Участие эксперта в судебном процессе": "Процессуальная роль эксперта, методология защиты выводов экспертизы в суде, правовая ответственность и взаимодействие с судебной системой.",
            "Форензика файловых систем": "Детальное изучение структуры NTFS, APFS и Linux FS. Методы анализа метаданных, журналов и нераспределенного пространства для восстановления удаленных данных.",
            "Сетевая форензика и анализ трафика": "Мониторинг и анализ активностей в сетях, работа с PCAP-файлами, дешифровка трафика, выявление аномалий и следов эксфильтрации данных.",
            "Протоколы стека TCP/IP": "Глубокое изучение сетевой архитектуры и протоколов для понимания механизмов атак и разработки стратегий защиты информационных систем.",
            "Реверс-инжиниринг и анализ кода": "Инструментальный анализ программного обеспечения без исходного кода, использование дизассемблеров и отладчиков для документирования недокументированных функций.",
            "Процессуальные требования к доказательствам": "Изучение правовых аспектов допустимости цифровых доказательств, требования к инструментам и верификации результатов исследования."
        }

        # 4. INSERT COURSES
        print("Populating professional course registry...")
        all_inserted_titles = []
        for domain, group in sequences.items():
            for seq in group:
                for idx, title in enumerate(seq):
                    if title not in all_inserted_titles:
                        code = f"{domain[:2].upper()}-{len(all_inserted_titles)+1:03d}"
                        desc = specific_descriptions.get(title, f"Профессиональная программа по дисциплине '{title}'. Курс фокусируется на практических аспектах применения в задачах киберрасследований.")
                        cursor.execute("INSERT INTO courses (course_id, title, domain, credits, description, topics, language, cycle_component) VALUES (?, ?, ?, ?, ?, ?, 'ru', 'обязательный компонент')",
                                     (code, title, domain, 5, desc, json.dumps([domain, "security"]), ))
                        all_inserted_titles.append(title)
        
        conn.commit()

        # 5. UNIQUE PREREQUISITES ENGINE
        print("Processing prerequisites (Unique Set mode)...")
        cursor.execute("SELECT id, title FROM courses")
        course_map = {row[1]: row[0] for row in cursor.fetchall()}
        
        unique_links = set() # STRICT UNIQUENESS

        # Auto-chain links
        for domain, group in sequences.items():
            for seq in group:
                for i in range(1, len(seq)):
                    child = course_map.get(seq[i])
                    parent = course_map.get(seq[i-1])
                    if child and parent: unique_links.add((child, parent))

        # Strategic Cross-Domain links
        def add_unique_link(child_name, parent_name):
            c_id = course_map.get(child_name)
            p_id = course_map.get(parent_name)
            if c_id and p_id: unique_links.add((c_id, p_id))

        add_unique_link("Введение в цифровую криминалистику", "Архитектура вычислительных систем")
        add_unique_link("Введение в цифровую криминалистику", "Компьютерные сети")
        add_unique_link("Сетевая форензика и анализ трафика", "Протоколы стека TCP/IP")
        add_unique_link("Реверс-инжиниринг и анализ кода", "Алгоритмы и структуры данных")
        add_unique_link("Подготовка экспертных заключений", "Процессуальные требования к доказательствам")
        add_unique_link("Анализ вредоносного ПО (Malware Analysis)", "Реверс-инжиниринг и анализ кода")

        # Execute final unique insertion
        cursor.executemany("INSERT INTO course_prerequisites (course_id, prerequisite_id) VALUES (?, ?)", list(unique_links))
        conn.commit()

        # 6. NEURAL MAPPING
        print("\n" + "=" * 60)
        print("PHASE 6: NEURAL MAPPING (High Precision)")
        print("=" * 60)
        
        cursor.execute("SELECT id, title, description FROM courses")
        courses = cursor.fetchall()
        total_courses = len(courses)
        
        print(f"Preparing to process {total_courses} courses...")
        
        # Prepare data for batch processing
        course_data = []
        texts_to_encode = []
        
        for c_id, title, desc in courses:
            full_text = f"{title}. {desc}"
            # Insert chunk first to get ID
            cursor.execute("INSERT INTO course_chunks (course_id, chunk_type, chunk_text, chunk_index) VALUES (?, 'description', ?, 0)", (c_id, desc))
            chunk_id = cursor.lastrowid
            course_data.append((chunk_id, full_text))
            texts_to_encode.append(full_text)
        
        print(f"Generating embeddings for {total_courses} courses...")
        if hasattr(embedding_service, 'encode_batch'):
            vectors = embedding_service.encode_batch(texts_to_encode)
        else:
            # Fallback if encode_batch is not available (though it should be)
            vectors = [embedding_service.encode(t) for t in texts_to_encode]
            
        print("Inserting embeddings into database...")
        for i, (chunk_id, _) in enumerate(course_data):
            vector = vectors[i]
            cursor.execute("INSERT INTO embeddings (chunk_id, vector, model_version) VALUES (?, ?, ?)", 
                          (chunk_id, json.dumps(vector.tolist()), embedding_service.get_model_version()))
            if (i + 1) % 5 == 0 or (i + 1) == total_courses:
                print(f"  Progress: {i + 1}/{total_courses} courses processed")

        conn.commit()
        print(f"\n--- SUCCESS: DATABASE V7.0 IS LIVE ---")
        print(f"Total Courses: {total_courses}")
        print(f"Unique Links: {len(unique_links)}")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    seed_professional_forensics()
