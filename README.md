# laim-kriteria-selector

Нода мониторингового контура LAIM: принимает эталонную корзину в формате
тестового датасета и контракт метрики от `laim-baskets-adapter` (либо, без
контракта, документы агента) и отдаёт в контур `metric_spec` — какая колонка
корзины является ключевой метрикой (КМ) и как она считается — и прошедший
проверку принадлежности агенту контракт `validated_monitoring_metric`.

## Зачем нода нужна

Потребители контура (конвертер трейсов, ассессор, тесты дрейфа и динамики
КМ) должны получать контракт метрики из одной точки и только после проверки,
что он относится к агенту, для которого запущен прогон. Селектор — эта точка:
identity-гейт между адаптером и остальным контуром.

- **Контракт адаптера — источник истины.** При подключённом
  `monitoring_metric` метрика уже определена и сверена с отчётом о валидации;
  селектор не пересчитывает её и не вызывает LLM, а передаёт насквозь.
- **Без контракта — код доказывает, LLM подсказывает.** Кандидаты в КМ
  выводятся из свойств данных корзины; формула и значение из отчёта о валидации
  принимаются только после воспроизведения пересчётом; модель вызывается, лишь
  когда доказательств нет, и её ответ проверяется по реальным колонкам.
- **Деградация вместо падения.** Неоднозначность или отсутствие разметки дают
  `status = not_computable` с `reason_code`; падение — только для технически
  непригодного входа.

## Место в контуре

```text
laim-baskets-adapter.reference_umr      ─► df
laim-baskets-adapter.monitoring_metric  ─► monitoring_metric
g-aiva-doc-browser.extracted_fields     ─► doc_browser_result
источник development_report             ─► development_report_artifact
источник validation_report              ─► validation_report_artifact
источник assessor_instruction           ─► assessor_instruction
источник selection                      ─► run_context
                                            │
                                   laim-kriteria-selector
                                            │
        validated_monitoring_metric ─► laim-traces-dataset-converter, laim-asessor-agent,
                                       laim-local-drift-test, laim-global-drift-test,
                                       laim-oos-oot-test, laim-km-dynamic-test
        metric_spec                 ─► laim-km-dynamic-test
        metric_dataset              ─► (в port_wiring.json не подключён)
```

## Порты и настройки

### Входы

| Порт | Обязателен | Что приходит с платформы |
|---|---|---|
| `df` | да | Корзина в формате тестового датасета: DataFrame, либо путь/каталог с `.parquet`/`.xlsx`/`.xls`/`.csv`/`.pkl`/`.pickle`, либо bytes pickle |
| `monitoring_metric` | нет | Контракт `laim-monitoring-metric.v2`: dict, JSON/pickle bytes или локальный файл (каталог с одним файлом) |
| `run_context` | нет | Selection manifest прогона; читаются ключи `agent_ci` (или `agent_id`), `distributive`, `model_version_id` |
| `validation_report_artifact` | нет | Полный DOCX отчёта о валидации; локальный путь (`getPortAsLocalPath`) |
| `development_report_artifact` | нет | Исходный DOCX отчёта о разработке (`{bin, ext}`); только для SHA-256 и проверки identity |
| `doc_browser_result` | нет | `extracted_fields` с блоком `bp_card_fields`: `evaluation_metric`, `threshold`, `metric_desc`, `metric_func`; текстовая карточка `bp_card` тоже принимается |
| `assessor_instruction` | нет | Инструкция ассессора: DOCX, pickle или dict с ключом `text`; локальный путь (`getPortAsLocalPath`) |

Транспорт артефактов отчётов распаковывается по содержимому: dict
`{bin, ext}`, raw bytes, локальный путь или каталог порта (служебные
`_SUCCESS`/`.crc` игнорируются), однострочный parquet-контейнер с bytes/path
внутри. DOCX и инструкция узнаются по сигнатуре (`PK\x03\x04` — DOCX, `\x80`
— pickle): платформа часто отдаёт файл без расширения. HDFS URI (`hdfs://`,
`viewfs://`, `/user/`) содержимым не считается — файл должен быть смонтирован
локально. Функция `main` принимает порты только по именам (`main(**kwargs)`).

### Выходы

