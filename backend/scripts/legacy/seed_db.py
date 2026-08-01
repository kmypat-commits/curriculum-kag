
import os
import json
import random
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, engine
from app.models.user import User, Role
from app.models.course import Course, CourseChunk
from app.models.project import Project, ProjectVersion, LearningOutcome
from app.models.plan import Plan, PlanItem
from app.models.bridge_module import BridgeModule
from app.models.embedding import MatchScore, Embedding, HAS_PGVECTOR
import bcrypt

# Fix for Passlib + Bcrypt 4.1.0+ compatibility on Python 3.14
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type('about', (object,), {'__version__': bcrypt.__version__})

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def seed_data():
    print("--- STARTING DATABASE SCALE-UP (130 COURSES) ---")
    
    # Ensure tables are created
    Base.metadata.create_all(bind=engine)
    
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # 1. CLEANING
        print("Cleaning existing courses and embeddings...")
        db.query(Embedding).delete()
        db.query(MatchScore).delete()
        db.query(CourseChunk).delete()
        
        # Clear many-to-many relationships
        for c in db.query(Course).all():
            c.prerequisites = []
        db.commit()
        
        db.query(Course).delete()
        db.commit()
        print("Database cleaned.")

        # 2. USERS & ROLES
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if not admin_role:
            admin_role = Role(name="admin")
            db.add(admin_role)
            db.add(Role(name="methodist"))
            db.flush()
        
        admin = db.query(User).filter(User.email == "admin@curriculum-kag.local").first()
        if not admin:
            admin = User(
                email="admin@curriculum-kag.local",
                full_name="System Administrator",
                hashed_password=pwd_context.hash("admin123"),
                is_active=1
            )
            admin.roles = [admin_role]
            db.add(admin)

        # 3. 200 COURSES DATA
        cyber_courses = [
            ("CYB01", "Введение в кибербезопасность", ["Безопасность", "Угрозы"]),
            ("CYB02", "Сетевая безопасность", ["TCP/IP", "Firewall"]),
            ("CYB03", "Криптографические методы", ["AES", "RSA"]),
            ("CYB04", "Этичный хакинг", ["Pentest", "Nmap"]),
            ("CYB05", "Облачная безопасность", ["AWS", "Azure"]),
            ("CYB06", "Защита мобильных устройств", ["Android", "iOS"]),
            ("CYB07", "Управление инцидентами", ["SOC", "SIEM"]),
            ("CYB08", "Анализ вредоносного ПО", ["IDA Pro", "Reverse"]),
            ("CYB09", "Инфраструктура PKI", ["Certificates", "CA"]),
            ("CYB10", "Безопасность Веб", ["OWASP", "SQLi"]),
        ]
        # Append 90 more to reach 100
        for i in range(11, 101):
            cyber_courses.append((f"CYB{i:02d}", f"Спецкурс Кибербезопасности #{i}", ["Cyber", f"Topic{i}"]))

        forensic_courses = [
            ("FOR01", "Основы криминалистики", ["Evidence", "Chain"]),
            ("FOR02", "Исследование дисков", ["EnCase", "Imaging"]),
            ("FOR03", "Расследование Windows", ["Registry", "Logs"]),
            ("FOR04", "Анализ Linux/Unix", ["Syslog", "Ext4"]),
            ("FOR05", "Мобильная криминалистика", ["Cellebrite", "SQLite"]),
            ("FOR06", "Сетевая форензика", ["Packet Analysis", "Flow"]),
            ("FOR07", "Анализ памяти", ["Volatility", "Memory"]),
            ("FOR08", "Восстановление данных", ["Carving", "Metadata"]),
            ("FOR09", "Экспертиза почты", ["SMTP", "Messengers"]),
            ("FOR10", "Облачная форензика", ["Google Drive", "iCloud"]),
        ]
        # Append 90 more to reach 100
        for i in range(11, 101):
            forensic_courses.append((f"FOR{i:02d}", f"Спецкурс Криминалистики #{i}", ["Forensics", f"F-Topic{i}"]))

        print(f"Adding {len(cyber_courses) + len(forensic_courses)} courses (exactly 5 credits each)...")
        
        cycle_options = ["обязательный компонент", "вузовский компонент", "компонент по выбору"]
        
        all_courses = []
        for code, title, tags in cyber_courses:
            cycle = cycle_options[0] if int(code[3:]) <= 30 else (cycle_options[1] if int(code[3:]) <= 60 else cycle_options[2])
            c = Course(course_id=code, title=title, domain="cybersecurity", credits=5, cycle_component=cycle, description=f"{title}. Ключевые слова: {', '.join(tags)}.", topics=tags)
            db.add(c)
            all_courses.append(c)
            
        for code, title, tags in forensic_courses:
            cycle = cycle_options[0] if int(code[3:]) <= 30 else (cycle_options[1] if int(code[3:]) <= 60 else cycle_options[2])
            c = Course(course_id=code, title=title, domain="forensics", credits=5, cycle_component=cycle, description=f"{title}. Ключевые слова: {', '.join(tags)}.", topics=tags)
            db.add(c)
            all_courses.append(c)

        db.flush()
        
        # 4. BATCH EMBEDDINGS (Skip models if we want it to be fast/lite, or use them if available)
        print("Generating mock embeddings for speed (semantic search will be functional but random)...")
        for c in all_courses:
            chunk = CourseChunk(course_id=c.id, chunk_type="description", chunk_text=c.description, chunk_index=0)
            db.add(chunk)
            db.flush()
            
            # Use deterministic random based on course_id
            import hashlib
            h = int(hashlib.md5(c.course_id.encode()).hexdigest(), 16) % 10**8
            random.seed(h)
            vec = [random.uniform(-1, 1) for _ in range(768)]
            
            emb = Embedding(
                chunk_id=chunk.id,
                vector=json.dumps(vec) if not HAS_PGVECTOR else vec,
                model_version="seed-fast-v1"
            )
            db.add(emb)

        # 5. PREREQUISITES LOGIC (Sets bidirectional relationships automatically)
        print("Linking mandatory prerequisites...")
        courses_by_code = {c.course_id: c for c in all_courses}
        random.seed(42)
        
        for code, c in courses_by_code.items():
            prefix = code[:3]
            num = int(code[3:])
            
            # Logic: higher numbers depend on lower numbers
            if num > 1:
                # 01 is root for all 02-10
                if 2 <= num <= 10: prereq_code = f"{prefix}01"
                # 11-30 depend on a random from 02-10
                elif 11 <= num <= 30: prereq_code = f"{prefix}{random.randint(2, 10):02d}"
                # 31-65 depend on a random from 11-30
                else: prereq_code = f"{prefix}{random.randint(11, 30):02d}"
                
                if prereq_code in courses_by_code:
                    c.prerequisites.append(courses_by_code[prereq_code])

        db.commit()
        
        # 6. VERIFICATION
        final_count = db.query(Course).count()
        wrong_credits = db.query(Course).filter(Course.credits != 5).count()
        linked_count = db.query(Course).filter(Course.prerequisites.any()).count()
        
        print(f"\n--- VERIFICATION REPORT ---")
        print(f"Total Courses: {final_count} (Goal: 200)")
        print(f"Non-5-Credit Courses: {wrong_credits} (Goal: 0)")
        print(f"Courses with Pre/Postrequisites: {linked_count}")
        print(f"--- SEEDING COMPLETE ---")

    except Exception as e:
        db.rollback()
        print(f"FATAL ERROR: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
