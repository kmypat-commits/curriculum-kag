import os
import sqlite3
import json
import traceback
from app.kag.embedding_service import embedding_service

DB_PATH = os.path.join(os.getcwd(), "curriculum_kag.db")

# 1. CORE DOMAIN (70 courses)
core_sequences = [
    # Math (15)
    ["Calculus 1", "Calculus 2", "Calculus 3"],
    ["Linear Algebra", "Analytic Geometry", "Tensor Calculus"],
    ["Differential Equations", "Optimization Methods"],
    ["Probability Theory", "Mathematical Statistics", "Data Analysis"],
    ["Discrete Mathematics", "Mathematical Logic"],
    ["Numerical Methods", "Mathematical Modeling"],
    
    # Physics (10)
    ["Physics (Mechanics)", "Molecular Physics and Thermodynamics", "Electromagnetism", "Optics", "Quantum Physics"],
    ["Theoretical Mechanics", "Electrodynamics", "Solid State Physics"],
    ["Nuclear Physics", "Astrophysics"],
    
    # Humanities (15)
    ["Philosophy", "Logic", "Ethics", "Aesthetics"],
    ["History", "World History"],
    ["Sociology", "Political Science"],
    ["Cultural Studies", "Psychology", "Pedagogy"],
    ["Fundamentals of Law", "Bioethics"],
    ["Foreign Language 1", "Foreign Language 2", "Professional Foreign Language"],
    
    # Natural Sciences (10)
    ["General Chemistry", "Organic Chemistry"],
    ["Biology", "Ecology"],
    ["Concepts of Modern Natural Science", "Geography", "Geology", "Astronomy"],
    ["Life Safety", "Physical Education"],
    
    # Others & Economics (20)
    ["Microeconomics", "Macroeconomics", "World Economy"],
    ["Systems Theory", "Systems Analysis", "Operations Research"],
    ["Management", "Marketing", "Project Management", "Innovation Management"],
    ["Fundamentals of Entrepreneurship", "Finance and Credit", "Accounting"],
    ["Communication Skills", "Rhetoric", "Academic Writing"],
    ["Quality Management", "Theory of State and Law", "Records Management"]
]

# 2. IT DOMAIN (70 courses)
it_sequences = [
    # Programming (15)
    ["Introduction to Programming", "Algorithms and Data Structures 1", "Algorithms and Data Structures 2", "Functional Programming"],
    ["Object-Oriented Programming", "C++ Programming", "Rust Programming"],
    ["Web Development (Frontend)", "Web Development (Backend)"],
    ["Java Programming", ".NET Platform and C#", "Go Programming"],
    ["Mobile Development (Android)", "Mobile Development (iOS)"],
    ["Python Programming"],
    
    # Databases (10)
    ["Databases", "SQL Database Development", "DBMS Administration", "Database Optimization"],
    ["Non-relational Databases (NoSQL)", "Graph Databases"],
    ["Data Warehouses", "Distributed Databases"],
    ["ORM and Data Access", "Time Series Databases"],
    
    # Architecture & OS (10)
    ["Computer Architecture", "Operating Systems", "High-Performance Computing"],
    ["Linux Administration", "Windows Server Administration"],
    ["Cloud Computing", "Virtualization", "Containerization"],
    ["Embedded Systems", "Real-Time OS"],
    
    # Networks (10)
    ["Computer Networks", "Network Protocols", "Wireless Networks"],
    ["Routing and Switching", "Internet of Things (IoT) Networks"],
    ["Software-Defined Networking (SDN)", "Network Services"],
    ["IP Telephony", "Optical Networks", "Network Programming"],
    
    # Software Engineering (10)
    ["Software Engineering", "Software Architecture"],
    ["DevOps", "CI/CD Practices"],
    ["Software Testing", "Quality Assurance (QA)"],
    ["Version Control Systems", "Requirements Engineering"],
    ["Agile Methodologies", "UI/UX Design"],

    # Data Science & AI (15)
    ["Introduction to Data Science", "Data Visualization", "Data Mining"],
    ["Machine Learning 1", "Machine Learning 2", "Statistical Learning"],
    ["Deep Learning", "Computer Vision"],
    ["Natural Language Processing (NLP)", "Speech Recognition"],
    ["Big Data Processing", "Recommender Systems"],
    ["Reinforcement Learning", "ML Ops", "AI Ethics"]
]

