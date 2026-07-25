# Curriculum-KAG — большая справка для продолжения работы в Codex

Дата контекста: 25 июня 2026  
Рабочая папка: `D:\curriculum-kag\curriculum-kag`  
Основной локальный URL: `http://localhost:3001/`  
Backend API: `http://127.0.0.1:8000/`  
Frontend static/proxy server: `http://127.0.0.1:3001/`

## 1. Смысл системы

Это диссертационный прототип системы для разработки образовательных программ. Важная идея: система не должна выглядеть как обычный “AI curriculum generator”. Она должна демонстрировать архитектуру Curriculum-KAG.

Формула системы:

```text
Curriculum Knowledge Base
= semantic vector index + curriculum knowledge graph

Generation pipeline
= hybrid retrieval + graph expansion + prerequisite closure + optimization + verifier + bridge trigger + expert feedback loop
```

То есть система должна:

- хранить репозиторий дисциплин;
- индексировать дисциплины через embeddings;
- строить curriculum knowledge graph;
- подбирать дисциплины под learning outcomes;
- проверять план по кредитам, prerequisites, LO coverage;
- создавать bridge modules при пробелах;
- позволять эксперту подтвердить bridge module через Promote to Course;
- после promotion расширять базу знаний и использовать новый курс в будущих генерациях.

Для диссертации главный смысл: показать не просто генерацию текста, а knowledge accumulation / expert-in-the-loop learning.

## 2. Главный демонстрационный кейс

Изначально система была заточена под case study Cyber Investigator:

- 8 семестров;
- 240 ECTS;
- IT + Digital Forensics;
- LO1–LO7;
- strict verification.

Но это было исправлено: Cyber Investigator теперь не должен быть hardcoded. Система должна работать и для других программ.

Текущий важный тестовый проект:

```text
Project ID: 6
Title: Цифровое государственное управление
Domain 1: Государственное управление
Domain 2: Информационные системы
Semesters: 2
Credits: 60
Allowed semester load: обычно 30 ± 3
Total credits allowed: target..target+5
```

Для этого проекта НЕЛЬЗЯ подбирать дисциплины вроде:

- Introduction to Human Anatomy;
- Introduction to Electrical Engineering;
- Medicine;
- Electrical Engineering;
- чужие core/math/engineering курсы, если они не относятся к проектным доменам.

Это уже исправлялось. Сейчас backend содержит предохранитель: если планировщик попытается сохранить дисциплину вне доменов проекта, он должен выбросить ошибку и не записать мусорный план.

## 3. Как запускать проект

Обычный запуск теперь выполняется одной командой из корня проекта:

```powershell
.\start.bat
```

Сценарий:

- проверяет `backend\venv\Scripts\python.exe` и при необходимости пересоздаёт окружение;
- при изменениях пересобирает frontend и копирует сборку в `.runtime\dist`;
- запускает backend на `127.0.0.1:8000`;
- запускает переносимый static/proxy server на `127.0.0.1:3001`;
- ждёт оба health check;
- открывает `http://localhost:3001/`.

Повторный запуск не создаёт дубликаты процессов. Остановка:

```powershell
.\stop.bat
```

Принудительная пересборка frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Rebuild
```

Health check:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:3001/api/health
```

Логи ошибок находятся в `.runtime\backend.err.log` и `.runtime\frontend.err.log`.

Логин:

```text
Email: admin@curriculum-kag.local
Password: admin123
```

## 4. Основная структура проекта

```text
backend/
  app/
    api/
      auth.py
      projects.py
      repository.py
      planner.py
      kag.py
      export_api.py
    kag/
      embedding_service.py
      indexing.py
      retrieval.py
      scoring.py
      gap_detector.py
      bridge_generator.py
      knowledge_graph.py
      feedback.py
      duplication_detector.py
    planner/
      scheduler.py
      verifier.py
      international_quality.py
    models/
      user.py
      course.py
      project.py
      plan.py
      bridge_module.py
      embedding.py
      audit.py
      __init__.py
  curriculum_kag.db
frontend/
  src/
    pages/
      Dashboard.jsx
      ProjectDetails.jsx
      ProjectWizard.jsx
      PlanBuilder.jsx
      LOCoverageDashboard.jsx
      Repository.jsx
    contexts/
      AuthContext.jsx
      LanguageContext.jsx
    translations.js
.runtime/
  frontend_server.py
  dist/
CODEX_CONTEXT_RU.md
```

