"""
process_model/process_graph.py — M3/M7: Grafo de proceso
=========================================================
El diferenciador clave del producto. Aprende la estructura
de la planta solo, sin configuración previa.

Qué hace:
1. Analiza correlaciones entre variables del histórico
2. Agrupa variables en equipos usando clustering
3. Detecta ciclos y periodicidades naturales
4. Construye un grafo dirigido: nodos=equipos/variables, aristas=relaciones
5. Hace preguntas mínimas al operario para validar hipótesis

El grafo se persiste como JSON y se actualiza incrementalmente.
Cambiar de NetworkX a Neo4j en el futuro = cambiar solo la capa de IO.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class ProcessNode:
    """Nodo del grafo: puede ser un equipo o una variable individual."""
    id: str
    name: str
    node_type: str          # "equipment" | "variable" | "product"
    tags: list[str]         # Tags asociados a este nodo
    confidence: float       # 0-1: confianza en la identificación
    properties: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    validated_by_operator: bool = False


@dataclass
class ProcessEdge:
    """Arista del grafo: relación entre dos nodos."""
    id: str
    source: str             # ID del nodo origen
    target: str             # ID del nodo destino
    relation_type: str      # "feeds", "controls", "correlates_with", "causes"
    confidence: float       # 0-1
    correlation: float      # Correlación estadística si aplica
    lag_seconds: float      # Desfase temporal entre causa y efecto
    evidence: str           # Por qué existe esta relación
    validated_by_operator: bool = False


@dataclass
class ProcessQuestion:
    """Pregunta generada para el operario para validar hipótesis."""
    id: str
    question: str
    context: str            # Por qué se hace esta pregunta
    options: list[str]      # Opciones de respuesta
    related_tags: list[str]
    answered: bool = False
    answer: Optional[str] = None
    asked_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ProcessGraph:
    """
    Grafo de conocimiento del proceso industrial.

    Aprende automáticamente desde datos históricos y se refina
    con las respuestas del operario.
    """

    def __init__(self, graph_path: str = "data/process_graph.json"):
        self._graph_path = graph_path
        self._nodes: dict[str, ProcessNode] = {}
        self._edges: dict[str, ProcessEdge] = {}
        self._pending_questions: list[ProcessQuestion] = []
        self._tag_to_node: dict[str, str] = {}     # tag_id → node_id
        self._learning_phase = "initial"            # initial | learning | operating
        self._stats = {
            "nodes": 0, "edges": 0, "questions_asked": 0,
            "questions_answered": 0, "last_updated": None,
        }
        self.load()

    # ── Aprendizaje automático ────────────────────────────────────────────────

    def learn_from_historical(self, df: pd.DataFrame, min_correlation: float = 0.6) -> None:
        """
        Paso 1: Aprende correlaciones y estructura desde el histórico.
        Este método puede tardar varios segundos con datasets grandes.
        """
        if df.empty:
            return

        print("[ProcessGraph] Analizando histórico para aprender estructura del proceso...")

        # Pivota a formato wide para análisis
        wide = df.pivot_table(
            index="timestamp", columns="tag_id", values="value", aggfunc="mean"
        ).ffill().fillna(0)

        if wide.empty or len(wide.columns) < 2:
            return

        tags = list(wide.columns)

        # ── 1. Correlaciones entre pares de variables ─────────────────────────
        corr_matrix = wide.corr()
        high_corr_pairs = []
        for i, tag_a in enumerate(tags):
            for j, tag_b in enumerate(tags):
                if i >= j:
                    continue
                corr = corr_matrix.loc[tag_a, tag_b]
                if abs(corr) >= min_correlation:
                    high_corr_pairs.append((tag_a, tag_b, corr))

        # ── 2. Clustering de variables en grupos (equipos probables) ──────────
        equipment_groups = self._cluster_variables(wide, tags)

        # ── 3. Crea nodos de equipos ─────────────────────────────────────────
        for group_name, group_tags in equipment_groups.items():
            node = ProcessNode(
                id=str(uuid.uuid4()),
                name=group_name,
                node_type="equipment",
                tags=group_tags,
                confidence=0.6,  # Baja confianza inicial — se valida con operario
                properties={"n_variables": len(group_tags)},
            )
            self._nodes[node.id] = node
            for tag in group_tags:
                self._tag_to_node[tag] = node.id

        # ── 4. Crea aristas para pares con alta correlación ───────────────────
        for tag_a, tag_b, corr in high_corr_pairs[:50]:  # Máximo 50 relaciones
            node_a = self._tag_to_node.get(tag_a)
            node_b = self._tag_to_node.get(tag_b)
            if not node_a or not node_b or node_a == node_b:
                continue

            edge = ProcessEdge(
                id=str(uuid.uuid4()),
                source=node_a,
                target=node_b,
                relation_type="correlates_with",
                confidence=abs(corr) * 0.8,
                correlation=round(float(corr), 3),
                lag_seconds=0,
                evidence=f"Correlación estadística {corr:.2f} sobre {len(df)} muestras",
            )
            self._edges[edge.id] = edge

        # ── 5. Genera preguntas para validar con el operario ──────────────────
        self._generate_validation_questions(equipment_groups)

        self._learning_phase = "learning"
        self._update_stats()
        self.save()

        print(f"[ProcessGraph] Aprendizaje completado: "
              f"{len(self._nodes)} nodos, {len(self._edges)} aristas, "
              f"{len(self._pending_questions)} preguntas generadas")

    def _cluster_variables(self, wide: pd.DataFrame, tags: list[str]) -> dict[str, list[str]]:
        """
        Agrupa variables en equipos usando correlación como métrica.
        Implementación simple sin sklearn para reducir dependencias en este módulo.
        """
        from sklearn.cluster import AgglomerativeClustering

        if len(tags) < 2:
            return {"Equipo_1": tags}

        # Usa 1 - |correlación| como distancia
        corr = wide[tags].corr().fillna(0)
        distance_matrix = 1 - np.abs(corr.values)
        np.fill_diagonal(distance_matrix, 0)
        distance_matrix = np.clip(distance_matrix, 0, 1)

        n_clusters = max(2, min(8, len(tags) // 4))
        clustering = AgglomerativeClustering(
            n_clusters=n_clusters,
            metric="precomputed",
            linkage="average",
        )
        labels = clustering.fit_predict(distance_matrix)

        groups: dict[str, list[str]] = {}
        for tag, label in zip(tags, labels):
            group_name = f"Equipo_{label + 1}"
            groups.setdefault(group_name, []).append(tag)

        return groups

    def _generate_validation_questions(self, groups: dict[str, list[str]]) -> None:
        """Genera preguntas mínimas para validar la estructura aprendida."""
        questions_generated = 0
        max_questions = 5  # No más de 5 preguntas al operario en la fase inicial

        for group_name, tags in groups.items():
            if questions_generated >= max_questions:
                break
            if len(tags) < 2:
                continue

            # Pregunta si los tags pertenecen al mismo equipo
            q = ProcessQuestion(
                id=str(uuid.uuid4()),
                question=f"He detectado que {', '.join(tags[:3])} siempre se mueven juntas. ¿Forman parte del mismo equipo o sistema?",
                context=f"Correlación alta detectada entre {len(tags)} variables del grupo {group_name}",
                options=["Sí, mismo equipo", "No, son independientes", "Parcialmente — algunas sí"],
                related_tags=tags[:4],
            )
            self._pending_questions.append(q)
            questions_generated += 1

    # ── Interfaz del grafo ────────────────────────────────────────────────────

    def get_related_tags(self, tag_id: str, max_hops: int = 2) -> list[str]:
        """Retorna tags relacionados con el dado — para compresión de contexto."""
        node_id = self._tag_to_node.get(tag_id)
        if not node_id:
            return [tag_id]

        related_node_ids = {node_id}
        for _ in range(max_hops):
            new_ids = set()
            for edge in self._edges.values():
                if edge.source in related_node_ids:
                    new_ids.add(edge.target)
                if edge.target in related_node_ids:
                    new_ids.add(edge.source)
            related_node_ids |= new_ids

        related_tags = []
        for nid in related_node_ids:
            node = self._nodes.get(nid)
            if node:
                related_tags.extend(node.tags)

        return list(set(related_tags))

    def add_relation(
        self,
        tag_a: str,
        tag_b: str,
        relation_type: str,
        confidence: float,
    ) -> None:
        node_a = self._tag_to_node.get(tag_a)
        node_b = self._tag_to_node.get(tag_b)
        if not node_a or not node_b:
            return
        edge = ProcessEdge(
            id=str(uuid.uuid4()),
            source=node_a, target=node_b,
            relation_type=relation_type,
            confidence=confidence,
            correlation=0, lag_seconds=0,
            evidence="Añadida manualmente",
        )
        self._edges[edge.id] = edge
        self.save()

    def get_equipment_for_tag(self, tag_id: str) -> Optional[str]:
        node_id = self._tag_to_node.get(tag_id)
        if node_id and node_id in self._nodes:
            return self._nodes[node_id].name
        return None

    def answer_question(self, question_id: str, answer: str) -> None:
        """Procesa la respuesta del operario a una pregunta de validación."""
        for q in self._pending_questions:
            if q.id == question_id:
                q.answered = True
                q.answer = answer
                self._stats["questions_answered"] += 1

                # Actualiza la confianza del nodo basándose en la respuesta
                if "sí" in answer.lower() or "yes" in answer.lower():
                    # Confirma el grupo — aumenta confianza
                    for node in self._nodes.values():
                        if any(t in node.tags for t in q.related_tags):
                            node.confidence = min(1.0, node.confidence + 0.2)
                            node.validated_by_operator = True
                elif "no" in answer.lower():
                    # Niega el grupo — split del nodo
                    pass  # TODO: implementar split de nodos en fase 2

                self.save()
                break

    def add_question(self, question: "ProcessQuestion") -> None:
        """Añade una pregunta pendiente al grafo."""
        self._pending_questions.append(question)
        self.save()

    def get_pending_questions(self) -> list[ProcessQuestion]:
        return [q for q in self._pending_questions if not q.answered]

    def get_nodes(self) -> list[ProcessNode]:
        return list(self._nodes.values())

    def get_edges(self) -> list[ProcessEdge]:
        return list(self._edges.values())

    def get_summary(self) -> dict:
        return {
            **self._stats,
            "learning_phase": self._learning_phase,
            "pending_questions": len(self.get_pending_questions()),
            "avg_node_confidence": round(
                np.mean([n.confidence for n in self._nodes.values()]) if self._nodes else 0, 3
            ),
        }

    # ── Persistencia ──────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persiste el grafo como JSON."""
        self._update_stats()
        Path(self._graph_path).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "saved_at": datetime.now().isoformat(),
            "learning_phase": self._learning_phase,
            "nodes": {k: asdict(v) for k, v in self._nodes.items()},
            "edges": {k: asdict(v) for k, v in self._edges.items()},
            "tag_to_node": self._tag_to_node,
            "pending_questions": [asdict(q) for q in self._pending_questions],
            "stats": self._stats,
        }
        with open(self._graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> None:
        """Carga el grafo desde disco."""
        if not Path(self._graph_path).exists():
            return
        try:
            with open(self._graph_path, encoding="utf-8") as f:
                data = json.load(f)

            self._learning_phase = data.get("learning_phase", "initial")
            self._tag_to_node = data.get("tag_to_node", {})
            self._stats = data.get("stats", self._stats)

            for k, v in data.get("nodes", {}).items():
                self._nodes[k] = ProcessNode(**v)

            for k, v in data.get("edges", {}).items():
                self._edges[k] = ProcessEdge(**v)

            for q in data.get("pending_questions", []):
                self._pending_questions.append(ProcessQuestion(**q))

            print(f"[ProcessGraph] Grafo cargado: {len(self._nodes)} nodos, {len(self._edges)} aristas")
        except Exception as e:
            print(f"[ProcessGraph] Error cargando grafo: {e} — iniciando desde cero")

    def _update_stats(self) -> None:
        self._stats["nodes"] = len(self._nodes)
        self._stats["edges"] = len(self._edges)
        self._stats["questions_asked"] = len(self._pending_questions)
        self._stats["last_updated"] = datetime.now().isoformat()
