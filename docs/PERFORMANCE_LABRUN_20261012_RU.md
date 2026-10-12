# Измерения текущей последовательной серии

Источник: system-20-labreview-20261012.json, первые11завершённых A, текущий код local-content-1.6, frozenoffset0. Среднее elapsed63.25сек, min28.52/max91.62, сумма695.70сек. Это время отдельного CLIкейса, не HTTP latency и не end-to-end пользовательской очереди.

3600/среднее≈56.9кейса/час — арифметическая экстраполяция, **не измеренная пропускная способность под нагрузкой**. Не использовать в обещаниях эксплуатации. Полная серия ещё running. Отдельные кейсы работают в новых процессах; warmedUIконтроли~8сек несопоставимы с этой серией.

Память: были мгновенные free792MiB и затем~2515MiB; не определены peak private bytes/commit, OOMlimit и concurrencylimit. Параллельный frontend test запуск получил nativeOOM, последовательный59tests прошёл. Не добавлять тяжёлую конкуренцию в текущую acceptanceсерию.

Стоимость генерации не измерена: нужны наблюдаемые CPUseconds, peakRSS/commit, энергия/платформа и конкретный тариф размещения. Для локального оценщика не добавлять выдуманную цену/tokencost. После20/contentприёмки провести изолированный повтор одинаковых задач с очередью1/2/4пользователя, собрать arrival→claim→publication время, successful/failed/cancelled, сохранность прежних планов, лимит тяжёлых процессов и фактическую память. Измерять throughput по интервалу полной партии, не 3600/одинбыстрыйкейс. Нынешние числа не закрывают пункт4цели.
# Проверкаохватаслота

Readonlyпоиск `generation_slot|CapacityBusy` во всёмbackend/app+backend/scripts подтверждает единственногоconsumer:api/kag.py,_capacity_checked_matches; триAPIcallsite используютего. Сам generation_capacity.py держитconnection-ownedPGadvisorylock до окончанияsyncscope и освобождаетегоfinally; повторныйsame-thread/same-engineвходreentrant. В scripts/audit_cross_level_generation.py compute_all_matches вызывается напрямую(около343), безgeneration_slot. Worker/buildконтур не обнаруженсредиconsumerэтогослота. Следовательно наличиеhelperне доказываетglobalone-heavy-limit, а APIscoringguardне защищаетCLIотодновременногоживогоworker. Переднагрузочнымтестом нуженединыйownershipscope доmodel/scoring/build спонятнойочередью/CapacityBusy ивосстановлениемприкраше. Изменениеэтойграницысейчасне выполнялось: текущий20v1.7running.