## 5. База данных

Основная SQLite база:

```text
backend\curriculum_kag.db
```

В корне также есть `curriculum_kag.db`, но важная рабочая база для backend — в папке `backend`, потому что backend запускается из `backend`, а `.env` содержит относительный путь:

```text
DATABASE_URL=sqlite:///./curriculum_kag.db
```

Если backend запустить из другой папки, он может смотреть на другую SQLite базу. Поэтому лучше запускать backend с working directory:

```text
D:\curriculum-kag\curriculum-kag\backend
```

## 6. Основные модели

### Course

Файл:

```text
backend\app\models\course.py
```

Поля:

- `course_id`;
- `title`;
- `domain`;
- `credits`;
- `recommended_semester`;
- `description`;
- `topics`;
- `learning_outcomes`;
- `assessment_methods`;
- `cycle_component`;
- prerequisites через self-referential relationship.

### Project / ProjectVersion / LearningOutcome

Файл:

```text
backend\app\models\project.py
```

Project содержит:

- `title`;
- `domain1`;
- `domain2`;
- `goal`;
- `constraints_json`.

ProjectVersion содержит:

- `project_id`;
- `version_number`;
- `status`;
- `learning_outcomes`;
- `plans`.

LearningOutcome содержит:

- `lo_code`;
- `lo_text`;
- `taxonomy_level`;
- `weight`;
- `order_index`.

### Plan / PlanItem

Файл:

```text
backend\app\models\plan.py
```

Plan:

- `project_version_id`;
- `variant_type`: A/B/C;
- `metrics_json`;
- `is_active`.

PlanItem:

- `semester`;
- `course_id`;
- `bridge_module_id`;
- `credits`;
- `course_type`;
- `prerequisites_snapshot`.

### BridgeModule

Файл:

```text
backend\app\models\bridge_module.py
```

Bridge module — временный/кандидатный модуль, который может быть promoted to course.

Поля:

- `course_id`;
- `title`;
- `goal`;
- `description`;
- `credits`;
- `recommended_semester`;
- `learning_outcomes`;
- `topics`;
- `prerequisites`;
- `assessment_methods`;
- `source_chunks_json`;
- `generation_params_json`;
- `target_los`.

### AuditEvent

Файл:

```text
backend\app\models\audit.py
```

Нужен для auditability и expert-in-the-loop:

- promotion events;
- plan feedback;
- other events.

## 7. Важное исправление SQLAlchemy model registry

Файл:

```text
backend\app\models\__init__.py
```

Там импортируются все ORM-модели, чтобы SQLAlchemy мог разрешать строковые relationships вроде `"Plan"` независимо от порядка импортов.

Без этого раньше могли падать скрипты/тесты с ошибкой:

```text
InvalidRequestError: expression 'Plan' failed to locate a name
```

## 8. Embeddings

Файл:

```text
backend\app\kag\embedding_service.py
```

Сейчас sentence-transformers может быть не установлен. Тогда используется fallback:

```text
feature-hash-v2
```

Это deterministic feature hashing. Он лучше старого случайного/hash fallback, но для финальной демонстрации желательно поставить sentence-transformers:

```powershell
cd backend
.\venv\Scripts\activate
pip install sentence-transformers
```

Но важно: после смены embedding mode нужно reindex.

Endpoint статуса:

```text
GET /api/kag/system/status
```

В UI есть блок:

```text
Embedding mode
Mixed index detected
Reindex All
```

Если в базе смешаны разные model_version, нужно нажать Reindex All.

## 9. Indexing

Файл:

```text
backend\app\kag\indexing.py
```

Важные функции:

- `index_course(course, db)`;
- `index_all_courses(db)`.

`index_all_courses` должен:

- удалить/пересоздать chunks/embeddings;
- сохранить `model_version`;
- вернуть stats.

Promotion bridge module вызывает indexing нового курса.

## 10. Retrieval

Файл:

