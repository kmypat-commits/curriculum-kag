# Исправление состояния заданий — 22 октября 2026

Причина: launcher recovery обходил только активные PlanBuildStatus. Поэтому
исторический durable job оставался running после перехода текущего статуса
в timed_out; также восемь попыток у завершённых jobs сохраняли running.

Добавлен явный режим recover_interrupted_builds.py --expired-orphans-only
--snapshot PATH. Он блокирует записи на время транзакции, сохраняет активные
текущие статусы и попытки с действующей/неизвестной lease. Перед изменениями
создаётся эксклюзивный fsync snapshot. Просроченные попытки получают timed_out
и failure_code=lease_expired; исходы уже завершённых jobs сохраняются.
Импорт скрипта больше не загружает root .env в процесс тестов.

Применено к localhost:5433/curriculum_kag_shadow после проверки identity:
один running job и девять running attempts были историческими, lease истекли
8–14 сентября. Снимок: .runtime/expired-build-recovery-20261022.json.
Committed readback: девять попыток timed_out; один job running→timed_out;
восемь terminal job outcomes сохранены. Running jobs=0, running attempts=0,
courses=57392. Данные опубликованных планов не изменялись.

Аудит больше не повторяет baseline_missing из-за старой строки Loading weights
в stderr: структурированный отказ имеет приоритет над этим маркером.
Транзиентные инфраструктурные ошибки и timeout сохраняют прежнюю retry policy.

Фокусные проверки: 38 passed. Отдельные RED тесты воспроизвели пропущенный
terminal status, просроченную попытку у complete job и повтор baseline_missing.
Полный backend pytest: exit0, 100%, два opt-in skipped; deprecation warnings
зависимостей сохранены. Лог: .runtime/backend-fixes-20261022-tests-green.log.
Первый full запуск остановился из-за отсутствующего repo в PYTHONPATH; второй
выявил dotenv import side effect; после исправления полный запуск прошёл.

Текущая БД уже на 20261013_university_baselines. Подтверждённых revisions=0.
baseline_missing для B/C по-прежнему корректен без исходного вузовского плана;
архив EPVO не подставлялся в его качестве. Fresh20/40 не выполнялись, завершение
полной цели и предметная готовность каталога этим исправлением не подтверждаются.