| Порт | Тип | Контракт |
|---|---|---|
| `metric_spec` | default | `metric-spec.v2` на legacy-пути; passthrough-спека на пути с контрактом (см. «Форматы выхода») |
| `validated_monitoring_metric` | default | Входной `laim-monitoring-metric.v2` без изменений, прошедший identity-гейт; отсутствует, если контракт не подавался |
| `metric_dataset` | dataframe | Входная корзина; на legacy-пути при `majority_vote` дополнена колонкой `laim_key_metric` |

### Настройки

| Настройка | По умолчанию | Зачем менять |
|---|---|---|
| `model_id` | `minimax-m2.5` | Маршрут LLM legacy-пути: `minimax-m2.5` и `qwen3-coder-next` — AI Gateway, `giga` — GigaChat |
| `llm_model` | `GigaChat-3-Ultra` | Точное имя модели GigaChat; действует только при `model_id = giga` |
| `main_metric` | пусто | Явная колонка КМ; отключает passthrough и LLM, проверяется по схеме корзины |
| `model_version_id` | `0` | ID версии решения; добавляется к ожидаемой identity при сверке отчётов |

## Как проходит прогон

```text
1. Контракт      monitoring_metric распакован → basket_id сверен с run_context.agent_ci
2. Passthrough   MetricSpec из контракта, LLM и документы не читаются → выход
   (без контракта или при заданном main_metric — шаги 3-5)
3. Чтение        корзина, инструкция, поля doc-browser, отчёт о валидации; SHA-256
                 и сверка CI-кода/дистрибутива/ID версии из отчётов с run_context
4. Кандидаты     шкальные колонки корзины; формула отчёта о валидации
                 воспроизводится пересчётом; LLM — только если доказательств нет
5. MetricSpec    колонки перепроверены по корзине, сверка с отчётом, публикация
```

Путь с контрактом (реальный прогон, корзина диалоговая, метод `all_assessors`):

```text
INFO root: kriteria-selector: метрика взята из monitoring_metric (main='mark_1_metric', source=monitoring_metric), LLM и артефакты не используются
```

Результат этого прогона: `status = resolved`, `main_metric = mark_1_metric`,
`other_metrics = [mark_2_metric, mark_3_metric]`, `assessment_mode = dialogue`, `reported_validation_value = 0.93`.

`resolution_source` на пути с контрактом: `monitoring_metric` — критерии
контракта доступны в корзине, `score_column` — колонка с ролью `final_score`,
иначе первый источник; `monitoring_metric_judged_total` — метод `accuracy`
или контракт без колонок-источников, судится итоговая колонка `main_metric`
корзины; `monitoring_metric_not_computable` — контракт со статусом
`not_computable` (например, `official_baseline_missing`) уходит дальше тем же
отказом с его `reason_code`, итоговую колонку без объявленной КМ селектор не судит.

Legacy-путь (контракт не подключён); сводные строки без пары
`input_query`/`output_answer` в выборе не участвуют. Порядок решения: явная
настройка `main_metric` → формула отчёта о валидации (majority vote по
упомянутым в отчёте колонкам голосов либо готовая score-колонка), принятая
только если пересчёт воспроизводит опубликованное значение с точностью его
последнего знака → ответ LLM, совпавший с реальной колонкой → единственный
кандидат → свойства данных (единственная явно итоговая колонка вроде `Итог`;
колонка, построчно равная минимуму частных критериев; единственная шкальная
колонка) → `not_computable`. Предупреждение legacy-пути:

```text
WARNING root: Ответ модели 'взвешенная accuracy' не совпал с колонками; метрика 'Итог' определена по свойствам данных: единственная шкальная колонка с явным признаком итоговой оценки в имени: 'Итог'
```

## Форматы выхода и контракты

Единица наблюдения — строка корзины (`assessment_mode` контракта: `qa` —
запрос, `dialogue` — сессия); селектор её не переопределяет.

**Passthrough-спека** (путь с контрактом): `status`, `main_metric`,
`other_metrics`, `metric_name`, `score_column`, `source_columns`,
`marker_columns`, `row_aggregation` (`majority_vote` для метода `majority`,
иначе `identity`), `strategy = monitoring_metric_passthrough`,
`scoring_method`, `assessment_mode`, `weight_column`,
`reported_validation_value`, `resolution_source`; при отказе — `reason_code`,
`reason`. Полей `metric_spec_version`, `artifact_provenance`,
`validation_evidence`, `selector_inference` в ней нет: происхождение и сверка
зафиксированы в самом контракте `validated_monitoring_metric`.

