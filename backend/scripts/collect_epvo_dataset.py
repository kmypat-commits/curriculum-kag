"""Collect public educational-program records from the EPVO registry safely."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


BASE_URL = "https://epvo.kz"
LIST_ENDPOINT = "/api/epvo-app/external/rep/publication/applications"
DETAIL_ENDPOINT = "/api/epvo-app/external/rep/publication/application/{program_id}"


def default_filter(language_id: int) -> dict[str, Any]:
    return {
        "repView": 1, "appStatus": "", "appStatuses": [], "status": "APPROVED",
        "searchText": "", "eduType": "", "appType": "", "catoCode": 0,
        "universityId": 0, "professionType": 0, "degreeTypes": [], "studyLang": 0,
        "centerTrainingDirection": 0, "centerProfession": 0,
        "dateRegistrationFrom": None, "dateRegistrationTo": None,
        "dateUpdateFrom": None, "dateUpdateTo": None, "actual": True,
        "actualUpdated": False, "applicationOfHrTraining": 1,
        "universityStatus": "ACTIVE", "professionalStandards": [], "psEpId": 0,
        "distinctType": "", "accreditation": 0, "psId": None, "okedId": None,
        "profId": None, "onlineOvpo": None, "langId": language_id,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_program_id(record: dict[str, Any]) -> str | None:
    for key in ("id", "applicationId", "eduProgramId", "programId"):
        if record.get(key) not in (None, ""):
            return str(record[key])
    return None


def create_client(base_url: str, timeout: float) -> httpx.Client:
    return httpx.Client(
        base_url=base_url, timeout=timeout, follow_redirects=True,
        headers={
            "Accept": "application/json, text/plain, */*", "Accept-Language": "ru",
            "Referer": f"{base_url}/#/register/education_program",
            "User-Agent": "Curriculum-KAG research collector/1.0 (public EPVO data)",
            "X-Requested-With": "XMLHttpRequest",
        },
    )


def bootstrap_csrf(client: httpx.Client) -> None:
    client.get("/api/epvo-app/external/s/main/menu/section/list")
    token = client.cookies.get("XSRF-TOKEN")
    if not token:
        raise RuntimeError("ЕПВО не выдал защитный XSRF-токен")
    client.headers["X-XSRF-TOKEN"] = token


def explain_http_error(response: httpx.Response) -> RuntimeError:
    body = response.text.strip() if response.content else ""
    details = f" Ответ: {body[:500]}" if body else ""
    return RuntimeError(
        f"ЕПВО вернул HTTP {response.status_code}.{details} "
        "Публичный интерфейс ЕПВО сейчас тоже может быть неисправен. "
        "Повторите пробу позже; при постоянной ошибке запросите официальную выгрузку."
    )


def request_with_retries(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code < 500:
                return response
            last_error = explain_http_error(response)
        except httpx.TransportError as exc:
            last_error = exc
        if attempt < 4:
            pause = attempt * 5
            print(f"ЕПВО временно не ответил; повтор {attempt}/3 через {pause} с", file=sys.stderr)
            time.sleep(pause)
    raise RuntimeError(f"ЕПВО не ответил после повторных попыток: {last_error}")


def collect(args: argparse.Namespace) -> dict[str, Any]:
    output, pages, records = Path(args.output), [], []
    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    page_number = args.start_page
    if not args.restart:
        existing_pages = sorted(raw_dir.glob("page-*.json"))
        for page_path in existing_pages:
            try:
                data = json.loads(page_path.read_text(encoding="utf-8"))
                page_records = data.get("dtoList")
                if not isinstance(page_records, list):
                    raise ValueError("dtoList отсутствует")
                saved_page = int(page_path.stem.split("-")[-1])
            except (ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Повреждена сохранённая страница {page_path}: {exc}") from exc
            pages.append({"page": saved_page, "records": len(page_records),
                          "file": str(page_path), "sha256": sha256(page_path)})
            records.extend(page_records)
            page_number = max(page_number, saved_page + 1)
        if existing_pages:
            print(f"Продолжаю после страницы {page_number}; уже сохранено {len(records)} записей")
    with create_client(args.base_url.rstrip("/"), args.timeout) as client:
        bootstrap_csrf(client)
        newly_collected = 0
        while not args.details_only and (args.max_pages is None or newly_collected < args.max_pages):
            payload = {
                "size": args.page_size, "totalElements": 0, "totalPages": 0,
                "pageNumber": page_number, "filter": default_filter(args.language_id),
            }
            response = request_with_retries(client, "POST", args.list_endpoint, json=payload)
            if response.status_code >= 400:
                raise explain_http_error(response)
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError("ЕПВО вернул не JSON; данные не сохранены") from exc
            page_records = data.get("dtoList") if isinstance(data, dict) else None
            if not isinstance(page_records, list):
                raise RuntimeError("Формат ответа ЕПВО изменился: поле dtoList не найдено")
            page_path = raw_dir / f"page-{page_number:06d}.json"
            write_json(page_path, data)
            pages.append({"page": page_number, "records": len(page_records),
                          "file": str(page_path), "sha256": sha256(page_path)})
            records.extend(page_records)
            newly_collected += 1
            total = int(data.get("totalElements") or len(records))
            print(f"Страница {page_number + 1}: {len(page_records)} записей; всего {total}")
            if not page_records or len(records) >= total:
                break
            page_number += 1
            time.sleep(max(args.delay, 1.0))

        if args.details:
            detail_dir = raw_dir / "details"
            downloaded_details = 0
            for index, record in enumerate(records, 1):
                program_id = get_program_id(record)
                if not program_id:
                    continue
                detail_path = detail_dir / f"{program_id}.json"
                if detail_path.exists() and not args.overwrite:
                    continue
                if args.details_limit and downloaded_details >= args.details_limit:
                    break
                response = request_with_retries(
                    client, "GET", args.detail_endpoint.format(program_id=program_id)
                )
                if response.status_code >= 400:
                    print(f"Предупреждение: карточка {program_id}: HTTP {response.status_code}", file=sys.stderr)
                    continue
                write_json(detail_path, response.json())
                downloaded_details += 1
                if index < len(records):
                    time.sleep(max(args.delay, 1.0))

    list_path = output / "program-list.jsonl"
    with list_path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    detail_count = len(list((raw_dir / "details").glob("*.json"))) if (raw_dir / "details").exists() else 0
    list_complete = bool(pages and pages[-1]["records"] < args.page_size)
    manifest = {
        "source": f"{args.base_url}/#/register/education_program",
        "endpoint_observed_in_public_ui": args.list_endpoint,
        "snapshot_date": datetime.now(timezone.utc).isoformat(),
        "license_or_permission": args.permission,
        "scope": "public educational-program registry; no personal data",
        "status": "complete_snapshot" if list_complete else "sample",
        "records": len(records), "pages": pages, "program_list": str(list_path),
        "detail_records": detail_count,
        "program_list_sha256": sha256(list_path),
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Безопасная выгрузка публичного Реестра ОП ЕПВО")
    parser.add_argument("--output", default="experiment-results/epvo-snapshot")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--list-endpoint", default=LIST_ENDPOINT)
    parser.add_argument("--detail-endpoint", default=DETAIL_ENDPOINT)
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--start-page", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=1,
                        help="Одна пробная страница; для полной выгрузки укажите 0")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--language-id", type=int, default=1)
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--details-only", action="store_true",
                        help="Не обновлять список, только продолжить загрузку карточек")
    parser.add_argument("--details-limit", type=int, default=0,
                        help="Максимум новых карточек за запуск; 0 — без ограничения")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--restart", action="store_true",
                        help="Начать список заново вместо продолжения сохранённой выгрузки")
    parser.add_argument("--permission", default="permission_pending")
    args = parser.parse_args()
    if args.details_only:
        args.details = True
    if args.max_pages == 0:
        args.max_pages = None
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size должен быть от 1 до 100")
    if args.delay < 1:
        parser.error("--delay не может быть меньше 1 секунды")
    return args


def main() -> None:
    try:
        manifest = collect(parse_args())
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
