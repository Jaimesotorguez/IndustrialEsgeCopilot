"""
recommender/recommender.py — M10: Recomendación y control
==========================================================
Genera acciones concretas a partir de diagnósticos (M9).
Gestiona el flujo: propuesta → aprobación humana → ejecución.
Toda escritura en PLC pasa por el validador de seguridad (M13).

Flujo de una acción:
  Diagnóstico → generate_actions() → status: PENDING
  Operario aprueba → execute() → escribe en PLC via M1
  Si fallo → status: FAILED + alerta
"""

import uuid
from datetime import datetime
from typing import Optional

from backend.core.interfaces import (
    ActionRecommender, ActionStatus, Diagnosis,
    RecommendedAction, Severity,
)
from backend.core.config import get_settings


# Plantillas de acciones por tipo de problema
# El LLM enriquece estas plantillas con el contexto real
ACTION_TEMPLATES = {
    "high_temperature": {
        "action_type": "COOLING_INCREASE",
        "risk_level": Severity.MEDIUM,
        "base_impact": "Reduce temperatura al rango normal en ~15 min",
    },
    "high_vibration": {
        "action_type": "RPM_REDUCE",
        "risk_level": Severity.MEDIUM,
        "base_impact": "Reduce vibración y riesgo de fallo mecánico",
    },
    "critical_pressure": {
        "action_type": "PRESSURE_REDUCE",
        "risk_level": Severity.HIGH,
        "base_impact": "Previene sobrepresión y posible fallo estructural",
    },
    "imminent_failure": {
        "action_type": "MACHINE_STOP",
        "risk_level": Severity.HIGH,
        "base_impact": "Parada controlada vs parada de emergencia no planificada",
    },
    "anomaly_general": {
        "action_type": "INCREASE_MONITORING",
        "risk_level": Severity.LOW,
        "base_impact": "Aumenta frecuencia de muestreo para seguimiento detallado",
    },
}

# Coste por hora de parada estimado por sector
DOWNTIME_COST_PER_HOUR = {
    "alimentacion": 8000,
    "farmaceutica": 25000,
    "automocion": 15000,
    "quimica": 12000,
    "general": 10000,
}