**`metric-spec.v2`** (legacy-путь): те же поля плюс `metric_spec_version`,
`prediction_column`, `reference_column`, `score_value_type`, `scale_min`,
`scale_max`, `higher_is_better`, `business_threshold`, `metric_description`,
`metric_formula` (из `doc_browser_result`), `evidence`, `warnings`,
`validation_evidence` (`status`: `not_provided` | `confirmed` |
`contradiction` | `no_metric_observation`; `observations`, `computed_value`),
`artifact_provenance` (SHA-256 корзины, инструкции и отчётов, схема и число
строк корзины; `identity_status`: `not_provided` | `declared_unverified` |
`expected_only` | `verified` | `mismatch`), `selector_inference`
(`llm_called`, `configured_model_id`, `selection_path`). Значения:
`status` — `resolved` | `resolved_categorical` | `not_computable`;
`strategy` — `mean_score` | `weighted_accuracy` | `accuracy` |
`categorical_label`; `resolution_source` — `setting` | `validation_report` |
`llm` | `llm_categorical` | `single_numeric_candidate` | `data_properties` |
`not_computable`. При `not_computable` — ещё `reason_code`, `reason`,
`score_column = null`; `main_metric = target` — транспортное имя пустой
колонки, не КМ. Тексты артефактов в контракт не копируются — только хеши.

## Падение против деградации

Нода останавливается (исключение в лог платформы):

| Причина | Исключение |
|---|---|
| `monitoring_metric` подключён, но контракт не распознан | `ValueError` |
| `basket_id` контракта не равен `run_context.agent_ci` | `ValueError` («принадлежит другому агенту») |
| Отчёт о валидации подан, но не прочитан: битый DOCX, пустой контейнер, ненайденный путь, HDFS URI | `ArtifactTransportError` |
| Корзина или инструкция не загружаются: каталог без файла, неподдержанный тип, нечитаемый DOCX | `FileNotFoundError`, `TypeError`, `RuntimeError` |

Деградации (спека публикуется, корзина уходит дальше):

| Событие | Реакция |
|---|---|
| Контракт адаптера `not_computable` | `status = not_computable`, `reason_code` контракта |
| Отчёт принадлежит другому агенту (CI-код, дистрибутив, ID версии) | `not_computable`, `artifact_identity_mismatch`, LLM не вызывается, `ERROR` в логе |
| `main_metric` из настроек нет в корзине | `not_computable`, `explicit_metric_missing` |
| Несколько неразличимых числовых кандидатов | `not_computable`, `ambiguous_numeric_candidates` |
| Только категориальная разметка, ответ модели не совпал | `not_computable`, `categorical_metric_unresolved` |
| В корзине нет построчной разметки | `not_computable`, `no_markup_candidates`; LLM не вызывается |
| Формула не воспроизводит ни одно значение отчёта о валидации | `not_computable`, `validation_metric_not_reproduced`, `validation_evidence.status = contradiction` |
| Отчёт прочитан, но таблицы со столбцом «Значение» нет | `resolved`, `validation_evidence.status = no_metric_observation`, warning |
| Формула `majority_vote` не материализуется; LLM не ответила валидным JSON | `identity` / решение по свойствам данных, warning |
| Категориальная итоговая колонка | `resolved_categorical`, `strategy = categorical_label`; числовые тесты дают серый результат |
| Инструкция длиннее 30 000 символов | обрезана для промпта, warning |

## Внешние сервисы

LLM нужна только на legacy-пути и только когда детерминированных доказательств
нет; на пути с контрактом и при явном `main_metric` внешних вызовов нет.

- **AI Gateway** (`model_id` ≠ `giga`): `POST {AI_GATEWAY_URL}/api/v1/chat/completions`,
  таймаут 10 с на соединение и 300 с на ответ, `max_tokens = 8192`,
  `temperature = 0.1`, `top_p = 0.1`, `top_k = 1`; проверка TLS-сертификата
  отключена. Без `AI_GATEWAY_URL` вызов невозможен.
