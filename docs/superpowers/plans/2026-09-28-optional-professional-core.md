# Optional Professional Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Необязательная настройка профильных блоков и обязательных дисциплин, выключенная по умолчанию.

**Architecture:** Один типизированный контракт в constraints и frozen snapshot. Существующие frontier, MILP и публикация используют одинаковые требования; UI не вводит второй редактор программы.

**Tech Stack:** Python, Pydantic, FastAPI, существующий MILP, React, pytest, Vitest.

**Spec:** docs/superpowers/specs/2026-09-28-professional-core-design.md; уточнение пользователя: весь режим opt-in.

## Global Constraints

- Без включения режима подбор и технические gates не меняются.
- При включении suggested/preferred не становится required автоматически.
- ГОСО, LO-evidence, scope, нагрузка и prerequisite сохраняются.
- Допуск 240–244 только target240/8; остальные exact.
- Не изменять статью, frozen manifest или дополнительные legacy edges.
- Git: коммитить проверенные относящиеся к задаче файлы; output/tmp/секреты не включать. Существующие незакоммиченные изменения отдельно инвентаризировать.

## Review Focus

1. Выключенный режим с сохранёнными требованиями не применяет их к build.
2. Чужая подпись/версия не считается подтверждением.
3. Изменённый контент аннулирует подтверждение в новом запросе, но не старом snapshot.
4. Обязательный курс не исчезает из top-N; невозможная цепочка диагностируется.
5. Fixed-курс и курс нескольких блоков не удваивает общий кредит.

## Task 1: Контракт и freeze

**Files:** create backend/app/schemas/curriculum_requirements.py; modify backend/app/api/projects.py, backend/app/services/program_spec_snapshot.py; test backend/tests/test_curriculum_requirements.py.

**Interfaces:** `CurriculumRequirements` с enabled=False, schema_version=1, required_course_ids, core_blocks; сервер формирует confirmation, клиент не назначает author/status.

- [ ] Написать RED для default/disabled, max30/max12, неизвестных ID, чужой версии и stale evidence.
- [ ] Проверить RED: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_requirements.py -q`.
- [ ] Реализовать схему и сохранение через существующий version flow; требования включить в frozen hash.
- [ ] Проверить GREEN и неизменность frozen retry.

```python
def test_optional_requirements_default_off():
    from app.schemas.curriculum_requirements import CurriculumRequirements
    assert CurriculumRequirements().enabled is False
```

## Task 2: Preflight, frontier, solver и итоговая проверка

**Files:** modify backend/app/planner/joint_contract.py, joint_frontier.py, joint_solver.py, joint_planner.py, final_schedule_checks.py; create backend/app/planner/core_requirements.py; tests backend/tests/test_core_requirements.py and test_joint_solver.py.

**Interfaces:** immutable block DTO; shared coverage evaluator возвращает covered/gap/unconfirmed, selected IDs, supported credits, reasons. Только enabled требования передаются в PlanningProblem.

- [ ] RED: обязательный низкорейтинговый курс против общего высокорейтингового; required block без покрытия; equivalent conflict; fixed credit count; disabled baseline.
- [ ] Сохранить обязательные seeds и prerequisite closure до ограничения frontier.
- [ ] Добавить x=1 и block minima; preferred coverage двухпроходным objective в прежнем общем бюджете.
- [ ] Проверять required повторно на финальной границе; preferred gap предупреждать, старый план сохранять при отказе.
- [ ] GREEN: целевые tests плюс полный backend suite.

```python
def test_disabled_requirements_have_no_effect():
    from app.planner.core_requirements import effective_requirements
    assert effective_requirements({"enabled": False, "required_course_ids": [1]}) is None
```

## Task 3: Opt-in интерфейс и объяснение

**Files:** modify frontend/src/pages/PlanBuilder.jsx; create frontend/src/components/CurriculumRequirements.jsx and tests; modify существующий экспорт backend/app/services/plan_pdf_export.py после проверки фактического расположения через rg.

**Interfaces:** общий constraints API; секция «Учитывать профильные блоки и обязательные дисциплины» выключена по умолчанию. Источники и подтверждения читаются из frozen результата.

- [ ] RED UI: выключенный режим, включение/сохранение/reload, preferred/required, конфликт и сохранение старого плана.
- [ ] Добавить компактный редактор реальных курсов/блоков и объяснение покрытия; не вызывать LLM на каждое изменение.
- [ ] Системные предложения из цели/РО помечать suggested; без источников не выдавать confirmed соответствия.
- [ ] Проверить frontend suite/build и экспорт warnings/coverage из snapshot.

```javascript
test('optional profile starts disabled', () => {
  render(<CurriculumRequirements value={{enabled: false}} onChange={() => {}} />);
  expect(screen.getByRole('checkbox', {name: /Учитывать профильные/})).not.toBeChecked();
});
```

## Task 4: Проверка и GitHub

**Files:** docs/METHODIST_APPLICABILITY_PLAN_20260927.md, тестовые overlay reports вне Git.

- [ ] Проверить историю/филологию/метрологию/Web/деревообработку/IT-медицину; enabled inputs хранить отдельным overlay hash, не подменять baseline.
- [ ] Замерить время preflight/frontier/solver; не обещать ускорение без измерений.
- [ ] Выполнить полные backend/frontend tests, build и git diff --check; осмотреть пользовательский сценарий.
- [ ] Инвентаризировать предыдущие исправления, исключить runtime/output/tmp и секреты из staging.
- [ ] Коммитить отдельными логическими изменениями, push в проверенный origin https://github.com/kmypat-commits/curriculum-kag.git; сообщить фактические SHA и результат push.

## Execution gate

Пользователь согласовал письменный дизайн и выполнение самим агентом. Перед кодом требуется проверка этого плана согласно writing-plans. После подтверждения выполнять последовательно без повторного согласования отдельных уже описанных шагов.