class ActionRecommenderImpl(ActionRecommender):
    """
    Genera y ejecuta recomendaciones de control.
    """

    def __init__(
        self,
        ingestion_manager=None,   # Para escribir en PLC
        validator=None,            # Validador de seguridad M13
        memory=None,               # Para guardar acciones M12
        llm=None,                  # Para enriquecer recomendaciones
    ):
        self._ingestion = ingestion_manager
        self._validator = validator
        self._memory = memory
        self._llm = llm
        self._pending: dict[str, RecommendedAction] = {}

    # ── ActionRecommender interface ───────────────────────────────────────────

    async def recommend(self, diagnosis: Diagnosis) -> list[RecommendedAction]:
        """
        Genera acciones concretas a partir de un diagnóstico.
        Si hay LLM disponible, lo usa para enriquecer las acciones.
        Sino, usa las plantillas base.
        """
        actions = []

        # Determina tipo de problema del diagnóstico
        action_template = self._select_template(diagnosis)

        if self._llm:
            # Enriquece con Claude para mayor precisión
            actions = await self._generate_with_llm(diagnosis, action_template)
        else:
            # Usa plantilla base
            actions = [self._build_from_template(diagnosis, action_template)]

        # Valida cada acción antes de añadirla a pendientes
        valid_actions = []
        for action in actions:
            if self._validator:
                is_valid, reason = self._validator.validate_action(action)
                if not is_valid:
                    print(f"[Recommender] Acción bloqueada por seguridad: {reason}")
                    continue
            valid_actions.append(action)
            self._pending[action.id] = action

            # Persiste en memoria
            if self._memory:
                self._memory.save_action(action, diagnosis_id=diagnosis.id)

        return valid_actions

    async def execute(self, action: RecommendedAction) -> bool:
        """
        Ejecuta una acción ya aprobada por el humano.
        Escribe en el PLC vía el adaptador correspondiente.
        """
        if action.status != ActionStatus.APPROVED:
            print(f"[Recommender] No se puede ejecutar acción en estado: {action.status.value}")
            return False

        # Segunda validación de seguridad en el momento de ejecución
        if self._validator:
            is_valid, reason = self._validator.validate_action(action)
            if not is_valid:
                action.status = ActionStatus.FAILED
                if self._memory:
                    self._memory.update_action_status(action.id, ActionStatus.FAILED)
                print(f"[Recommender] Ejecución bloqueada: {reason}")
                return False

        action.status = ActionStatus.EXECUTING

        # Ejecuta el comando en el PLC
        success = await self._execute_command(action)

        if success:
            action.status = ActionStatus.COMPLETED
            print(f"[Recommender] ✓ Acción ejecutada: {action.action_type} en {action.machine_id}")
        else:
            action.status = ActionStatus.FAILED
            print(f"[Recommender] ✗ Fallo al ejecutar: {action.action_type}")

        if self._memory:
            self._memory.update_action_status(
                action.id,
                action.status,
                approved_by=action.approved_by or "",
            )

        return success

    async def emergency_stop(self) -> None:
        """
        PARADA DE EMERGENCIA.
        Detiene toda escritura en PLCs inmediatamente.
        """
        print("[Recommender] 🛑 PARADA DE EMERGENCIA")

        # Activa el flag en el validador
        if self._validator:
            self._validator.set_emergency_stop(True)

        # Rechaza todos los pendientes
        for action in self._pending.values():
            if action.status == ActionStatus.PENDING:
                action.status = ActionStatus.REJECTED
                if self._memory:
                    self._memory.update_action_status(action.id, ActionStatus.REJECTED)

    # ── Métodos internos ──────────────────────────────────────────────────────

    def _select_template(self, diagnosis: Diagnosis) -> dict:
        """Selecciona la plantilla de acción más apropiada."""
        cause_lower = diagnosis.probable_cause.lower()

        if diagnosis.urgency >= 4:
            return ACTION_TEMPLATES["imminent_failure"]
        if any(x in cause_lower for x in ["temperatura", "temperature", "sobrecalent"]):
            return ACTION_TEMPLATES["high_temperature"]
        if any(x in cause_lower for x in ["vibraci", "vibration", "mecánico"]):
            return ACTION_TEMPLATES["high_vibration"]
        if any(x in cause_lower for x in ["presión", "pressure", "sobrepresion"]):
            return ACTION_TEMPLATES["critical_pressure"]

        return ACTION_TEMPLATES["anomaly_general"]

    def _build_from_template(
        self,
        diagnosis: Diagnosis,
        template: dict,
    ) -> RecommendedAction:
        """Construye acción desde plantilla sin LLM."""
        cfg = get_settings()
        downtime_cost = DOWNTIME_COST_PER_HOUR.get(cfg.plant.sector, 10000)
        estimated_saving = downtime_cost * (diagnosis.urgency / 5) * 2  # 2h de parada evitada

        machine_id = diagnosis.tags_involved[0].split("_")[0] if diagnosis.tags_involved else "UNKNOWN"

        return RecommendedAction(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            machine_id=machine_id,
            action_type=template["action_type"],
            parameters=self._default_parameters(template["action_type"]),
            reason=diagnosis.probable_cause[:200],
            estimated_impact=template["base_impact"],
            estimated_saving_eur=round(estimated_saving, 2),
            risk_level=template["risk_level"],
            status=ActionStatus.PENDING,
        )

    async def _generate_with_llm(
        self,
        diagnosis: Diagnosis,
        base_template: dict,
    ) -> list[RecommendedAction]:
        """Genera acciones enriquecidas con Claude."""
        try:
            cfg = get_settings()
            downtime_cost = DOWNTIME_COST_PER_HOUR.get(cfg.plant.sector, 10000)

            context = {
                "diagnostico": {
                    "causa": diagnosis.probable_cause,
                    "confianza": diagnosis.confidence,
                    "urgencia": diagnosis.urgency,
                    "variables": diagnosis.tags_involved[:5],
                    "evidencia": diagnosis.evidence[:3],
                },
                "coste_parada_hora_eur": downtime_cost,
                "accion_base_sugerida": base_template["action_type"],
            }

            schema = {
                "acciones": [
                    {
                        "accion_tipo": "string — RPM_REDUCE | COOLING_INCREASE | MACHINE_STOP | PRESSURE_REDUCE | INCREASE_MONITORING",
                        "maquina_id": "string",
                        "parametros": {"descripcion": "dict con parámetros específicos de la acción"},
                        "razon": "string — máx 150 chars",
                        "impacto_estimado": "string — máx 100 chars",
                        "ahorro_estimado_eur": "number",
                        "nivel_riesgo": "low | medium | high",
                    }
                ]
            }

            result = await self._llm.complete_json(
                system_prompt="Eres un sistema de control industrial. Genera acciones de control específicas y accionables. Sé conservador — mejor una acción segura que una acción perfecta arriesgada.",
                user_message="Genera las acciones de control recomendadas para este diagnóstico:",
                context=context,
                output_schema=schema,
            )

            actions = []
            for a in result.get("acciones", [])[:3]:  # Máximo 3 acciones por diagnóstico
                risk_map = {"low": Severity.LOW, "medium": Severity.MEDIUM, "high": Severity.HIGH}
                actions.append(RecommendedAction(
                    id=str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    machine_id=a.get("maquina_id", "UNKNOWN"),
                    action_type=a.get("accion_tipo", base_template["action_type"]),
                    parameters=a.get("parametros", {}),
                    reason=a.get("razon", "")[:200],
                    estimated_impact=a.get("impacto_estimado", ""),
                    estimated_saving_eur=float(a.get("ahorro_estimado_eur", 0)),
                    risk_level=risk_map.get(a.get("nivel_riesgo", "medium"), Severity.MEDIUM),
                    status=ActionStatus.PENDING,
                ))
            return actions

        except Exception as e:
            print(f"[Recommender] Error generando con LLM: {e} — usando plantilla base")
            return [self._build_from_template(diagnosis, base_template)]

    async def _execute_command(self, action: RecommendedAction) -> bool:
        """Escribe el comando en el PLC via el adaptador de ingesta."""
        if not self._ingestion:
            # En desarrollo sin PLC: simula éxito
            print(f"[Recommender] SIMULADO: {action.action_type} → {action.parameters}")
            return True

        try:
            # Mapea la acción a una escritura OPC-UA/Modbus concreta
            tag_id, value = self._action_to_plc_write(action)
            if tag_id:
                return await self._ingestion.write_to_any(tag_id, value)
            return True  # Acciones sin escritura directa (ej: INCREASE_MONITORING)
        except Exception as e:
            print(f"[Recommender] Error escribiendo en PLC: {e}")
            return False

    def _action_to_plc_write(self, action: RecommendedAction) -> tuple[Optional[str], float]:
        """Convierte una acción a una escritura de tag/valor en el PLC."""
        params = action.parameters
        action_type = action.action_type

        if action_type == "RPM_REDUCE":
            tag = params.get("rpm_tag") or f"{action.machine_id}_RPM_SETPOINT"
            new_rpm = params.get("target_rpm") or params.get("value", 0)
            return tag, float(new_rpm)

        if action_type == "COOLING_INCREASE":
            tag = params.get("cooling_tag") or f"{action.machine_id}_COOLING_VALVE"
            new_val = params.get("target_pct") or params.get("value", 80)
            return tag, float(new_val)

        if action_type == "MACHINE_STOP":
            tag = params.get("stop_tag") or f"{action.machine_id}_STOP_CMD"
            return tag, 1.0  # 1 = señal de parada

        if action_type == "PRESSURE_REDUCE":
            tag = params.get("pressure_tag") or f"{action.machine_id}_PRESSURE_SETPOINT"
            new_val = params.get("target_pct") or params.get("value", 70)
            return tag, float(new_val)

        return None, 0.0  # Sin escritura directa

    def _default_parameters(self, action_type: str) -> dict:
        defaults = {
            "RPM_REDUCE":         {"target_rpm": 800, "ramp_seconds": 30},
            "COOLING_INCREASE":   {"target_pct": 80, "ramp_seconds": 10},
            "PRESSURE_REDUCE":    {"target_pct": 70, "ramp_seconds": 20},
            "MACHINE_STOP":       {"mode": "controlled", "ramp_seconds": 60},
            "INCREASE_MONITORING": {"interval_seconds": 1},
        }
        return defaults.get(action_type, {})

    def get_pending(self) -> dict[str, RecommendedAction]:
        return {k: v for k, v in self._pending.items()
                if v.status == ActionStatus.PENDING}