- **GigaChat** (`model_id = giga`): через `langchain-gigachat`; переменные
  окружения `config.py` (читаются также из `.env`): `MODEL`, `CREDENTIALS`,
  `AUTH_URL`, `BASE_URL`, `SCOPE`, `TEMPERATURE` (0.001), `TOP_P` (0.001),
  `VERIFY_SSL_CERTS`, `TIMEOUT`, `STREAMING`; заданный `AI_GATEWAY_URL`
  переключает `ModelsConfig` на контур `sds` с адресом `{AI_GATEWAY_URL}/api/v1`.
- **Ретраи**: 3 попытки, паузы 2 с и 4 с. После исчерпания нода не падает:
  метрика выбирается по свойствам данных или публикуется `not_computable`.
  Сэмплирование не строго детерминировано, но ответ модели всегда
  перепроверяется по реальным колонкам. HDFS и эмбеддинги нода не использует.

## Наблюдаемость

Лог платформы (root-логгер): распаковка транспорта, кандидаты в метрики и
причины их исключения, запрос/ответ AI Gateway (`request_id`, `finish_reason`,
`completion_tokens`), итоговая строка `kriteria-selector MetricSpec: status=...
score_column=... strategy=... source=... llm_called=...`. Отдельного порта
журнала нет: журнал прогона — сам `metric_spec` (`evidence`, `warnings`,
`validation_evidence`, `artifact_provenance`, `selector_inference`). Триаж на
сотне прогонов — по `metric_spec` без чтения логов: агрегируйте `status`,
`reason_code`, `resolution_source`, `validation_evidence.status`, `artifact_provenance.identity_status`.

## Карта кода

```text
descriptor.json                     порты, настройки, sourceFiles, py312-simple
main.py                             вся логика: транспорт DataArtifact, identity, кандидаты, сверка
                                    с отчётом о валидации, LLM-fallback, passthrough контракта
config.py                           ModelsConfig: маршрут GigaChat/AI Gateway из переменных окружения
tests/test_artifact_provenance.py   passthrough, identity-гейт, транспорт артефактов, деградации
```

## Что делать, если

- **Нода упала с «принадлежит другому агенту»** — в `monitoring_metric` подан
  контракт чужой корзины: `laim-baskets-adapter` и `selection` должны относиться к одному CI-коду.
- **`ArtifactTransportError: validation_report_artifact не прочитан`** — порт
  отдал не файл (HDFS URI, пустой каталог, битый DOCX): проверьте монтирование порта и документ.
- **`status = not_computable`** — читайте `reason_code` и `reason`; для
  `ambiguous_numeric_candidates` кандидаты перечислены в `evidence` — задайте `main_metric`.
- **LLM вызывается на корзине с очевидной итоговой колонкой** — колонка не
  прошла проверку шкалы (больше 6 значений или нецелые) либо заполнена меньше чем на 20 % строк.

## Деплой

База — `py312-simple`; синтаксис и stdlib новее Python 3.12 не используются.
`descriptor.json`: `sourceFiles = [main.py, config.py]`, `functionName = main`;
порты `assessor_instruction` и `validation_report_artifact` монтируются как
локальный путь (`getPortAsLocalPath`, закреплено тестом). Нода самодостаточна.
Зависимости `requirements.txt`: `pandas`, `pyarrow`, `numpy`, `langchain`,
`langchain-gigachat`, `langchain-core`, `langchain-community`, `python-docx`,
`requests`, `python-dotenv`. Тесты: `python3 -m pytest -q tests`.

## Глоссарий

- **Корзина** — эталонный набор запросов/ответов агента с оценками, на котором
  проходила первичная валидация; здесь — в формате тестового датасета.
- **КМ** — ключевая метрика качества агента, объявленная в отчёте о валидации.
- **Контракт метрики** — `laim-monitoring-metric.v2` от `laim-baskets-adapter`:
  метод расчёта, колонки-источники, baseline и сверка с отчётом.
- **Identity-гейт** — сверка `basket_id` контракта (или CI-кода, дистрибутива
  и ID версии из отчётов) с `run_context` прогона; **passthrough** —
  публикация контракта без изменений после гейта.
- **Шкальная колонка** — числовая колонка с целыми значениями и не более чем
  шестью различимыми уровнями: признак построчной разметки, а не веса.
- **Majority vote** — строгое большинство голосов разметчиков; материализуется
  в колонку `laim_key_metric`.
