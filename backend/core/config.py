"""
core/config.py — Carga y valida la configuración del sistema.
Lee config.yaml y expone un objeto Settings tipado.
Nunca hay valores hardcodeados en el código — todo viene de aquí.
"""

import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field


# ── Modelos de configuración ──────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = "claude"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1000
    temperature: float = 0.3
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    ollama_url: str = "http://localhost:11434"


class OpcUaConfig(BaseModel):
    enabled: bool = False
    url: str = "opc.tcp://localhost:4840"
    polling_interval_seconds: int = 5
    username: Optional[str] = None
    password: Optional[str] = None


class ModbusConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 502
    slave_id: int = 1
    polling_interval_seconds: int = 5
    registers: str = "0-49"


class MqttConfig(BaseModel):
    enabled: bool = False
    broker: str = "localhost"
    port: int = 1883
    topics: list[str] = ["factory/#"]


class CsvConfig(BaseModel):
    enabled: bool = True
    path: str = "simulator/data/"
    polling_interval_seconds: int = 5


class DataSourcesConfig(BaseModel):
    opcua: OpcUaConfig = OpcUaConfig()
    modbus: ModbusConfig = ModbusConfig()
    mqtt: MqttConfig = MqttConfig()
    csv: CsvConfig = CsvConfig()


class StorageConfig(BaseModel):
    sqlite_path: str = "data/copilot.db"
    duckdb_path: str = "data/analytics.duckdb"
    chromadb_path: str = "data/chromadb/"
    knowledge_graph_path: str = "data/process_graph.json"


class ObserverConfig(BaseModel):
    polling_interval_seconds: int = 5
    anomaly_threshold: float = 0.7
    zscore_window_minutes: int = 60


class EscalationConfig(BaseModel):
    min_confidence_for_llm: float = 0.6
    max_llm_calls_per_hour: int = 100


class SafetyConfig(BaseModel):
    require_human_approval: bool = True
    max_temperature_delta: float = 20.0
    max_rpm_delta_percent: float = 30.0


class PlantConfig(BaseModel):
    name: str = "Planta Principal"
    sector: str = "general"
    language: str = "es"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False


class Settings(BaseModel):
    llm: LLMConfig = LLMConfig()
    data_sources: DataSourcesConfig = DataSourcesConfig()
    storage: StorageConfig = StorageConfig()
    observer: ObserverConfig = ObserverConfig()
    escalation: EscalationConfig = EscalationConfig()
    safety: SafetyConfig = SafetyConfig()
    plant: PlantConfig = PlantConfig()
    server: ServerConfig = ServerConfig()


# ── Loader ────────────────────────────────────────────────────────────────────

def load_settings(config_path: Optional[str] = None) -> Settings:
    """
    Carga configuración en este orden de prioridad:
    1. Variables de entorno (ANTHROPIC_API_KEY, etc.)
    2. config.yaml en la raíz del proyecto
    3. Valores por defecto de los modelos Pydantic

    Uso:
        from backend.core.config import get_settings
        cfg = get_settings()
        print(cfg.llm.provider)
    """
    # Buscar config.yaml
    if config_path is None:
        candidates = [
            Path("config.yaml"),
            Path("../config.yaml"),
            Path(__file__).parent.parent.parent / "config.yaml",
        ]
        config_path = next((str(p) for p in candidates if p.exists()), None)

    raw: dict = {}
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        print(f"[config] Cargado desde {config_path}")
    else:
        print("[config] No se encontró config.yaml — usando valores por defecto")

    settings = Settings(**raw)

    # Variables de entorno tienen máxima prioridad
    if key := os.getenv("ANTHROPIC_API_KEY"):
        settings.llm.anthropic_api_key = key
    if key := os.getenv("OPENAI_API_KEY"):
        settings.llm.openai_api_key = key
    if key := os.getenv("GEMINI_API_KEY"):
        settings.llm.gemini_api_key = key

    return settings


# Singleton para usar en toda la app
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> Settings:
    """Fuerza recarga desde disco (útil en desarrollo)."""
    global _settings
    _settings = load_settings()
    return _settings