```text
backend\app\kag\retrieval.py
```

Есть:

- `retrieve_top_k_courses`;
- `retrieve_top_k_courses_hybrid`;
- `retrieve_similar_chunks`.

SQLite fallback:

- cosine similarity по embeddings;
- BM25-like lexical score;
- domain filter;
- graph expansion.

Важно: раньше там были hardcoded forensic keywords и битая кириллица. Это исправлялось на более domain-agnostic dynamic keyword extraction.

## 11. Scoring

Файл:

```text
backend\app\kag\scoring.py
```

Основная функция:

```python
compute_all_matches(project_version_id, db)
```

Она:

- берёт LOs проекта;
- делает hybrid retrieval;
- считает match score course ↔ LO;
- сохраняет MatchScore;
- считает probabilistic LO coverage:

```text
coverage = 1 - Π(1 - score_i)
```

Компоненты score:

- semantic similarity;
- keyword boost;
- domain alignment;
- text overlap fallback.

## 12. Gap detection

Файл:

```text
backend\app\kag\gap_detector.py
```

Считает LOs, где coverage ниже threshold:

```text
COVERAGE_THRESHOLD = 0.60 (порог главы T6 диссертации)
```

Возвращает:

- `gap_count`;
- `gap_percentage`;
- `gaps`;
- `threshold`.

## 13. Bridge generation

Файл:

```text
backend\app\kag\bridge_generator.py
```

Bridge modules должны появляться только если есть gaps. В UI кнопка Generate Bridge Modules активна при `gap_count > 0`.

Bridge module — это не сразу дисциплина учебного плана. Это рекомендация/кандидат.

Правильная логика:

```text
Coverage gap detected
→ Generate Bridge Module
→ Expert reviews it
→ Promote to Course
→ course repository grows
→ reindex embeddings
→ rebuild graph
→ regenerate curriculum variants
→ new plan can use promoted course
```

Важно: после Generate Bridge Modules план НЕ меняется автоматически.

## 14. Promote to Course

Файл:

```text
backend\app\kag\feedback.py
```

Endpoint:

```text
POST /api/kag/bridge/{bridge_module_id}/promote
```

Что делает:

- создаёт Course из BridgeModule;
- ставит domain `"interdisciplinary"` или forced domain;
- индексирует новый курс;
- rebuild knowledge graph;
- пишет AuditEvent;
- возвращает next step.

Сейчас backend возвращает:

```json
{
  "plan_changed": false,
  "requires_regeneration": true,
  "next_step": "Bridge module has been added to the course repository. Regenerate curriculum variants in Plan Builder to use it in the plan."
}
```

То есть Promote расширяет базу знаний, но не переписывает существующий план.

## 15. Knowledge Graph

Файл:

```text
backend\app\kag\knowledge_graph.py
```

Graph edges:

- prerequisite edges;
- similarity edges;
- LO coverage edges.

Endpoints:

```text
GET  /api/kag/graph/stats
POST /api/kag/graph/build
```

Build Graph:

- обновляет graph;
- улучшает retrieval/analysis;
- не меняет существующий план автоматически.

В UI теперь есть пояснение:

```text
Rebuild Graph updates retrieval knowledge only; it does not rewrite an existing plan.
```

## 16. Планировщик

Главный файл:

```text
backend\app\planner\scheduler.py
```

Главная функция:

```python
build_curriculum_plan(project_version_id, db, variant_type)
```

Варианты:

- A — maximize LO coverage;
- B — minimize new courses;
- C — minimize conflicts/balance.

Сейчас для проекта 6 A/B/C могут быть похожи, потому что constraints маленькие: 2 семестра / 60 ECTS / нужны bridge modules.

### 16.1 Credit logic

Нельзя требовать ровно 30 каждый семестр. Пользователь сказал:

```text
не прям ровно по 30, разброс может быть ±3
План может получиться больше 60, но не более 5
```

То есть:

```text
semester load = nominal ± 3
total credits = target .. target+5
```

Для проекта 6:

```text
target = 60
allowed total = 60..65
semester allowed = 27..33
```

### 16.2 Domain guard

Очень важное исправление:

Система не должна добирать кредиты чужими дисциплинами.

