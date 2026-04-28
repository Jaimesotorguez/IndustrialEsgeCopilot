"""
analytics/reasoning_engine.py — M9: Razonamiento operativo
===========================================================
Orquesta el diagnóstico completo cuando se detecta una anomalía.

Flujo M9 (nuevo — iterativo):
1. Recibe AnomalyEvent del Observer (M8)
2. FeatureExtractor convierte datos actuales en features estructuradas (€0)
3. HypothesisEngine itera: genera hipótesis (LLM) → testa con Python (€0) → acepta/rechaza
4. Si no converge, genera pregunta para el operario
5. Retorna Diagnosis estructurado con evidencia

Control de coste:
- FeatureExtractor: €0 (Python puro)
- HypothesisEngine: 1 llamada LLM por iteración (típicamente 1-2)
- Contexto comprimido: máximo top_n=15 variables al LLM
"""

import uuid
from datetime import datetime
from typing import Optional

from backend.core.interfaces import AnomalyEvent, Diagnosis, Severity
from backend.core.config import get_settings
from backend.analytics.feature_extractor import FeatureExtractor
from backend.inference.hypothesis_engine import HypothesisEngine, InferenceResult


class ReasoningEngine:
    """
    Motor de razonamiento operativo.
    Conecta detección de anomalías → FeatureExtractor → HypothesisEngine → Diagnosis.
    """

    def __init__(
        self,
        llm=None,
        process_graph=None,
        memory=None,
        normalizer=None,
    ):
        self._llm = llm
        self._graph = process_graph
        self._memory = memory
        self._normalizer = normalizer
        self._extractor = FeatureExtractor()
        self._engine = HypothesisEngine(llm=llm, process_graph=process_graph)
        self._diagnosis_count = 0

    async def diagnose(self, event: AnomalyEvent) -> Optional[Diagnosis]:
        """
        Genera un diagnóstico completo para un evento de anomalía.
        Retorna None si el score es demasiado bajo.
        """
        cfg = get_settings()
        if event.anomaly_score < cfg.escalation.min_confidence_for_llm:
            return None

        try:
            # ── 1. Recupera datos recientes para feature extraction ────────────
            df_current = self._get_recent_dataframe(event.tag_ids)
            baselines = self._get_baselines(event.tag_ids)

            # ── 2. Extrae features estructuradas (€0) ─────────────────────────
            features = {}
            if df_current is not None and not df_current.empty:
                features = self._extractor.extract(
                    df_current, baselines=baselines, top_n=15
                )

            if not features:
                return self._simple_diagnosis(event)

            # ── 3. Motor iterativo de hipótesis ───────────────────────────────
            context = {
                "anomaly_description": event.description,
                "severity": event.severity.value,
                "anomaly_score": event.anomaly_score,
                "plant": cfg.plant.name,
                "sector": cfg.plant.sector,
                "similar_events": self._get_similar_events(event.tag_ids),
            }

            inference: InferenceResult = await self._engine.run(
                features=features,
                df_current=df_current,
                context=context,
                max_iterations=3,
            )

            # ── 4. Construye Diagnosis desde InferenceResult ───────────────────
            if inference.accepted:
                top = max(inference.accepted, key=lambda h: h.score)
                cause = top.hypothesis
                confidence = top.score
                evidence = top.evidence_for
            else:
                cause = inference.summary
                confidence = event.anomaly_score * 0.6   # Reducida por incertidumbre
                evidence = [event.description]

            tags_involved = list(
                set(event.tag_ids)
                | set(
                    tag
                    for h in inference.accepted
                    for tag in features.get("variables", {}).keys()
                    if tag.lower() in h.hypothesis.lower()
                )
            )

            diagnosis = Diagnosis(
                id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                probable_cause=cause,
                confidence=round(confidence, 3),
                tags_involved=tags_involved[:10],
                urgency=self._score_to_urgency(event.anomaly_score),
                evidence=evidence[:5],
                context_sent_tokens=inference.tokens_used,
            )

            # Adjunta pregunta para operario si la hay
            if inference.question_for_operator:
                diagnosis.evidence.append(
                    f"[PREGUNTA AL OPERARIO] {inference.question_for_operator}"
                )

            # ── 5. Persiste en memoria ────────────────────────────────────────
            if self._memory:
                event_id = self._memory.save_event(event)
                self._memory.save_diagnosis(diagnosis, event_id=event_id)

            self._diagnosis_count += 1
            print(
                f"[Reasoning] #{self._diagnosis_count}: "
                f"'{diagnosis.probable_cause[:60]}' "
                f"conf={diagnosis.confidence:.2f} "
                f"iters={inference.n_iterations} "
                f"tokens={inference.tokens_used}"
            )
            return diagnosis

        except Exception as e:
            print(f"[Reasoning] Error en diagnóstico: {e}")
            return self._simple_diagnosis(event)

    # ── Recuperación de datos actuales ────────────────────────────────────────

    def _get_recent_dataframe(self, tag_ids: list[str]):
        """
        Intenta recuperar un DataFrame de los datos más recientes.
        Fuente: normalizer si tiene buffer, o None.
        """
        if not self._normalizer:
            return None
        try:
            if hasattr(self._normalizer, "get_recent_dataframe"):
                return self._normalizer.get_recent_dataframe(n=100)
        except Exception:
            pass
        return None

    def _get_baselines(self, tag_ids: list[str]) -> dict:
        if not self._normalizer or not hasattr(self._normalizer, "get_baseline"):
            return {}
        baselines = {}
        for tag in tag_ids:
            b = self._normalizer.get_baseline(tag)
            if b:
                baselines[tag] = b
        return baselines

    def _get_similar_events(self, tag_ids: list[str]) -> list[dict]:
        if not self._memory:
            return []
        try:
            past = self._memory.get_similar_events(tag_ids, limit=3)
            return [
                {
                    "descripcion": e.description,
                    "severity": e.severity.value,
                    "score": e.anomaly_score,
                    "cuando": e.timestamp.isoformat(),
                }
                for e in past
            ]
        except Exception:
            return []

    # ── Diagnóstico simple sin LLM ────────────────────────────────────────────

    def _simple_diagnosis(self, event: AnomalyEvent) -> Diagnosis:
        return Diagnosis(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            probable_cause=(
                f"Anomalía detectada en {', '.join(event.tag_ids[:3])}. "
                f"Score: {event.anomaly_score:.2f}"
            ),
            confidence=event.anomaly_score,
            tags_involved=event.tag_ids,
            urgency=self._score_to_urgency(event.anomaly_score),
            evidence=[event.description],
            context_sent_tokens=0,
        )

    def _score_to_urgency(self, score: float) -> int:
        if score >= 0.9: return 5
        if score >= 0.8: return 4
        if score >= 0.7: return 3
        if score >= 0.6: return 2
        return 1

    def get_stats(self) -> dict:
        return {
            "total_diagnoses": self._diagnosis_count,
            "validated_hypotheses": len(self._engine.get_validated_history()),
        }
