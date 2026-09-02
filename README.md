# LAIM Kriteria Selector

Единственная точка семантического выбора ключевой метрики в измерительной
ветке LAIM. Модуль сопоставляет бизнес-метрику из отчёта о разработке и
инструкции и полного отчёта о валидации с фактическими столбцами эталонной
корзины и возвращает проверяемый `metric-spec.v2`.

Selector не принимает опубликованное число на веру: он пересчитывает
кандидатную формулу на корзине и сверяет результат с точностью таблицы
validation report. Для готовой оценки выходной `metric_dataset` равен входной
корзине. Для вычисляемой оценки (сейчас поддержан строгий `majority_vote`) в
него добавляется валидная для downstream колонка `laim_key_metric`.
`laim-baseline-extractor`, assessor и диагностические тесты должны получать
именно этот датасет, а не параллельную прямую связь от коннектора.

Выход содержит:

- `metric_name` — семантическое имя, например `Accuracy`;
- `score_column` / legacy `main_metric` — реальная колонка, например `Итог`;
- `source_columns` и `row_aggregation` — происхождение построчной оценки;
- `strategy`, `weight_column`, шкалу и направление улучшения;
- `reported_validation_value` и `validation_evidence` со статусом пересчёта;
- `business_threshold` отдельно от измеренного значения;
- `status`, `resolution_source`, evidence/warnings без chain-of-thought;
- `selector_inference`: вызывался ли LLM фактически, какой route был настроен
  и каким путём получено решение. Наличие `configured_model_id` само по себе
  не означает inference-вызов;
- `artifact_provenance` с SHA-256 полного содержимого корзины, инструкции и
  отчёта, а также схемой/числом строк корзины. Текст артефактов в контракт не
  копируется; хеш считается до ограничения размера LLM-промпта.

Хеши обеспечивают воспроизводимость содержимого, но не доказывают
принадлежность артефакта агенту. Пока upstream не передаёт проверяемые
`agent/version/distributive`, selector явно возвращает
`identity_status=not_provided` либо `declared_unverified`, а не угадывает
идентичность по имени файла.

Каждая колонка проверяется по DataFrame. При нескольких неразличимых
кандидатах либо при полном отсутствии построчной разметки модуль не выбирает
первый и не прерывает невозобновляемую автовалидацию: возвращает
`status=not_computable`, `score_column=null` и явную причину. Legacy-поле
`main_metric=target` в таком ответе — только транспортное имя пустой колонки,
а не измеренная КМ. Корзины с явной категориальной итоговой оценкой можно
использовать для калибровки assessor; числовые тесты по ним остаются серыми.

Если подключён порт `monitoring_metric` (контракт `laim-monitoring-metric.v2`
от `laim-baskets-adapter`), селектор работает как identity-гейт: сверяет
`basket_id` с `run_context.agent_ci`, строит MetricSpec из контракта без LLM
(`strategy=monitoring_metric_passthrough`) и публикует контракт в порт
`validated_monitoring_metric` без изменений. Контракт со статусом
`not_computable` (например, `official_baseline_missing`) уходит дальше таким
же отказом: `metric_spec.status=not_computable` с `reason_code` контракта,
`score_column=null`; судить итоговую колонку без объявленной КМ селектор не
пытается.

Сводные строки Excel без пары `input_query`/`output_answer` не участвуют в
выборе построчной шкалы и не становятся дополнительным классом. Среди
доказанных шкальных колонок единственная явно итоговая колонка (`Итог`,
`Итоговая оценка`, `final_mark`) выбирается детерминированно; поэтому такие
корзины, как CI09840670, не зависят от доступности LLM-селектора. Если отчёт
явно говорит, что итоговая метка — мнение большинства, selector не доверяет
готовой финальной колонке: он находит упомянутые в отчёте колонки голосов,
требует строгого большинства, выбирает вес только при единственном совпадении
с опубликованным weighted-значением и материализует проверенную оценку.