Для проекта 6 допустимы:

- Государственное управление;
- Информационные системы;
- bridge/interdisciplinary modules.

Недопустимы:

- Anatomy;
- Medicine;
- Electrical Engineering;
- unrelated core courses;
- unrelated Computer Science Engineering, если это не связано с доменом проекта или не bridge.

В `build_curriculum_plan` добавлен предохранитель перед сохранением:

```text
если schedule содержит course вне domain1/domain2,
raise ValueError и план не сохраняется
```

Это сделано, чтобы мусорный план не попал в БД даже при будущей ошибке selection logic.

### 16.3 Auto bridge modules

Если constraints не позволяют набрать нужные кредиты только domain courses из-за prerequisites/depth, система создаёт deterministic credit-gap bridge modules.

Функция:

```python
ensure_credit_bridge_modules(...)
```

Она создаёт модули вида:

```text
Bridge Module: Государственное управление + Информационные системы Integration 1
```

Это нужно, чтобы закрыть образовательный разрыв не чужими курсами, а междисциплинарными модулями.

## 17. Verifier

Файл:

```text
backend\app\planner\verifier.py
```

Проверяет:

- prerequisite violations;
- semester load violations;
- total credit violations;
- LO coverage;
- evidence count;
- redundancy;
- quality violations.

Возвращает:

```json
{
  "feasible": true,
  "quality_passed": true,
  "hard_violation_count": 0,
  "prerequisite_violations": [],
  "semester_load_violations": [],
  "credit_violations": [],
  "semester_loads": {"1": 30, "2": 30},
  "target_credits": 60,
  "total_credits": 60,
  "min_lo_coverage": 0.75,
  "average_lo_coverage": 0.756,
  "evidence_count": 9,
  "redundancy": 0.0
}
```

Важно: verifier теперь учитывает bridge modules как evidence по `target_los`.

Для bridge module coverage используется score около `0.75`, если LO входит в `target_los`. Это нужно, чтобы bridge modules реально закрывали пробелы в plan-based coverage.

## 18. International Quality Checklist

Добавлено 25 июня 2026.

Файл:

```text
backend\app\planner\international_quality.py
```

Цель: встроить зарубежный опыт curriculum quality assurance в систему.

Логика опирается на:

- Outcome-Based Education;
- ABET-style continuous improvement;
- CDIO integrated curriculum;
- Tuning competences;
- curriculum mapping;
- assessment alignment;
- expert-in-the-loop learning.

Функция:

```python
evaluate_international_quality(schedule, project_version, db, verification)
```

Чеклист:

1. Outcome-based curriculum mapping  
   Проверяет, все ли LOs достигли threshold.

2. Structured progression and prerequisite integrity  
   Проверяет hard violations.

3. Domain relevance control  
   Проверяет, что repository courses соответствуют доменам проекта.

4. Integrated interdisciplinary curriculum  
   Проверяет наличие bridge/interdisciplinary units.

5. Assessment alignment  
   Проверяет, есть ли assessment_methods у большинства learning units.

6. Continuous improvement and expert-in-the-loop learning  
   Проверяет bridge modules / promotion events.

Score:

```text
score = passed_checks / total_checks * 100
```

Для проекта 6 сейчас после генерации:

```text
International Quality = 83.3%
Passed = true
```

Один пункт может не проходить:

```text
Assessment alignment
```

Причина: не у всех дисциплин явно заполнены assessment methods.

Это хорошо для диссертации: система показывает не только “план готов”, но и конкретную рекомендацию для международной аккредитационной логики.

## 19. Plan metrics

Файл:

```text
backend\app\planner\scheduler.py
```

`calculate_plan_metrics` теперь возвращает:

```json
{
  "total_credits": 60,
  "target_credits": 60,
  "total_courses": 13,
  "num_bridge_modules": 4,
  "lo_coverage_percentage": 75.6,
  "min_lo_coverage": 0.75,
  "evidence_count": 9,
  "redundancy": 0.0,
  "prerequisite_violations": 0,
  "semester_load_violations": 0,
  "feasible": true,
  "international_quality": {...},
  "verification": {...}
}
```

## 20. Planner API

Файл:

