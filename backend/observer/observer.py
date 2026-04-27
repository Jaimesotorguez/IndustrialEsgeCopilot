"""
observer/observer.py — M8: Observación en tiempo real
======================================================
Bucle principal del sistema. Corre continuamente, lee datos,
detecta anomalías con los modelos locales (coste €0) y decide
cuándo escalar a Claude API (coste real).

La clave del coste controlado está aquí:
- Isolation Forest corre local → siempre activo, coste €0
- Claude API → solo cuando hay anomalía con score > threshold

Arquitectura:
    IngestionManager → SensorNormalizer → IsolationForestDetector
                                                    ↓ (si anomalía)
                                            Claude API (M9/M5)
                                                    ↓
                                            Evento → WebSocket → Dashboard
"""

import asyncio
from datetime import datetime
from typing import Callable, Optional
import pandas as pd

from backend.core.interfaces import AnomalyEvent, RealtimeObserver as RealtimeObserverBase, SensorReading
from backend.core.config import get_settings
from backend.adapters.ingestion_manager import IngestionManager
from backend.normalizer.normalizer import SensorNormalizer
from backend.analytics.anomaly_detector import IsolationForestDetector


class RealtimeObserver(RealtimeObserverBase):
    """
    Bucle de observación en tiempo real.

    Ciclo (cada N segundos):
    1. Lee datos de todas las fuentes (IngestionManager)
    2. Normaliza (SensorNormalizer)
    3. Detecta anomalías (IsolationForestDetector — local, coste €0)
    4. Si hay anomalía con score suficiente → emite evento
    5. Los handlers registrados deciden si escalar a Claude
    """

    def __init__(
        self,
        ingestion: IngestionManager,
        normalizer: SensorNormalizer,
        detector: IsolationForestDetector,
        polling_interval: Optional[int] = None,
    ):
        self._ingestion = ingestion
        self._normalizer = normalizer
        self._detector = detector
        cfg = get_settings()
        self._interval = polling_interval or cfg.observer.polling_interval_seconds
        self._threshold = cfg.observer.anomaly_threshold

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Callbacks registrados para eventos
        self._anomaly_handlers: list[Callable[[AnomalyEvent], None]] = []
        self._reading_handlers: list[Callable[[list[SensorReading]], None]] = []

        # Buffer en memoria de las últimas lecturas (para el dashboard)
        self._latest_readings: dict[str, SensorReading] = {}  # tag_id → última lectura
        self._latest_events: list[AnomalyEvent] = []          # últimos 50 eventos

        self._stats = {
            "cycles": 0,
            "total_readings": 0,
            "total_anomalies": 0,
            "last_cycle_at": None,
            "last_anomaly_at": None,
            "running": False,
        }

    # ── Control del bucle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Arranca el bucle de observación en background."""
        if self._running:
            return
        self._running = True
        self._stats["running"] = True
        self._task = asyncio.create_task(self._loop())
        print(f"[Observer] Bucle iniciado — intervalo {self._interval}s")

    async def stop(self) -> None:
        """Detiene el bucle limpiamente."""
        self._running = False
        self._stats["running"] = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[Observer] Bucle detenido")

    # ── Registro de handlers ──────────────────────────────────────────────────

    def on_anomaly(self, handler: Callable[[AnomalyEvent], None]) -> None:
        """
        Registra un callback para cuando se detecte una anomalía.
        El handler decide si escala a Claude o solo registra el evento.

        Ejemplo:
            observer.on_anomaly(lambda event: escalate_to_claude(event))
        """
        self._anomaly_handlers.append(handler)

    def on_readings(self, handler: Callable[[list[SensorReading]], None]) -> None:
        """Registra un callback para cada batch de lecturas (para el dashboard)."""
        self._reading_handlers.append(handler)

    # ── Estado actual ─────────────────────────────────────────────────────────

    def get_latest_readings(self) -> dict[str, SensorReading]:
        """Última lectura de cada tag — para el dashboard en tiempo real."""
        return self._latest_readings.copy()

    def get_latest_events(self, limit: int = 20) -> list[AnomalyEvent]:
        """Últimos eventos detectados."""
        return self._latest_events[-limit:]

    def get_stats(self) -> dict:
        return self._stats.copy()

    # ── Bucle principal ───────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """Bucle infinito de observación."""
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Observer] Error en ciclo: {e}")

            await asyncio.sleep(self._interval)

    async def _cycle(self) -> None:
        """Un ciclo completo de observación."""
        # 1. Leer datos
        readings = await self._ingestion.read_all()
        if not readings:
            return

        # 2. Normalizar
        df = self._normalizer.normalize(readings)
        if df.empty:
            return

        # 3. Actualizar buffer de últimas lecturas (para dashboard)
        self._update_latest_readings(readings)

        # 4. Notificar handlers de lecturas (dashboard en tiempo real)
        for handler in self._reading_handlers:
            try:
                handler(readings)
            except Exception as e:
                print(f"[Observer] Error en reading handler: {e}")

        # 5. Detectar anomalías (local, coste €0)
        if not hasattr(self._detector, '_fitted') or self._detector._fitted:
            events = self._detector.detect(df)
        else:
            events = []

        # 6. Procesar eventos detectados
        for event in events:
            self._latest_events.append(event)
            if len(self._latest_events) > 50:
                self._latest_events.pop(0)

            self._stats["total_anomalies"] += 1
            self._stats["last_anomaly_at"] = event.timestamp.isoformat()

            print(f"[Observer] ANOMALÍA: score={event.anomaly_score:.2f} "
                  f"severity={event.severity.value} tags={event.tag_ids[:3]}")

            # Notificar handlers (uno de ellos escalará a Claude si score > threshold)
            for handler in self._anomaly_handlers:
                try:
                    handler(event)
                except Exception as e:
                    print(f"[Observer] Error en anomaly handler: {e}")

        # Actualizar stats
        self._stats["cycles"] += 1
        self._stats["total_readings"] += len(readings)
        self._stats["last_cycle_at"] = datetime.now().isoformat()

    def _update_latest_readings(self, readings: list[SensorReading]) -> None:
        """Actualiza el buffer con las lecturas más recientes por tag."""
        for r in readings:
            self._latest_readings[r.tag_id] = r