## Установка

```bash
pip install -r requirements.txt
```

## Использование

```python
from main import main
import pandas as pd

# Загрузка данных
df = pd.read_csv("data/dataset.csv", sep=";")

# Вызов модуля
result = main(
    df=df,
    docx_intstruction="./instruction/",
    doc_browser_result={"bp_card_fields": {
        "evaluation_metric": "Accuracy", "threshold": "0.8"
    }},
    run_context={"agent_ci": "CI09840670", "distributive": "D-01.004.02-604"},
    development_report_artifact={"bin": raw_docx_bytes, "ext": ".docx"},
    validation_report_artifact={"bin": raw_validation_docx, "ext": ".docx"},
    model_version_id=342293,
    model_id="minimax-m2.5"
)

print(result)
```

Обязательная разводка измерительной ветки:

```text
TRAIN -> basket_connector.input_df
basket_connector.output_data -> criteria_selector.df
VALIDATION_REPORT -> criteria_selector.validation_report_artifact
criteria_selector.metric_dataset -> baseline_extractor.test_basket
criteria_selector.metric_dataset -> assessor.rag_dataset
criteria_selector.metric_dataset -> local/global/oos.real_asessor_df
```

## Компоненты

### main.py

Основной модуль с функциями:
- `read_docx()` — чтение docx файла с инструкцией по разметке
- `make_giga_request()` — запрос к GigaChat
- `make_sds_request()` — запрос к SDS моделям через AI Gateway
- `main()` — основная функция модуля

### config.py

Конфигурация модели LLM. Содержит класс `ModelsConfig` для настройки параметров подключения к LLM. Поддерживает два контура:
- **sigma** — прямое подключение к GigaChat
- **sds** — подключение через AI Gateway

### run.py

Пример использования модуля с тестовыми данными.

## Конфигурация

Модуль использует переменные окружения из `.env` файла:
- `MODEL` — название модели
- `CREDENTIALS` — учётные данные
- `AUTH_URL` — URL аутентификации
- `BASE_URL` — базовый URL API
- `SCOPE` — область видимости
- `AI_GATEWAY_URL` — URL AI Gateway (для SDS контура)

## Поддерживаемые модели

- `minimax-m2.5` — AI Gateway, значение по умолчанию;
- `giga` — GigaChat;
- `qwen3-coder-next` — AI Gateway.

Для `doc_browser_result` предпочтителен порт `extracted_fields`: актуальный
g-aiva-doc-browser уже извлекает `evaluation_metric`, `threshold`,
`metric_desc`, `metric_func` в `bp_card_fields`. Прежний
`all_results.bp_card` также поддержан как текстовый fallback.

Отдельный `development_report_artifact` получает исходный `report_dict`
коннектора. Его текст не дублируется в MetricSpec и не заменяет
структурированные поля doc-browser: исходный DOCX нужен для точного SHA-256 и
детерминированной сверки явно записанных `CI...`, ID версии и дистрибутива с
`run_context` и Common Setting `model_version_id`. Доказанное несовпадение останавливает измерительную ветку до
LLM со статусом `not_computable`.

`validation_report_artifact` — отдельный полный DataArtifact. В SberDS он
может прийти как raw bytes, локальный путь/каталог без расширения либо как
однострочный parquet-контейнер с bytes/path исходного файла. Selector сначала
распаковывает транспорт по сигнатуре содержимого и только затем читает DOCX;
HDFS URI сам по себе не считается содержимым — платформа должна смонтировать
его в локальный файл порта. Текст отчёта не становится готовым ответом для
workflow: наружу уходят только извлечённые наблюдения, формула, SHA-256 и
результат воспроизведения. Отсутствующий отчёт сохраняет legacy fallback.
Поданный, но технически непрочитанный отчёт останавливает ноду с явной ошибкой
`ArtifactTransportError`; семантическое противоречие корректно прочитанного
отчёта и корзины даёт `not_computable`.