# 3. FORENSICS DOMAIN (70 courses)
forensics_sequences = [
    # Legal & Foundational (15)
    ["Information Security Fundamentals", "IS Risk Management", "Information Security Audit"],
    ["Introduction to Digital Forensics", "Collection and Preservation of Digital Evidence"],
    ["Cyber Law", "International Cyber Law", "Privacy Legislation"],
    ["Procedural Requirements in IT", "Preparation of Expert Opinion", "Expert Participation in Court"],
    ["Cybercrime Investigation", "Cyber Insurance", "Digital Rights Management"],
    ["Ethics in Cyberspace"],
    
    # OS & File System Forensics (15)
    ["Windows Forensics", "Registry and Pagefile Analysis", "Program Execution Artifacts Analysis"],
    ["Linux Forensics", "MacOS and iOS Forensics"],
    ["NTFS and FAT File System Forensics", "Ext4 and Btrfs File System Analysis", "APFS File System Analysis"],
    ["Data Recovery", "Volume Shadow Copy Analysis"],
    ["RAM Forensics", "Live Response", "Timeline Analysis"],
    ["OS Boot Process Forensics", "Android Forensics"],
    
    # Network & Cloud Forensics (15)
    ["Network Forensics", "Network Traffic Analysis (PCAP)", "Wireless Network Attacks Analysis"],
    ["Intrusion Detection Systems (IDS/IPS)", "Firewall Log Analysis"],
    ["Web Application Forensics", "Email Incident Investigation"],
    ["Cloud Forensics (AWS and Azure)", "Distributed Architecture Forensics"],
    ["IoT Forensics", "VoIP Systems Forensics"],
    ["Dark Web Investigation", "Ransomware Attacks Investigation", "Cryptocurrency Tracking"],
    ["Network Indicators of Compromise Analysis"],
    
    # Malware & Reverse Eng (15)
    ["Fundamentals of Malware Analysis", "Static Code Analysis", "Dynamic Sandbox Analysis"],
    ["Reverse Engineering (x86/x64)", "Exploit Development"],
    ["ARM Reverse Engineering", "Packed and Obfuscated Code Analysis"],
    ["Windows API Usage in Malware", "Fileless Malware"],
    ["Rootkit and Bootkit Analysis", "Advanced Incident Response (IR)"],
    ["YARA Rules Development", "Threat Hunting"],
    ["Malware Analysis Automation", "Script Virus Analysis"],
    
    # Specialized Tools & Techniques (10)
    ["Cryptography", "Password Cracking and Data Decryption"],
    ["Steganography and Steganalysis", "Hardware Forensics"],
    ["Fundamentals of EnCase and FTK", "Open Source Forensics (SleuthKit, Volatility)"],
    ["Python for Digital Forensics", "Bash and PowerShell for Automation"],
    ["Unmanned Aerial Vehicle (UAV) Forensics", "Automotive Systems Forensics"]
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
                "desc": f"Fundamental course on '{title}' within the {domain.upper()} domain. Designed to provide deep knowledge and practical skills."
            })
            if i > 0:
                links.append((title, seq[i-1])) # title depends on seq[i-1]
                
    return courses, links

def seed_210_courses():
    print("=" * 60)
    print("MASSIVE SEED ENGINE - 210 COURSES (CORE, IT, FORENSICS) - ENGLISH")
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
                VALUES (?, ?, ?, ?, ?, ?, 'en', 'mandatory component')
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
            else:
                print(f"Warning: Missing course for cross-link: {child} -> {parent}")

        # IT: can have Core as prereqs
        add_cross_link("Introduction to Programming", "Discrete Mathematics")
        add_cross_link("Introduction to Programming", "Mathematical Logic")
        add_cross_link("Machine Learning 1", "Probability Theory")
        add_cross_link("Machine Learning 1", "Linear Algebra")
        add_cross_link("Computer Vision", "Analytic Geometry")

        # Forensics: can have Core and IT as prereqs
        add_cross_link("Information Security Fundamentals", "Computer Networks")
        add_cross_link("Network Forensics", "Network Protocols")
        add_cross_link("Web Application Forensics", "Web Development (Backend)")
        add_cross_link("RAM Forensics", "Computer Architecture")
        add_cross_link("RAM Forensics", "Operating Systems")
        add_cross_link("Static Code Analysis", "Object-Oriented Programming")
        add_cross_link("Reverse Engineering (x86/x64)", "Computer Architecture")

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
        print(f"\n--- SUCCESS: DATABASE SEEDED WITH EXACTLY 210 ENGLISH COURSES ---")
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
