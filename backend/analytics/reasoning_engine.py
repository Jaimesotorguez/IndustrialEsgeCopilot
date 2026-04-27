"""
analytics/reasoning_engine.py — M9: Razonamiento operativo
===========================================================
Orquesta el diagnóstico completo cuando se detecta una anomalía.

Flujo completo M9:
1. Recibe AnomalyEvent del Observer (M8)
2. Comprime el contexto: subgrafo relevante + eventos similares (RAG)
3. Llama a Claude API con contexto comprimido
4. Retorna Diagnosis estructurado
5. Pasa el diagnóstico al Recommender (M10)

La clave del coste controlado:
- Solo se llama cuando hay anomalía con score > threshold (M8 ya filtró)
- El contexto se comprime: nunca más de ~2000 tokens de entrada
- El subgrafo limita qué variables se incluyen
"""

import uuid
from datetime import datetime
from typing import Optional

from backend.core.interfaces import AnomalyEvent, Diagnosis, Severity
from backend.core.config import get_settings


class ReasoningEngine:
    """
    Motor de razonamiento operativo.
    Conecta detección de anomalías → diagnóstico Claude → recomendación.
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
        self._diagnosis_count = 0

    async def diagnose(self, event: AnomalyEvent) -> Optional[Diagnosis]:
        """
        Genera un diagnóstico completo para un evento de anomalía.
        Retorna None si no hay LLM configurado o el score es muy bajo.
        """
        cfg = get_settings()
        if event.anomaly_score < cfg.escalation.min_confidence_for_llm:
            return None

        if not self._llm:
            return self._simple_diagnosis(event)

        try:
            # ── Compresión de contexto (clave para control de coste) ──────────
            relevant_tags = self._get_relevant_tags(event.tag_ids)
            baselines = self._get_baselines(relevant_tags)
            similar_events = self._get_similar_events(event.tag_ids)
            plant_config = {
                "sector": cfg.plant.sector,
                "language": cfg.plant.language,
                "name": cfg.plant.name,
            }

            # ── Llamada a Claude API ──────────────────────────────────────────
            result = await self._llm.diagnose(
                anomaly_description=event.description,
                relevant_tags=relevant_tags[:8],      # Máximo 8 variables
                tag_values=event.raw_values,
                tag_baselines=baselines,
                similar_past_events=similar_events[:3],  # Máximo 3 eventos pasados
                plant_config=plant_config,
            )

            if not result:
                return self._simple_diagnosis(event)

            # ── Construye objeto Diagnosis ────────────────────────────────────
            diagnosis = Diagnosis(
                id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                probable_cause=result.get("causa_probable", event.description),
                confidence=float(result.get("confianza", event.anomaly_score)),
                tags_involved=result.get("variables_implicadas", event.tag_ids),
                urgency=int(result.get("urgencia", self._score_to_urgency(event.anomaly_score))),
                evidence=result.get("evidencia", []),
                context_sent_tokens=0,  # Se actualiza desde el provider
            )

            # Persiste en memoria
            if self._memory:
                event_id = self._memory.save_event(event)
                self._memory.save_diagnosis(diagnosis, event_id=event_id)

            self._diagnosis_count += 1
            print(
                f"[Reasoning] Diagnóstico #{self._diagnosis_count}: "
                f"'{diagnosis.probable_cause[:60]}...' "
                f"confianza={diagnosis.confidence:.2f} urgencia={diagnosis.urgency}/5"
            )
            return diagnosis

        except Exception as e:
            print(f"[Reasoning] Error en diagnóstico: {e}")
            return self._simple_diagnosis(event)

    # ── Compresión de contexto ────────────────────────────────────────────────

    def _get_relevant_tags(self, tag_ids: list[str]) -> list[str]:
        """
        Obtiene tags relacionados del grafo de proceso.
        Esto es lo que limita el contexto enviado a Claude.
        """
        if not self._graph:
            return tag_ids

        all_relevant = set(tag_ids)
        for tag in tag_ids[:3]:  # Expande desde los 3 tags principales
            related = self._graph.get_related_tags(tag, max_hops=1)
            all_relevant.update(related[:5])  # Máximo 5 relacionados por tag

        return list(all_relevant)[:12]  # Tope absoluto de 12 tags en contexto

    def _get_baselines(self, tag_ids: list[str]) -> dict:
        """Obtiene estadísticas de baseline para los tags relevantes."""
        if not self._normalizer or not hasattr(self._normalizer, 'get_baseline'):
            return {}
        return {
            tag: self._normalizer.get_baseline(tag)
            for tag in tag_ids
            if self._normalizer.get_baseline(tag)
        }

    def _get_similar_events(self, tag_ids: list[str]) -> list[dict]:
        """RAG: recupera eventos similares del pasado para dar contexto."""
        if not self._memory:
            return []
        try:
            past_events = self._memory.get_similar_events(tag_ids, limit=3)
            return [
                {
                    "descripcion": e.description,
                    "severity": e.severity.value,
                    "score": e.anomaly_score,
                    "cuando": e.timestamp.isoformat(),
                }
                for e in past_events
            ]
        except Exception:
            return []

    # ── Diagnóstico simple sin LLM ────────────────────────────────────────────

    def _simple_diagnosis(self, event: AnomalyEvent) -> Diagnosis:
        """
        Diagnóstico básico sin LLM.
        Se usa cuando no hay API key o el score es bajo.
        """
        return Diagnosis(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            probable_cause=f"Anomalía detectada en {', '.join(event.tag_ids[:3])}. Score: {event.anomaly_score:.2f}",
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
        return {"total_diagnoses": self._diagnosis_count}
