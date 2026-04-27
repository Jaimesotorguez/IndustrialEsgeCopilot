"""
interaction/interaction_manager.py — M6: Interacción Humano-IA
===============================================================
Gestiona el diálogo entre el sistema y el operario.

Dos funciones principales:
1. Preguntas de aprendizaje: valida hipótesis del grafo de proceso
2. Aprobación de comandos: flujo de confirmación antes de actuar

Principio: nunca más de 1-2 preguntas pendientes al mismo tiempo.
El operario no debe sentirse interrogado — solo lo mínimo imprescindible.
"""

import uuid
from datetime import datetime
from typing import Optional, Callable

from backend.process_model.process_graph import ProcessGraph, ProcessQuestion


class InteractionManager:
    """
    Gestiona todas las interacciones entre el sistema y el operario.

    Uso:
        mgr = InteractionManager(process_graph, llm, memory)
        question = mgr.get_next_question()
        if question:
            # Mostrar al operario en el dashboard
            mgr.submit_answer(question.id, "Sí, mismo equipo")
    """

    def __init__(
        self,
        process_graph: ProcessGraph,
        llm=None,
        memory=None,
        max_pending_questions: int = 2,
    ):
        self._graph = process_graph
        self._llm = llm
        self._memory = memory
        self._max_pending = max_pending_questions
        self._answer_callbacks: list[Callable] = []

    # ── Preguntas de aprendizaje ──────────────────────────────────────────────

    def get_next_question(self) -> Optional[ProcessQuestion]:
        """
        Retorna la siguiente pregunta pendiente para el operario.
        Nunca devuelve más de una a la vez — no queremos agobiar.
        """
        pending = self._graph.get_pending_questions()
        if not pending:
            return None
        # Prioriza las preguntas con mayor impacto en el grafo
        return pending[0]

    def submit_answer(self, question_id: str, answer: str) -> dict:
        """
        Procesa la respuesta del operario.
        Actualiza el grafo y persiste el conocimiento.
        """
        self._graph.answer_question(question_id, answer)

        # Guarda en memoria como conocimiento validado
        if self._memory:
            pending = [q for q in self._graph.get_pending_questions() if q.id == question_id]
            if pending:
                q = pending[0]
                self._memory.save_knowledge(
                    content=f"P: {q.question} — R: {answer}",
                    source="operator",
                    tag_ids=q.related_tags,
                    confidence=1.0,
                    validated=True,
                )

        # Notifica callbacks
        for cb in self._answer_callbacks:
            try:
                cb(question_id, answer)
            except Exception:
                pass

        # Genera siguiente pregunta si hay más
        next_q = self.get_next_question()
        return {
            "status": "answered",
            "question_id": question_id,
            "next_question": {
                "id": next_q.id,
                "question": next_q.question,
                "options": next_q.options,
                "related_tags": next_q.related_tags,
            } if next_q else None,
        }

    def on_answer(self, callback: Callable) -> None:
        """Registra callback cuando el operario responde."""
        self._answer_callbacks.append(callback)

    # ── Generación dinámica de preguntas ──────────────────────────────────────

    async def generate_question_for_anomaly(
        self,
        tag_ids: list[str],
        anomaly_description: str,
    ) -> Optional[ProcessQuestion]:
        """
        Genera una pregunta específica sobre una anomalía detectada.
        Útil cuando el sistema necesita contexto operativo que no tiene.
        """
        if not self._llm:
            return None

        # Solo genera si hay pocas preguntas pendientes
        if len(self._graph.get_pending_questions()) >= self._max_pending:
            return None

        try:
            context = {
                "anomalia": anomaly_description,
                "tags_involucrados": tag_ids[:5],
                "equipos_conocidos": [
                    {"nombre": n.name, "tags": n.tags[:3]}
                    for n in self._graph.get_nodes()[:5]
                ],
            }

            schema = {
                "pregunta": "string — pregunta concisa para el operario (máx 120 chars)",
                "contexto": "string — por qué se hace esta pregunta",
                "opciones": ["opción 1", "opción 2", "opción 3"],
            }

            result = await self._llm.complete_json(
                system_prompt=(
                    "Generas preguntas mínimas y precisas para operarios industriales. "
                    "Las preguntas deben ser técnicas, directas y fáciles de responder. "
                    "Nunca preguntes algo que puedas inferir de los datos. "
                    "Responde en español."
                ),
                user_message="Genera la pregunta más útil para resolver esta anomalía:",
                context=context,
                output_schema=schema,
            )

            if not result.get("pregunta"):
                return None

            question = ProcessQuestion(
                id=str(uuid.uuid4()),
                question=result["pregunta"],
                context=result.get("contexto", ""),
                options=result.get("opciones", ["Sí", "No", "No sé"]),
                related_tags=tag_ids[:4],
            )
            self._graph.add_question(question)
            return question

        except Exception as e:
            print(f"[Interaction] Error generando pregunta: {e}")
            return None

    # ── Estado ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        pending = self._graph.get_pending_questions()
        return {
            "pending_questions": len(pending),
            "next_question": {
                "id": pending[0].id,
                "question": pending[0].question,
                "options": pending[0].options,
                "related_tags": pending[0].related_tags,
            } if pending else None,
            "graph_summary": self._graph.get_summary(),
        }
