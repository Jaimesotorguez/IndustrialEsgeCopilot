"""
INDUSTRIAL EDGE COPILOT — INTERFACES CENTRALES
===============================================
Todas las Abstract Base Classes del sistema.
Cada módulo implementa su interfaz correspondiente.
Cambiar implementación = nueva clase que hereda de aquí.
El resto del sistema no cambia.

REGLA: Nunca importar implementaciones concretas fuera de su módulo.
       Siempre importar la interfaz y usar inyección de dependencias.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import pandas as pd


# ══════════════════════════════════════════════════════════════════
# TIPOS DE DATOS COMPARTIDOS
# ══════════════════════════════════════════════════════════════════

class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SensorReading:
    """Lectura normalizada de un sensor. Formato interno estándar."""
    timestamp: datetime
    tag_id: str
    value: float
    unit_guess: str = ""
    quality: float = 1.0        # 0-1: calidad del dato
    source: str = ""            # Protocolo origen: opcua, modbus, csv...


@dataclass
class AnomalyEvent:
    """Evento de anomalía detectado por la capa de observación local."""
    timestamp: datetime
    tag_ids: list[str]
    anomaly_score: float        # 0-1
    severity: Severity
    description: str
    raw_values: dict[str, float] = field(default_factory=dict)


@dataclass
class Hypothesis:
    """Hipótesis generada sobre el estado del proceso."""
    id: str
    timestamp: datetime
    description: str
    confidence: float           # 0-1
    tags_involved: list[str]
    evidence: list[str]
    suggested_actions: list[str]


@dataclass
class Diagnosis:
    """Diagnóstico completo generado por el módulo de razonamiento."""
    id: str
    timestamp: datetime
    probable_cause: str
    confidence: float           # 0-1
    tags_involved: list[str]
    urgency: int                # 1-5
    evidence: list[str]
    context_sent_tokens: int    # Para monitorizar coste API


@dataclass
class RecommendedAction:
    """Acción recomendada pendiente de aprobación humana."""
    id: str
    timestamp: datetime
    machine_id: str
    action_type: str            # RPM_REDUCE, VALVE_CLOSE, MACHINE_STOP...
    parameters: dict[str, Any]
    reason: str
    estimated_impact: str       # Descripción en lenguaje natural
    estimated_saving_eur: float
    risk_level: Severity
    status: ActionStatus = ActionStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


@dataclass
class LLMResponse:
    """Respuesta normalizada de cualquier proveedor LLM."""
    text: str
    tokens_input: int
    tokens_output: int
    model_used: str
    provider: str
    latency_ms: float


# ══════════════════════════════════════════════════════════════════
# M1 — INGESTA
# ══════════════════════════════════════════════════════════════════

class DataSourceAdapter(ABC):
    """
    Interfaz para todos los adaptadores de fuentes de datos.
    Implementaciones: OpcUaAdapter, ModbusAdapter, MqttAdapter, CsvAdapter
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Establece conexión con la fuente. Retorna True si éxito."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def read(self) -> list[SensorReading]:
        """Lee el último batch de datos disponibles."""
        ...

    @abstractmethod
    async def write(self, tag_id: str, value: Any) -> bool:
        """Escribe un valor en la fuente (para comandos de control)."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Nombre identificador de esta fuente."""
        ...


# ══════════════════════════════════════════════════════════════════
# M2 — NORMALIZACIÓN
# ══════════════════════════════════════════════════════════════════

class DataNormalizer(ABC):
    """Convierte lecturas crudas en DataFrame normalizado con schema fijo."""

    @abstractmethod
    def normalize(self, readings: list[SensorReading]) -> pd.DataFrame:
        """
        Input: lista de SensorReading
        Output: DataFrame con columnas: [timestamp, tag_id, value, unit_guess, quality, source]
        """
        ...

    @abstractmethod
    def infer_variable_type(self, tag_id: str, values: list[float]) -> str:
        """Infiere tipo: temperatura, presion, rpm, binario, contador..."""
        ...


# ══════════════════════════════════════════════════════════════════
# M3/M7 — MODELO DE PROCESO Y CONOCIMIENTO
# ══════════════════════════════════════════════════════════════════