```text
backend\app\api\planner.py
```

Endpoints:

```text
POST /api/planner/{project_version_id}/build
GET  /api/planner/{project_version_id}/variants
POST /api/planner/{plan_id}/toggle-active
GET  /api/planner/{project_version_id}/evaluation
```

Important:

`GET /variants` теперь возвращает только последние A/B/C, а не всю историю старых планов. Это было исправлено, потому что UI раньше показывал старые мусорные генерации.

## 21. Coverage API

Файл:

```text
backend\app\api\kag.py
```

Endpoint:

```text
GET /api/kag/{project_version_id}/coverage
```

Возвращает:

- raw KAG matches coverage;
- gaps;
- plan_coverage.

Очень важно:

Raw KAG coverage считает только repository course matches.  
Plan coverage считает текущий/последний план и учитывает bridge modules.

Именно поэтому раньше на dashboard мог быть 0%, хотя plan verifier показывал 75%. Это было исправлено.

Сейчас dashboard предпочитает `plan_coverage`, если он есть.

## 22. Frontend: Plan Builder

Файл:

```text
frontend\src\pages\PlanBuilder.jsx
```

Показывает:

- варианты A/B/C;
- расписание по семестрам;
- total credits;
- verification block;
- min LO coverage;
- evidence count;
- redundancy;
- International Quality Checklist.

После новых изменений в Plan Builder должен быть блок:

```text
International Quality Checklist
OBE / ABET-style continuous improvement / CDIO integrated curriculum / Tuning competences
Score: 83.3%
Checks:
✅ Outcome-based curriculum mapping
✅ Structured progression and prerequisite integrity
✅ Domain relevance control
✅ Integrated interdisciplinary curriculum
⚠️ Assessment alignment
✅ Continuous improvement and expert-in-the-loop learning
```

## 23. Frontend: LO Coverage Dashboard

Файл:

```text
frontend\src\pages\LOCoverageDashboard.jsx
```

Содержит:

- analytics summary;
- Knowledge Graph section;
- Bridge Module Suggestions;
- LO Achievability Analysis;
- LO list with priority sliders.

Сейчас добавлен постоянный блок:

```text
How this page affects the curriculum plan

1. Rebuild Graph updates retrieval knowledge only; it does not rewrite an existing plan.
2. Generate Bridge Modules creates recommendations for weak LOs; they are not courses yet.
3. Promote to Course adds a bridge module to the repository and rebuilds the knowledge base.
4. Regenerate Variants in Plan Builder is required for the new knowledge/course to appear in the curriculum plan.
```

После действий показываются workflow notices:

- Graph rebuilt → plan not changed, regenerate variants if needed.
- Bridge modules generated → recommendations only.
- Promote to Course → knowledge base updated, regenerate variants.
- Analyze with AI → diagnostic report only, does not change plan.

## 24. Export

Файл:

```text
backend\app\api\export_api.py
```

Excel export содержит sheets:

- Curriculum Plan;
- LO Coverage;
- Metrics;
- Verification;
- Knowledge Graph;
- Audit Log;
- International Quality.

Новый лист:

```text
International Quality
```

Содержит:

- framework score;
- passed;
- checks;
- evidence;
- recommendations.

## 25. Текущее состояние проекта 6

Последняя проверка после добавления international quality:

```text
A: 60 ECTS, feasible=true, international quality=83.3%
B: 60 ECTS, feasible=true, international quality=83.3%
C: 60 ECTS, feasible=true, international quality=83.3%
```

Ожидаемый состав плана:

```text
Introduction to Public Administration
Introduction to Information Systems
Bridge Module: Государственное управление + Информационные системы Integration 1
Bridge Module: Государственное управление + Информационные системы Integration 2
Bridge Module: Государственное управление + Информационные системы Integration 3
Bridge Module: Государственное управление + Информационные системы Integration 4
Ethics and Integrity in Public Administration
Leadership in Public Services
Public Policy Analysis
Database Management Systems
Introduction to Information Security
User Interface Design
Geographic Information Systems
```

Недопустимые курсы больше не должны появляться:

```text
Introduction to Human Anatomy
Introduction to Electrical Engineering
Medicine
Electrical Engineering
Global Health
unrelated core/math/engineering filler
```

