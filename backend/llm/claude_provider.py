"""
llm/claude_provider.py — LLM Provider: Claude (Anthropic)
==========================================================
Implementación de LLMProvider para Claude API.
Nunca llamar a anthropic directamente fuera de este archivo.

Incluye:
- Llamadas con contexto comprimido (RAG — solo lo relevante)
- Output JSON estructurado con validación Pydantic
- Tracking de tokens para control de coste
- Retry automático con backoff exponencial
"""

import json
import time
from typing import Any, Optional
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.interfaces import LLMProvider, LLMResponse
from backend.core.config import get_settings


class ClaudeProvider(LLMProvider):
    """
    Proveedor LLM usando Claude API (Anthropic).
    Implementa la interfaz LLMProvider — intercambiable con GPT, Gemini, etc.
    """

    def __init__(self):
        cfg = get_settings()
        api_key = cfg.llm.anthropic_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY no configurada. "
                "Añádela en config.yaml o como variable de entorno."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = cfg.llm.model
        self._max_tokens = cfg.llm.max_tokens
        self._temperature = cfg.llm.temperature
        self._token_usage = {"input": 0, "output": 0, "calls": 0}

    # ── LLMProvider interface ─────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """
        Llamada principal al LLM.
        El contexto se comprime antes de enviarse — nunca se manda todo.
        """
        import asyncio

        t0 = time.time()

        # Comprime el contexto — nunca mandamos el histórico completo
        compressed_context = self._compress_context(context)
        full_user_msg = self._build_user_message(user_message, compressed_context)

        # Claude API es síncrona — corremos en thread pool para no bloquear
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or self._max_tokens,
                temperature=self._temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": full_user_msg}],
            )
        )

        latency_ms = (time.time() - t0) * 1000
        text = response.content[0].text if response.content else ""

        # Tracking de coste
        self._token_usage["input"] += response.usage.input_tokens
        self._token_usage["output"] += response.usage.output_tokens
        self._token_usage["calls"] += 1

        return LLMResponse(
            text=text,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
            model_used=self._model,
            provider="claude",
            latency_ms=latency_ms,
        )

    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
        context: dict[str, Any],
        output_schema: dict,
    ) -> dict:
        """
        Llamada que garantiza output JSON válido.
        El schema se incluye en el prompt para que Claude lo respete.
        """
        schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)
        json_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANTE: Responde ÚNICAMENTE con JSON válido que siga exactamente este schema:\n"
            f"{schema_str}\n"
            f"Sin texto adicional, sin markdown, sin explicaciones. Solo el JSON."
        )

        response = await self.complete(json_system, user_message, context)

        try:
            # Limpia posibles backticks de markdown
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            print(f"[ClaudeProvider] Error parseando JSON: {e}\nRespuesta: {response.text[:200]}")
            return {}

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self._model

    # ── Métodos especializados ────────────────────────────────────────────────

    async def diagnose(
        self,
        anomaly_description: str,
        relevant_tags: list[str],
        tag_values: dict[str, float],
        tag_baselines: dict[str, dict],
        similar_past_events: list[dict],
        plant_config: dict,
    ) -> dict:
        """
        Genera un diagnóstico estructurado de una anomalía.
        Contexto comprimido: solo los tags relevantes, no todo el histórico.
        """
        system_prompt = f"""Eres un ingeniero industrial senior especializado en diagnóstico de fallos.
Analizas datos de sensores de una planta industrial y generas diagnósticos precisos y accionables.
La planta es del sector: {plant_config.get('sector', 'industrial')}.
Responde siempre en {plant_config.get('language', 'es')}.
Sé técnico, directo y accionable. Cuando no hay suficiente evidencia, dilo explícitamente."""

        context = {
            "anomalia": anomaly_description,
            "variables_implicadas": {
                tag: {
                    "valor_actual": tag_values.get(tag),
                    "media_normal": tag_baselines.get(tag, {}).get("mean"),
                    "std_normal": tag_baselines.get(tag, {}).get("std"),
                    "max_historico": tag_baselines.get(tag, {}).get("max"),
                }
                for tag in relevant_tags[:8]  # Máximo 8 variables en contexto
            },
            "eventos_similares_pasados": similar_past_events[:3],  # Máximo 3
        }

        schema = {
            "causa_probable": "string — descripción de la causa más probable",
            "confianza": "number — 0.0 a 1.0",
            "variables_implicadas": ["lista de tag_ids clave"],
            "urgencia": "integer — 1 (baja) a 5 (crítica)",
            "evidencia": ["lista de observaciones que soportan el diagnóstico"],
            "accion_recomendada": "string — qué hacer ahora mismo",
            "impacto_estimado": "string — consecuencias si no se actúa",
        }

        return await self.complete_json(system_prompt, "Genera el diagnóstico:", context, schema)

    async def generate_hypothesis(
        self,
        process_state: dict,
        recent_events: list[dict],
        known_relations: list[dict],
    ) -> list[dict]:
        """
        Genera hipótesis sobre el estado del proceso.
        Llamado por M5 cuando hay eventos pero sin diagnóstico claro aún.
        """
        system_prompt = """Eres un experto en análisis de procesos industriales.
