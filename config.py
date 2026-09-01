"""
Конфигурация модели LLM для модуля LAIM kriteria selector.

Содержит класс ModelsConfig для настройки параметров подключения к LLM.
Поддерживает два контура: sigma (прямое подключение к GigaChat) и sds (через AI Gateway).

Имя модели выбирается в порядке: явный аргумент (настройка узла) →
переменная окружения MODEL → дефолт модуля. Дефолт — GigaChat-3-Ultra:
интерпретация инструкции разметки и сопоставление метрики с колонками —
задача на понимание длинного документа, и старшая модель ошибается в ней
заметно реже базовой.
"""

import os

from dotenv import load_dotenv

# Модель по умолчанию, когда её не задали ни настройкой узла, ни окружением.
DEFAULT_GIGACHAT_MODEL = "GigaChat-3-Ultra"


class ModelsConfig:
    def __init__(self, model: str = ""):
        load_dotenv()
        model = str(model).strip() or os.environ.get("MODEL") or DEFAULT_GIGACHAT_MODEL
        credentials = os.environ.get("CREDENTIALS")
        auth_url = os.environ.get("AUTH_URL")
        base_url = os.environ.get("BASE_URL")
        scope = os.environ.get("SCOPE")
        temperature = float(os.environ.get("TEMPERATURE", 0.001))
        top_p = float(os.environ.get("TOP_P", 0.001))
        verify_ssl_certs = (
            True if os.environ.get("VERIFY_SSL_CERTS") == "True" else False
        )
        timeout = os.environ.get("TIMEOUT")
        streaming = True if os.environ.get("STREAMING") == "True" else False

        AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL", None)
        if AI_GATEWAY_URL is not None:
            self.contour = "sds"
            base_url = AI_GATEWAY_URL + "/api/v1"
        else:
            self.contour = "sigma"

        self.shared_config = {
            "base_url": base_url,
        }

        self.contour_configs = {
            "sigma": {
                "auth_url": auth_url,
                "credentials": credentials,
                "verify_ssl_certs": verify_ssl_certs,
                "scope": scope,
            }
            | self.shared_config,
            "sds": self.shared_config,
        }[self.contour]

        self.llm_params = {
            "temperature": temperature,
            "model": model,
            "top_p": top_p,
            "timeout": timeout,
            "streaming": streaming,
        }
        self.contour_llm_configs = self.llm_params | self.contour_configs