## 26. Как быстро проверить проект 6 через API

PowerShell:

```powershell
$login = curl.exe -s -X POST http://127.0.0.1:3001/api/auth/login `
  -H "Content-Type: application/x-www-form-urlencoded" `
  --data "username=admin@curriculum-kag.local&password=admin123"

$token = ($login | ConvertFrom-Json).access_token
$h = "Authorization: Bearer $token"

$variants = curl.exe -s http://127.0.0.1:3001/api/planner/6/variants -H $h | ConvertFrom-Json

$variants | ForEach-Object {
  [pscustomobject]@{
    plan_id=$_.plan_id
    type=$_.variant_type
    total=$_.metrics.total_credits
    bridge=$_.metrics.num_bridge_modules
    feasible=$_.metrics.feasible
    quality=$_.metrics.verification.quality_passed
    min_lo=$_.metrics.min_lo_coverage
    avg=$_.metrics.lo_coverage_percentage
    iq=$_.metrics.international_quality.score
  }
} | Format-Table -AutoSize
```

Expected:

```text
total = 60
feasible = True
min_lo = 0.75
avg ≈ 75.6
international quality ≈ 83.3
```

## 27. Как пересгенерировать план проекта 6

```powershell
curl.exe -s -X POST http://127.0.0.1:3001/api/planner/6/build -H $h
```

После этого:

```powershell
curl.exe -s http://127.0.0.1:3001/api/planner/6/variants -H $h
```

## 28. Важные UX-объяснения

Пользователь спрашивал: “после кнопок что-то в плане меняется или надо заново сгенерировать?”

Правильный ответ:

```text
Rebuild Graph — не меняет план.
Generate Bridge Modules — не меняет план.
Analyze with AI — не меняет план.
Promote to Course — добавляет курс в репозиторий, но не меняет уже созданный план.
Чтобы план изменился, после Promote нужно открыть Plan Builder и нажать Generate Variants.
```

Это важно сохранить в UI и в объяснениях.

## 29. Что нужно улучшать дальше

### 29.1 Assessment alignment

International Quality Checklist показывает, что assessment alignment слабый.

Нужно:

- заполнить `assessment_methods` для всех курсов проекта;
- особенно для repository courses:
  - Introduction to Public Administration;
  - Introduction to Information Systems;
  - Ethics and Integrity;
  - Public Policy Analysis;
  - Database Management Systems;
  - Information Security;
  - User Interface Design;
  - Geographic Information Systems.

Можно сделать endpoint/скрипт:

```text
Fill missing assessment methods
```

Например:

```json
["case study", "project", "presentation", "exam", "portfolio"]
```

### 29.2 Настоящие SentenceTransformer embeddings

Сейчас может быть fallback:

```text
feature_hash_fallback
```

Для сильной демонстрации желательно:

```powershell
pip install sentence-transformers
```

Потом:

```text
Reindex All
Rebuild Graph
Generate Variants
```

### 29.3 Better bridge module UI

Bridge modules сейчас могут быть длинными. Хорошо добавить:

- before/after coverage;
- “why this module was generated”;
- target LO gap;
- evidence source chunks;
- button “Promote and Regenerate Plan”.

Сейчас Promote и Regenerate разделены. Можно сделать combined workflow:

```text
Promote to Course and Regenerate Variants
```

Но важно не делать это без ясного подтверждения, потому что это меняет план.

### 29.4 Course relevance explanation

Для каждой дисциплины в плане полезно показывать:

- why selected;
- matched LOs;
- score;
- domain relevance;
- prerequisites satisfied.

Это усилит explainability.

### 29.5 Graph visualization

Сейчас graph stats есть, но нет визуального графа.

Можно добавить:

- nodes: courses, LOs, domains;
- edges: prerequisite, similarity, LO coverage;
- filter by project;
- highlight bridge modules.

### 29.6 Audit trail

Уже есть AuditEvent. Нужно в UI показать:

- when graph rebuilt;
- when bridge generated;
- when bridge promoted;
- when plan regenerated;
- before/after courses, edges, coverage.

Для диссертации это важно как auditability.

