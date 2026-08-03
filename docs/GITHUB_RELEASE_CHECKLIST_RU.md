# Публикация Curriculum-KAG на GitHub

## Текущее состояние

- Remote: `https://github.com/kmypat-commits/curriculum-kag.git`
- Ветка: `master`
- Рабочее дерево: чистое
- Обычные Git-объекты: около 17 МБ
- Модели, базы и experiment-results исключены через `.gitignore`.
- `backend/data/course_translations.json` хранится как LFS-placeholder `{}`; актуальные переводы находятся в PostgreSQL.

## Перед первым push

Проверить авторизацию:

```powershell
gh auth login -h github.com
gh auth status
git lfs install
```

Затем проверить локально:

```powershell
git status
git lfs status
powershell -ExecutionPolicy Bypass -File .\test.ps1
cd frontend; npm.cmd run build; cd ..
```

## Публикация

```powershell
git push -u origin master
git lfs push --all origin master
```

После push проверить репозиторий в браузере и убедиться, что в нём нет `.env`, SQLite/PostgreSQL dumps, моделей и `experiment-results`.

## Восстановление legacy-переводов

Оно не требуется для рабочего PostgreSQL-контура. Если нужен старый fallback, сначала восстановить LFS-объект по инструкции в `docs/LEGACY_TRANSLATIONS_RU.md`, затем включить `LEGACY_TRANSLATIONS_FALLBACK=true` только локально.