class ProcessModelStore(ABC):
    """Almacena y actualiza el grafo de conocimiento de la planta."""

    @abstractmethod
    def get_related_tags(self, tag_id: str, max_hops: int = 2) -> list[str]:
        """Retorna tags relacionados con el dado (subgrafo relevante)."""
        ...

    @abstractmethod
    def add_relation(self, tag_a: str, tag_b: str, relation_type: str, confidence: float) -> None:
        ...

    @abstractmethod
    def get_equipment_for_tag(self, tag_id: str) -> Optional[str]:
        """¿A qué equipo pertenece este sensor?"""
        ...

    @abstractmethod
    def save(self) -> None:
        """Persiste el grafo a disco."""
        ...

    @abstractmethod
    def load(self) -> None:
        """Carga el grafo desde disco."""
        ...


# ══════════════════════════════════════════════════════════════════
# M4 — ANÁLISIS HISTÓRICO / DETECCIÓN DE ANOMALÍAS
# ══════════════════════════════════════════════════════════════════

class AnomalyDetector(ABC):
    """Detecta anomalías en series temporales sin supervisión."""

    @abstractmethod
    def fit(self, historical_data: pd.DataFrame) -> None:
        """Entrena el modelo con datos históricos normales."""
        ...

    @abstractmethod
    def detect(self, current_data: pd.DataFrame) -> list[AnomalyEvent]:
        """Detecta anomalías en el batch actual."""
        ...

    @abstractmethod
    def get_anomaly_score(self, reading: SensorReading) -> float:
        """Score 0-1 para una lectura individual."""
        ...


# ══════════════════════════════════════════════════════════════════
# M5/M9/M11 — LLM (AGNÓSTICO AL PROVEEDOR)
# ══════════════════════════════════════════════════════════════════

class LLMProvider(ABC):
    """
    Interfaz única para todos los proveedores LLM.
    NUNCA llamar a anthropic/openai/gemini directamente fuera de sus implementaciones.
    """

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """Llamada principal al LLM con contexto estructurado."""
        ...

    @abstractmethod
    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        output_schema: dict,
    ) -> dict:
        """Llamada que garantiza output JSON válido según schema."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


# ══════════════════════════════════════════════════════════════════
# M8 — OBSERVACIÓN EN TIEMPO REAL
# ══════════════════════════════════════════════════════════════════

class RealtimeObserver(ABC):
    """Bucle principal de observación continua."""

    @abstractmethod
    async def start(self) -> None:
        """Arranca el bucle de observación."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    def on_anomaly(self, callback) -> None:
        """Registra callback para cuando se detecta anomalía."""
        ...


# ══════════════════════════════════════════════════════════════════
# M10 — RECOMENDACIÓN Y CONTROL
# ══════════════════════════════════════════════════════════════════

class ActionRecommender(ABC):
    """Genera recomendaciones de acción a partir de diagnósticos."""

    @abstractmethod
    async def recommend(self, diagnosis: Diagnosis) -> list[RecommendedAction]:
        ...

    @abstractmethod
    async def execute(self, action: RecommendedAction) -> bool:
        """Ejecuta una acción ya aprobada por el humano."""
        ...

    @abstractmethod
    async def emergency_stop(self) -> None:
        """Detiene TODA escritura en PLCs inmediatamente."""
        ...


# ══════════════════════════════════════════════════════════════════
# M12 — MEMORIA / PERSISTENCIA
# ══════════════════════════════════════════════════════════════════

class MemoryStore(ABC):
    """Persistencia de todos los objetos del sistema."""

    @abstractmethod
    def save_event(self, event: AnomalyEvent) -> str:
        """Retorna el ID asignado."""
        ...

    @abstractmethod
    def save_diagnosis(self, diagnosis: Diagnosis) -> str:
        ...

    @abstractmethod
    def save_action(self, action: RecommendedAction) -> str:
        ...

    @abstractmethod
    def update_action_status(self, action_id: str, status: ActionStatus, approved_by: str = "") -> None:
        ...

    @abstractmethod
    def get_similar_events(self, tag_ids: list[str], limit: int = 5) -> list[AnomalyEvent]:
        """Búsqueda semántica de eventos similares (para RAG)."""
        ...

    @abstractmethod
    def get_recent_diagnoses(self, hours: int = 24) -> list[Diagnosis]:
        ...


# ══════════════════════════════════════════════════════════════════
# M13 — VALIDACIÓN
# ══════════════════════════════════════════════════════════════════

class SafetyValidator(ABC):
    """Valida que toda acción está dentro de los límites de seguridad."""

    @abstractmethod
    def validate_action(self, action: RecommendedAction) -> tuple[bool, str]:
        """
        Retorna (es_válida, motivo_si_no_válida)
        Una acción inválida NUNCA se ejecuta, ni con aprobación humana.
        """
        ...

    @abstractmethod
    def is_within_safe_range(self, tag_id: str, value: float) -> bool:
        ...
