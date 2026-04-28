"""
inference/hypothesis_engine.py — Motor iterativo de hipótesis
=============================================================
Reemplaza el diagnóstico one-shot con un bucle de razonamiento:
    generar hipótesis (LLM) → testear con Python (€0) →
    puntuar → aceptar/rechazar → iterar hasta convergencia

Coste: 1 llamada LLM por iteración (típicamente 1-3 iteraciones).
       Las pruebas de hipótesis son 100% Python → €0.

Uso standalone:
    python -m backend.inference.hypothesis_engine

Integraciones:
    - ReasoningEngine llama a HypothesisEngine.run() en lugar de LLM directo
    - Phase2Learn usa HypothesisEngine para aprender del histórico
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np


# ── Tipos de datos ────────────────────────────────────────────────────────────

@dataclass
class HypothesisResult:
    """Resultado de evaluar una hipótesis individual contra datos reales."""
    hypothesis: str
    score: float           # 0-1: evidencia estadística que la soporta
    evidence_for: list = field(default_factory=list)
    evidence_against: list = field(default_factory=list)
    accepted: bool = False
    rejected: bool = False


@dataclass
class InferenceResult:
    """Resultado completo del motor iterativo de hipótesis."""
    accepted: list
    rejected: list
    uncertain: list
    n_iterations: int
    converged: bool
    summary: str
    question_for_operator: Optional[str] = None
    tokens_used: int = 0


# ── Motor principal ───────────────────────────────────────────────────────────

class HypothesisEngine:
    """
    Motor iterativo de hipótesis para diagnóstico industrial.

    Garantías:
    - Nunca acepta una hipótesis sin evidencia estadística Python
    - Siempre explica qué evidencia soporta cada conclusión
    - Si no converge, pregunta al operario en lugar de inventar
    """

    ACCEPT_THRESHOLD = 0.65
    REJECT_THRESHOLD = 0.25

    def __init__(self, llm=None, process_graph=None):
        self._llm = llm
        self._graph = process_graph
        self._validated_history: list[dict] = []   # Aprendizaje cross-sesión

    async def run(
        self,
        features: dict,
        df_current=None,
        context: Optional[dict] = None,
        max_iterations: int = 4,
    ) -> InferenceResult:
        """
        Bucle principal de inferencia iterativa.

        Args:
            features   : Output de FeatureExtractor.extract()
            df_current : DataFrame wide con los datos actuales (para tests estadísticos)
            context    : Descripción anomalía, config planta, etc.
            max_iterations: Límite para evitar loops infinitos
        """
        context = context or {}
        all_accepted: list[HypothesisResult] = []
        all_rejected: list[HypothesisResult] = []
        refuted_descriptions: list[str] = []
        tokens_total = 0

        for iteration in range(max_iterations):
            # ── 1. Generar hipótesis ──────────────────────────────────────────
            candidates = await self._generate_hypotheses(
                features=features,
                context=context,
                refuted=refuted_descriptions,
                iteration=iteration,
            )
            if not candidates:
                break

            tokens_total += sum(h.get("_tokens", 0) for h in candidates)

            # ── 2. Evaluar cada hipótesis con Python puro (€0) ────────────────
            results = [
                self._evaluate_hypothesis(h["description"], features, df_current)
                for h in candidates
            ]

            # ── 3. Clasificar ─────────────────────────────────────────────────
            accepted_iter = [r for r in results if r.score >= self.ACCEPT_THRESHOLD]
            rejected_iter = [r for r in results if r.score <= self.REJECT_THRESHOLD]
            uncertain_iter = [
                r for r in results
                if self.REJECT_THRESHOLD < r.score < self.ACCEPT_THRESHOLD
            ]

            all_accepted.extend(accepted_iter)
            all_rejected.extend(rejected_iter)
            refuted_descriptions.extend(r.hypothesis for r in rejected_iter)

            print(
                f"[HypothesisEngine] Iter {iteration+1}/{max_iterations}: "
                f"{len(accepted_iter)} aceptadas, {len(rejected_iter)} rechazadas, "
                f"{len(uncertain_iter)} inciertas"
            )

            # ── 4. Criterio de convergencia ───────────────────────────────────
            if accepted_iter or (not uncertain_iter and rejected_iter):
                return self._build_result(
                    all_accepted, all_rejected, uncertain_iter,
                    n_iterations=iteration + 1,
                    converged=bool(accepted_iter),
                    tokens=tokens_total,
                    features=features,
                )

        # Sin convergencia → preguntar al operario
        return self._build_result(
            all_accepted, all_rejected, [],
            n_iterations=max_iterations,
            converged=False,
            tokens=tokens_total,
            features=features,
        )

    # ── Generación de hipótesis ───────────────────────────────────────────────

    async def _generate_hypotheses(
        self,
        features: dict,
        context: dict,
        refuted: list,
        iteration: int,
    ) -> list[dict]:
        """Con LLM: hipótesis semánticas. Sin LLM: hipótesis heurísticas."""
        if not self._llm:
            return self._heuristic_hypotheses(features)

        variables_criticas = [
            tag for tag, feat in features.get("variables", {}).items()
            if feat.get("estado") in ("atipico", "critico")
            or abs(feat.get("zscore_vs_baseline", 0)) > 2
        ]

        prompt_context = {
            "variables_anomalas": variables_criticas[:8],
            "correlaciones_fuertes": features.get("correlaciones_fuertes", [])[:5],
            "lags_causales": features.get("lags_causales", [])[:3],
            "hipotesis_ya_descartadas": refuted,
            "iteracion": iteration + 1,
            "contexto_extra": context,
        }

        system = (
            "Eres un experto en diagnóstico de procesos industriales. "
            "Genera hipótesis concretas y falsificables sobre la causa raíz "
            "de las anomalías. Cada hipótesis debe nombrar variables específicas "
            "y relaciones causales medibles. NO repitas hipótesis ya descartadas."
        )

        schema = {
            "type": "object",
            "properties": {
                "hipotesis": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "descripcion": {"type": "string"},
                            "tags_implicados": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "relacion_causal": {"type": "string"},
                        },
                        "required": ["descripcion", "tags_implicados"],
                    },
                }
            },
        }

        try:
            result = await self._llm.complete_json(
                system_prompt=system,
                user_message=(
                    "Genera hipótesis de causa raíz para estas anomalías industriales."
                ),
                context=prompt_context,
                output_schema=schema,
            )
            return [
                {
                    "description": h.get("descripcion", ""),
                    "tags": h.get("tags_implicados", []),
                    "causal": h.get("relacion_causal", ""),
                }
                for h in result.get("hipotesis", [])
                if h.get("descripcion")
            ]
        except Exception as e:
            print(f"[HypothesisEngine] LLM error: {e}, usando heurísticas")
            return self._heuristic_hypotheses(features)

    def _heuristic_hypotheses(self, features: dict) -> list[dict]:
        """Hipótesis sin LLM basadas en estadísticas de los features."""
        hypotheses = []
        variables = features.get("variables", {})
        correlaciones = features.get("correlaciones_fuertes", [])
        lags = features.get("lags_causales", [])

        # H1: Variable con mayor zscore
        criticas = sorted(
            [
                (tag, feat)
                for tag, feat in variables.items()
                if abs(feat.get("zscore_vs_baseline", 0)) > 2
            ],
            key=lambda x: abs(x[1].get("zscore_vs_baseline", 0)),
            reverse=True,
        )
        if criticas:
            tag, feat = criticas[0]
            z = feat.get("zscore_vs_baseline", 0)
            hypotheses.append({
                "description": (
                    f"{tag} está {'por encima' if z > 0 else 'por debajo'} "
                    f"de su valor normal (zscore={z:.1f}), posible causa raíz"
                ),
                "tags": [tag],
            })

        # H2: Lag causal más fuerte
        if lags:
            lag = lags[0]
            hypotheses.append({
                "description": (
                    f"{lag['causa']} causa cambios en {lag['efecto']} "
                    f"con {lag['lag_muestras']} muestras de retardo"
                ),
                "tags": [lag["causa"], lag["efecto"]],
            })

        # H3: Correlación rota (par normalmente acoplado ahora diverge)
        for corr in correlaciones[:3]:
            a, b = corr["variables"]
            za = variables.get(a, {}).get("zscore_vs_baseline", 0)
            zb = variables.get(b, {}).get("zscore_vs_baseline", 0)
            if abs(za - zb) > 3:
                hypotheses.append({
                    "description": (
                        f"{a} y {b} normalmente correlacionan "
                        f"({corr['correlacion']:.2f}) pero divergen ahora "
                        f"(Δzscore={abs(za - zb):.1f}). Posible fallo intermedio."
                    ),
                    "tags": [a, b],
                })
                break

        return hypotheses[:3]

    # ── Evaluación Python pura (€0) ───────────────────────────────────────────

    def _evaluate_hypothesis(
        self,
        hypothesis: str,
        features: dict,
        df=None,
    ) -> HypothesisResult:
        """
        Puntúa una hipótesis contra evidencia estadística real.
        Score 0-1 basado en zscore, correlaciones, lags, tendencias.
        """
        evidence_for: list[str] = []
        evidence_against: list[str] = []
        scores: list[float] = []

        variables = features.get("variables", {})
        correlaciones = features.get("correlaciones_fuertes", [])
        lags = features.get("lags_causales", [])
        hyp = hypothesis.lower()

        # Evidencia 1: Zscores de variables mencionadas
        for tag, feat in variables.items():
            if tag.lower() not in hyp:
                continue
            z = feat.get("zscore_vs_baseline", 0)
            estado = feat.get("estado", "sin_baseline")
            if estado in ("atipico", "critico") or abs(z) > 2:
                evidence_for.append(f"{tag}: zscore={z:.1f} ({estado})")
                scores.append(min(abs(z) / 4.0, 1.0))
            elif abs(z) < 1:
                evidence_against.append(f"{tag}: normal (zscore={z:.1f})")
                scores.append(0.1)

        # Evidencia 2: Correlaciones entre pares mencionados
        for corr in correlaciones:
            a, b = corr["variables"]
            if a.lower() in hyp and b.lower() in hyp:
                evidence_for.append(
                    f"{a}↔{b}: corr={corr['correlacion']:.2f} ({corr['tipo']})"
                )
                scores.append(abs(corr["correlacion"]))

        # Evidencia 3: Lags causales mencionados
        for lag in lags:
            if lag["causa"].lower() in hyp and lag["efecto"].lower() in hyp:
                evidence_for.append(
                    f"{lag['causa']}→{lag['efecto']}: "
                    f"lag={lag['lag_muestras']} muestras, "
                    f"corr={lag['correlacion_con_lag']:.2f}"
                )
                scores.append(abs(lag["correlacion_con_lag"]))

        # Evidencia 4: Tendencias consistentes
        for tag, feat in variables.items():
            if tag.lower() in hyp and feat.get("tendencia", "estable") != "estable":
                evidence_for.append(
                    f"{tag}: {feat['tendencia']} "
                    f"(pendiente={feat.get('pendiente', 0):.4f})"
                )
                scores.append(0.4)

        # Score final
        if not scores:
            final_score = 0.2
            evidence_against.append(
                "Ninguna variable mencionada encontrada en los features"
            )
        else:
            final_score = float(np.mean(scores))
            if len(evidence_against) > len(evidence_for):
                final_score *= 0.6

        return HypothesisResult(
            hypothesis=hypothesis,
            score=round(final_score, 3),
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            accepted=final_score >= self.ACCEPT_THRESHOLD,
            rejected=final_score <= self.REJECT_THRESHOLD,
        )

    # ── Construcción resultado final ──────────────────────────────────────────

    def _build_result(
        self,
        accepted: list,
        rejected: list,
        uncertain: list,
        n_iterations: int,
        converged: bool,
        tokens: int,
        features: dict,
    ) -> InferenceResult:
        if accepted:
            top = max(accepted, key=lambda x: x.score)
            summary = (
                f"Causa más probable: {top.hypothesis} "
                f"(score={top.score:.2f}"
                + (f", evidencia: {', '.join(top.evidence_for[:2])}" if top.evidence_for else "")
                + ")"
            )
        elif uncertain:
            summary = (
                f"Diagnóstico incierto tras {n_iterations} iteraciones. "
                f"Hipótesis sin confirmar: {uncertain[0].hypothesis}"
            )
        else:
            summary = (
                f"No se encontró causa raíz clara en {n_iterations} iteraciones."
            )

        question = None
        if not converged or uncertain:
            question = self._generate_operator_question(features, accepted, uncertain)

        # Persiste hipótesis aceptadas para aprendizaje futuro
        for h in accepted:
            self._validated_history.append({
                "hypothesis": h.hypothesis,
                "score": h.score,
                "evidence": h.evidence_for,
                "timestamp": datetime.now().isoformat(),
            })

        return InferenceResult(
            accepted=accepted,
            rejected=rejected,
            uncertain=uncertain,
            n_iterations=n_iterations,
            converged=converged,
            summary=summary,
            question_for_operator=question,
            tokens_used=tokens,
        )

    def _generate_operator_question(
        self,
        features: dict,
        accepted: list,
        uncertain: list,
    ) -> str:
        variables = features.get("variables", {})
        # Variable anómala sin baseline: el operario puede saber si es normal
        no_baseline = [
            (tag, feat)
            for tag, feat in variables.items()
            if "zscore_vs_baseline" not in feat
            and feat.get("tendencia", "estable") != "estable"
        ]
        if no_baseline:
            tag, feat = no_baseline[0]
            return (
                f"La variable {tag} muestra tendencia {feat['tendencia']} "
                f"(valor actual: {feat['valor_actual']:.3f}). "
                f"¿Es esto esperado en las condiciones actuales de operación?"
            )
        if uncertain:
            return (
                f"¿Puede confirmar o descartar la siguiente situación? "
                f"{uncertain[0].hypothesis}"
            )
        return (
            "¿Hay alguna operación o cambio reciente que pueda explicar "
            "las anomalías detectadas?"
        )

    def get_validated_history(self) -> list[dict]:
        """Devuelve hipótesis aceptadas en sesiones previas (aprendizaje)."""
        return list(self._validated_history)


# ── Ejecución standalone ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import pandas as pd
    import sys

    sys.path.insert(0, ".")
    from backend.analytics.feature_extractor import FeatureExtractor

    path = sys.argv[1] if len(sys.argv) > 1 else "simulator/data/tep_normal.csv"
    print(f"[HypothesisEngine] Cargando {path}...")

    df = pd.read_csv(path)
    extractor = FeatureExtractor()
    features = extractor.extract(df, top_n=15)

    engine = HypothesisEngine(llm=None)

    result = asyncio.run(engine.run(features, df_current=df, max_iterations=3))

    print(f"\n── Resultado ({result.n_iterations} iteraciones) ────────────────")
    print(f"  Convergió: {result.converged}")
    print(f"  Resumen  : {result.summary}")

    print(f"\n── Hipótesis aceptadas ({len(result.accepted)}) ─────────────────")
    for h in result.accepted:
        print(f"  [{h.score:.2f}] {h.hypothesis}")
        for e in h.evidence_for:
            print(f"         + {e}")

    print(f"\n── Hipótesis rechazadas ({len(result.rejected)}) ────────────────")
    for h in result.rejected:
        print(f"  [{h.score:.2f}] {h.hypothesis}")

    if result.question_for_operator:
        print(f"\n── Pregunta al operario ─────────────────────────────────────")
        print(f"  {result.question_for_operator}")

    print("\n[OK] HypothesisEngine completado")