## 30. Зарубежный опыт, который уже встроен

### ABET-style continuous improvement

Идея:

- outcomes должны быть измеримы;
- curriculum mapping должен показывать, где outcomes достигаются;
- должны быть evidence и continuous improvement loop.

В системе:

- LO coverage;
- evidence count;
- bridge generation;
- promote to course;
- audit log;
- International Quality Checklist.

### CDIO integrated curriculum

Идея:

- программа должна быть интегрированной;
- disciplines должны не жить отдельно, а связываться проектами/bridge modules.

В системе:

- bridge modules;
- interdisciplinary domain;
- integrated curriculum check.

### Tuning competences

Идея:

- learning outcomes и competences должны быть явно mapped;
- curriculum design должен быть outcome-based.

В системе:

- Project LOs;
- course ↔ LO MatchScore;
- coverage matrix;
- gap detector.

### Curriculum mapping best practice

Идея:

- каждому LO нужно evidence;
- gaps и redundancies должны быть видимы.

В системе:

- coverage_by_lo;
- evidence_count;
- redundancy;
- gap_count.

## 31. Важные источники, которые использовались

При добавлении International Quality Checklist были использованы/учтены:

- ABET accreditation criteria / continuous improvement;
- ABET performance indicators and curriculum mapping;
- CDIO standards, integrated curriculum;
- Tuning Educational Structures in Europe;
- university curriculum mapping guides.

Если нужно цитировать в статье, лучше заново открыть официальные страницы и взять точные формулировки/ссылки.

## 32. Известные особенности и осторожность

### 32.1 Browser cache

После изменения frontend надо делать:

```text
Ctrl+F5
```

Иначе браузер может показывать старый bundle.

### 32.2 Старые планы

Раньше в базе было много старых неправильных планов проекта 6. Большинство были удалены, но при новых тестах снова создаются новые Plan rows.

`GET /planner/6/variants` должен возвращать только последние A/B/C.

### 32.3 Multiple backend processes

Иногда на Windows оставались два uvicorn-процесса. Проверять:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { ($_.Name -like 'python*') -and ($_.CommandLine -like '*-m uvicorn app.main:app*') } |
  Select-Object ProcessId,CommandLine
```

Если нужно, остановить и запустить один.

### 32.4 Static server

Порт 3001 держит `.runtime\frontend_server.py`.

Если frontend не обновляется:

```powershell
Remove-Item .runtime\dist -Recurse -Force
Copy-Item frontend\dist .runtime\dist -Recurse
```

## 33. Минимальный quick-start для нового Codex-треда

1. Открыть:

```text
D:\curriculum-kag\curriculum-kag\CODEX_CONTEXT_RU.md
```

2. Проверить порты:

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object {$_.LocalPort -in 3001,8000} |
  Select-Object LocalPort,OwningProcess
```

3. Проверить health:

```powershell
curl.exe -s http://127.0.0.1:3001/api/health
```

4. Если frontend надо пересобрать:

```powershell
cd D:\curriculum-kag\curriculum-kag\frontend
npm run build
cd ..
Remove-Item .runtime\dist -Recurse -Force
Copy-Item frontend\dist .runtime\dist -Recurse
```

5. Если backend надо перезапустить:

```powershell
cd D:\curriculum-kag\curriculum-kag
backend\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

6. Открыть:

```text
http://localhost:3001/
```

7. Login:

```text
admin@curriculum-kag.local
admin123
```

## 34. Главный narrative для диссертации

Система реализует Curriculum-KAG prototype:

```text
Semantic vector index
+ Curriculum knowledge graph
+ Hybrid retrieval
+ Prerequisite closure
+ Constraint-aware scheduler
+ Strict verifier
+ Bridge module trigger
+ Expert promotion
+ Reindex/rebuild
+ International quality checklist
= explainable, auditable, accumulating curriculum design system
```

Cyber Investigator — case study, но система универсальна.  
“Цифровое государственное управление” показывает, что система уже может работать с другой программой и не должна быть hardcoded.

Главный научный акцент:

```text
Не RAG, а KAG.
Не просто генерация текста, а knowledge accumulation.
Не просто красивый план, а проверяемый curriculum pipeline.
```