Generas hipótesis sobre qué puede estar ocurriendo basándote en patrones de datos.
No afirmes sin evidencia — usa lenguaje de hipótesis: "podría ser", "es posible que".
Responde en español."""

        context = {
            "estado_proceso": process_state,
            "eventos_recientes": recent_events[:5],
            "relaciones_conocidas": known_relations[:10],
        }

        schema = {
            "hipotesis": [
                {
                    "descripcion": "string",
                    "confianza": "number 0-1",
                    "tags_involucrados": ["lista"],
                    "accion_sugerida": "string",
                }
            ]
        }

        result = await self.complete_json(
            system_prompt,
            "Genera las hipótesis más probables sobre el estado del proceso:",
            context,
            schema,
        )
        return result.get("hipotesis", [])

    async def answer_operator(
        self,
        question: str,
        plant_state: dict,
        conversation_history: list[dict],
    ) -> str:
        """
        Responde preguntas del operario en lenguaje natural (M11).
        Incluye el estado actual de la planta como contexto.
        """
        system_prompt = f"""Eres MindAgent, el copiloto IA de esta planta industrial.
Respondes preguntas del operario de forma técnica, directa y accionable.
Máximo 6 líneas por respuesta. Usa los datos reales de la planta.
Si no tienes suficiente información para responder con certeza, dilo claramente.
Idioma: {plant_state.get('language', 'español')}."""

        context = {"estado_planta": plant_state}
        full_msg = self._build_user_message(question, context)

        # Incluye historial de conversación (últimos 10 mensajes)
        messages = conversation_history[-10:] + [{"role": "user", "content": full_msg}]

        import asyncio
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.messages.create(
                model=self._model,
                max_tokens=600,
                system=system_prompt,
                messages=messages,
            )
        )

        self._token_usage["input"] += response.usage.input_tokens
        self._token_usage["output"] += response.usage.output_tokens
        self._token_usage["calls"] += 1

        return response.content[0].text if response.content else ""

    # ── Utilidades internas ───────────────────────────────────────────────────

    def _compress_context(self, context: dict, max_chars: int = 3000) -> dict:
        """
        Comprime el contexto para no mandar tokens innecesarios.
        Principio clave: nunca mandar el histórico completo — solo lo relevante.
        """
        compressed = {}
        for key, value in context.items():
            if isinstance(value, list) and len(value) > 10:
                # Trunca listas largas
                compressed[key] = value[:10]
            elif isinstance(value, dict) and len(str(value)) > 1000:
                # Trunca dicts muy grandes
                compressed[key] = dict(list(value.items())[:20])
            else:
                compressed[key] = value
        return compressed

    def _build_user_message(self, question: str, context: dict) -> str:
        """Construye el mensaje final incluyendo contexto comprimido."""
        if not context:
            return question
        ctx_str = json.dumps(context, ensure_ascii=False, default=str, indent=2)
        return f"CONTEXTO:\n{ctx_str}\n\nPREGUNTA/TAREA:\n{question}"

    def get_token_usage(self) -> dict:
        """Retorna el uso acumulado de tokens para monitorizar coste."""
        cfg = get_settings()
        # Precios aproximados Claude Sonnet (€/token)
        cost_input = self._token_usage["input"] * 0.000003
        cost_output = self._token_usage["output"] * 0.000015
        return {
            **self._token_usage,
            "estimated_cost_eur": round(cost_input + cost_output, 4),
        }
