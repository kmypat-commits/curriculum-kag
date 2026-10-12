# Обратимая чистка — 11 октября 2026

Архив: `E:\Мусор\Curriculum-KAG-20261011-14acd02e`.
Журнал: `move-manifest.json` в этой папке, исходные и новые абсолютные пути,
SHA256 каждого файла, состояние `moved_verified`.

Перенесено13 объектов,264 файла,448138bytes:

- Пять вспомогательных обёрток: smoke-test.bat, acceptance-test.bat,
  backup-postgres.bat, test.bat, epvo_ai_status.bat.
- Восемь завершённых временных pytest-папок внутри visualizations:
  audit20261011, clinical-boundary, clinical-suite, content-v14-test,
  content-v15, content-v15-final, content-v16, lease-history (точные имена вmanifest).

PowerShell проверки/backup/test сохранены; start.bat/stop.bat сохранены.
Ссылка на архивированную smoke BAT-обёртку в RUN_MODES_RU.md заменена пояснением;
smoke-test.ps1 остаётся действующим.

Скрипт проверил отсутствие текущего pytest-процесса, принадлежность точных
путей проекту и архиву, отсутствие reparse points, checksum копий. Директории
удалялись из исходного места только после проверенного копирования; в архиве
данные сохранены. Итоговый exit0, все13 moved_verified.

Для возврата выбрать запись вmanifest и скопировать Destination обратно в
Source, только если исходный путь ещё отсутствует; при появившемся новом файле
сначала сравнить содержимое, не перезаписывать его автоматически.

Не тронуты: активный.runtime/dist, модели, PostgreSQL, резервные копии,
материалы генераций/исследований, исходные статьи, frozen manifest и его входы,
чужие изменения start.ps1 и защищённые/непрочитанные папкиtmp.

После чистки smoke-test.ps1 подтвердил healthy backend, connected PostgreSQL
и frontend proxy. Это availability check, не полная содержательная приёмка.
Новых генераций, смены паролей, Git push или публикации сайта не выполнялось.

Это первый безопасный проход по явным обёрткам и тестовому scratch, а не
освобождение всех18.4GiB runtime. Большие snapshots, backup и модели не мусор:
дальнейшее архивирование требует отдельной проверки назначения и восстановления.
