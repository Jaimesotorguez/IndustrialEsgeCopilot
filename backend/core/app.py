"""
core/app.py — Contenedor de la aplicación
==========================================
Conecta todos los módulos entre sí. Es el único sitio donde
se instancian los módulos concretos y se pasan como dependencias.

Por qué existe este archivo:
- Evita que los módulos se importen entre sí directamente (acoplamiento)
- Facilita el testing: puedes sustituir cualquier módulo por un mock
- Un solo lugar para ver cómo está montado el sistema completo

Flujo de arranque:
  AppContainer.build() → crea todos los módulos
  AppContainer.start() → conecta fuentes de datos, entrena modelos, arranca bucle
  AppContainer.stop()  → cierra limpiamente todo
"""

import asyncio
from typing import Optional

from backend.core.config import get_settings


class AppContainer:
    """
    Contenedor central de la aplicación.
    Instancia y conecta todos los módulos del sistema.
    """

    def __init__(self):
        # M1 — Ingesta
        self.ingestion = None
        # M2 — Normalización
        self.normalizer = None
        # M3/M7 — Grafo de proceso
        self.process_graph = None
        # M4 — Detección de anomalías
        self.detector = None
        # M5/M9/M11 — LLM
        self.llm = None
        # M6 — Interacción
        self.interaction = None
        # M8 — Observación RT
        self.observer = None
        # M9 — Razonamiento
        self.reasoning = None
        # M10 — Recomendación
        self.recommender = None
        # M12 — Memoria
        self.memory = None
        # M13 — Validación
        self.validator = None

        self._started = False

    @classmethod
    async def build(cls) -> "AppContainer":
        """
        Factory principal. Construye el sistema completo.
        Orden importa: los módulos que dependen de otros se crean después.
        """
        cfg = get_settings()
        app = cls()

        print("[App] Construyendo módulos...")

        # ── M12: Memoria (primero — otros módulos la necesitan) ────────────────
        from backend.memory.memory_store import SqliteMemoryStore
        app.memory = SqliteMemoryStore(db_path=cfg.storage.sqlite_path)

        # ── M13: Validador de seguridad ────────────────────────────────────────
        from backend.validator.safety_validator import SafetyValidatorImpl
        app.validator = SafetyValidatorImpl()

        # ── M3/M7: Grafo de proceso ────────────────────────────────────────────
        from backend.process_model.process_graph import ProcessGraph
        app.process_graph = ProcessGraph(graph_path=cfg.storage.knowledge_graph_path)

        # ── LLM: Proveedor de IA ───────────────────────────────────────────────
        try:
            from backend.llm.provider_factory import get_llm_provider
            app.llm = get_llm_provider()
        except Exception as e:
            print(f"[App] ⚠ LLM no disponible: {e}")
            print("[App]   El sistema funcionará sin IA conversacional")
            app.llm = None

        # ── M1: Ingesta ────────────────────────────────────────────────────────
        from backend.adapters.ingestion_manager import build_ingestion_manager
        app.ingestion = build_ingestion_manager()

        # ── M2: Normalizador ───────────────────────────────────────────────────
        from backend.normalizer.normalizer import SensorNormalizer
        app.normalizer = SensorNormalizer()

        # ── M4: Detector de anomalías ──────────────────────────────────────────
        from backend.analytics.anomaly_detector import IsolationForestDetector
        app.detector = IsolationForestDetector(
            contamination=0.05,
            anomaly_threshold=cfg.observer.anomaly_threshold,
            model_path="data/anomaly_model.joblib",
        )

        # ── M9: Motor de razonamiento ──────────────────────────────────────────
        from backend.analytics.reasoning_engine import ReasoningEngine
        app.reasoning = ReasoningEngine(
            llm=app.llm,
            process_graph=app.process_graph,
            memory=app.memory,
            normalizer=app.normalizer,
        )

        # ── M10: Recomendador ──────────────────────────────────────────────────
        from backend.recommender.recommender import ActionRecommenderImpl
        app.recommender = ActionRecommenderImpl(
            ingestion_manager=app.ingestion,
            validator=app.validator,
            memory=app.memory,
            llm=app.llm,
        )

        # ── M6: Interacción ────────────────────────────────────────────────────
        from backend.interaction.interaction_manager import InteractionManager
        app.interaction = InteractionManager(
            process_graph=app.process_graph,
            llm=app.llm,
            memory=app.memory,
        )

        # ── M8: Observer ───────────────────────────────────────────────────────
        from backend.observer.observer import RealtimeObserver
        app.observer = RealtimeObserver(
            ingestion=app.ingestion,
            normalizer=app.normalizer,
            detector=app.detector,
            polling_interval=cfg.observer.polling_interval_seconds,
        )

        # Registra el handler principal: anomalía → diagnóstico → recomendación
        app.observer.on_anomaly(
            lambda event: asyncio.create_task(app._handle_anomaly(event))
        )

        print("[App] ✓ Todos los módulos construidos")
        return app

    async def start(self) -> None:
        """
        Arranque completo del sistema:
        1. Conecta fuentes de datos
        2. Carga histórico y entrena modelos
        3. Aprende grafo de proceso (si no existe)
        4. Arranca bucle de observación RT
        """
        if self._started:
            return

        print("[App] Iniciando sistema...")

        # ── 1. Conecta fuentes de datos ────────────────────────────────────────
        await self.ingestion.start()

        # ── 2. Carga histórico y entrena modelos ───────────────────────────────
        await self._train_models()

        # ── 3. Arranca bucle de observación ────────────────────────────────────
        await self.observer.start()

        self._started = True
        print("[App] ✓ Sistema en marcha")

    async def stop(self) -> None:
        """Parada limpia de todos los módulos."""
        print("[App] Parando sistema...")
        if self.observer:
            await self.observer.stop()
        if self.ingestion:
            await self.ingestion.stop()
        if self.memory:
            self.memory.close()
        self._started = False
        print("[App] Sistema parado")

    # ── Handler central de anomalías ──────────────────────────────────────────

    async def _handle_anomaly(self, event) -> None:
        """
        Pipeline completo: evento → diagnóstico → recomendación.
        Este es el corazón del sistema en tiempo real.
        """
        try:
            # M9: Genera diagnóstico con Claude
            diagnosis = await self.reasoning.diagnose(event)
            if not diagnosis:
                return

            # M10: Genera recomendaciones de acción
            actions = await self.recommender.recommend(diagnosis)

            if actions:
                print(f"[App] {len(actions)} acción(es) pendiente(s) de aprobación")

            # M6: Genera pregunta si hay ambigüedad
            if diagnosis.confidence < 0.75 and self.interaction:
                await self.interaction.generate_question_for_anomaly(
                    tag_ids=event.tag_ids,
                    anomaly_description=event.description,
                )

        except Exception as e:
            print(f"[App] Error en pipeline de anomalía: {e}")

    # ── Entrenamiento de modelos ───────────────────────────────────────────────

    async def _train_models(self) -> None:
        """Carga histórico y entrena modelos ML."""
        from backend.adapters.csv_adapter import CsvAdapter

        csv_adapters = self.ingestion.get_adapters_of_type(CsvAdapter)
        if not csv_adapters:
            print("[App] Sin fuente CSV — modelos sin entrenar")
            return

        print("[App] Cargando histórico...")
        historical_df = await csv_adapters[0].load_full_historical()

        if historical_df.empty:
            print("[App] ⚠ Histórico vacío")
            return

        # Normaliza el histórico
        normalized = self.normalizer.normalize_dataframe(historical_df)
        self.normalizer.fit(normalized)

        # Entrena o carga el detector de anomalías
        if not self.detector.load("data/anomaly_model.joblib"):
            print("[App] Entrenando modelo de anomalías...")
            self.detector.fit(normalized)
            print(f"[App] Modelo entrenado: {len(normalized)} muestras")

        # Aprende grafo de proceso si no existe
        if len(self.process_graph.get_nodes()) == 0:
            print("[App] Aprendiendo grafo de proceso...")
            self.process_graph.learn_from_historical(normalized)

    # ── Acceso a estado para la API ────────────────────────────────────────────

    def get_full_status(self) -> dict:
        """Estado completo del sistema para el endpoint /api/status."""
        cfg = get_settings()
        return {
            "plant": cfg.plant.name,
            "sector": cfg.plant.sector,
            "started": self._started,
            "llm": {
                "provider": cfg.llm.provider,
                "model": cfg.llm.model,
                "available": self.llm is not None,
            },
            "observer": self.observer.get_stats() if self.observer else {},
            "memory": self.memory.get_stats() if self.memory else {},
            "process_graph": self.process_graph.get_summary() if self.process_graph else {},
            "detector": self.detector.get_stats() if self.detector else {},
            "reasoning": self.reasoning.get_stats() if self.reasoning else {},
            "pending_actions": len(self.recommender.get_pending()) if self.recommender else 0,
            "pending_questions": len(self.process_graph.get_pending_questions()) if self.process_graph else 0,
            "validator": {
                "emergency_stopped": self.validator.is_emergency_stopped() if self.validator else False,
            },
        }
