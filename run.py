"""
Пример использования модуля LAIM kriteria selector.

Демонстрирует вызов функции main() с тестовыми данными:
- Датасет из CSV файла
- Путь к инструкции по разметке
- Модель для анализа
"""

import pandas as pd

from main import main

input_df = pd.read_csv(
    "data/Тестовая корзина StrategyBuilder [размеченная] v1.csv", sep=";"
)
docx_instruction_path = "./instruction/"
res = main(
    df=input_df,
    docx_intstruction=docx_instruction_path,
    doc_browser_result={"bp_card": "Основная метрика target"},
    model_id="giga",
)
print(res)