# ── Función de arranque del sistema completo ──────────────────────────────────

async def build_and_start_observer(data_path: str = "simulator/data/") -> RealtimeObserver:
    """
    Construye y arranca el observador completo con todos los módulos.
    Punto de entrada para arrancar el sistema desde main.py.

    Secuencia:
    1. Conecta fuentes de datos
    2. Carga histórico y entrena modelo de anomalías
    3. Arranca el bucle de observación
    """
    from backend.adapters.ingestion_manager import build_ingestion_manager

    print("[Sistema] Iniciando Industrial Edge Copilot...")

    # M1: Ingesta
    ingestion = build_ingestion_manager()
    await ingestion.start()

    # M2: Normalizador
    normalizer = SensorNormalizer()

    # M4: Detector de anomalías
    detector = IsolationForestDetector()

    # Carga histórico y entrena el modelo
    print("[Sistema] Cargando histórico para entrenar modelo...")
    from backend.adapters.csv_adapter import CsvAdapter
    csv_adapters = ingestion.get_adapters_of_type(CsvAdapter)
    if csv_adapters:
        historical_df = await csv_adapters[0].load_full_historical()
        if not historical_df.empty:
            normalized_hist = normalizer.normalize_dataframe(historical_df)
            normalizer.fit(normalized_hist)
            detector.fit(normalized_hist)
            print(f"[Sistema] Modelo entrenado con {len(historical_df)} filas de histórico")
        else:
            print("[Sistema] ⚠ Sin histórico — modelo no entrenado. El detector funcionará sin baseline.")

    # M8: Observer
    observer = RealtimeObserver(ingestion, normalizer, detector)

    print("[Sistema] ✓ Listo para monitorizar")
    return observer
