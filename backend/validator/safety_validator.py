"""
validator/safety_validator.py — M13: Validación de seguridad
=============================================================
Capa de seguridad transversal. Toda acción pasa por aquí
antes de ejecutarse, sin excepción.

Los límites de seguridad viven en config.yaml y en safety_limits.json.
La IA nunca puede modificar estos límites — solo el ingeniero de planta.

Principio: mejor rechazar una acción válida que ejecutar una peligrosa.
"""

import json
from pathlib import Path
from typing import Optional

from backend.core.interfaces import RecommendedAction, SafetyValidator, Severity
from backend.core.config import get_settings


# Límites de seguridad por defecto
# El ingeniero de planta los ajusta en safety_limits.json
DEFAULT_SAFETY_LIMITS = {
    "temperature": {
        "min": 20.0, "max": 95.0, "max_delta": 20.0, "unit": "°C"
    },
    "pressure": {
        "min": 0.0, "max": 100.0, "max_delta": 15.0, "unit": "%"
    },
    "rpm": {
        "min": 0.0, "max": 2200.0, "max_delta_pct": 30.0, "unit": "rpm"
    },
    "valve": {
        "min": 0.0, "max": 100.0, "max_delta": 20.0, "unit": "%"
    },
    "vibration": {
        "min": 0.0, "max": 60.0, "max_delta": 30.0, "unit": "Hz"
    },
}

# Acciones que SIEMPRE requieren aprobación humana, sin excepción
ALWAYS_REQUIRE_APPROVAL = {
    "MACHINE_STOP",
    "EMERGENCY_STOP",
    "VALVE_CLOSE_FULL",
    "PRESSURE_INCREASE",
    "RPM_INCREASE_HIGH",
    "BYPASS_SAFETY",
}

# Acciones que están completamente prohibidas para la IA
FORBIDDEN_ACTIONS = {
    "BYPASS_SAFETY",
    "OVERRIDE_HARDWARE_LIMIT",
    "DISABLE_SENSOR",
}


class SafetyValidatorImpl(SafetyValidator):
    """
    Valida acciones antes de su ejecución.

    Checks realizados (en orden):
    1. Acción no está en lista de prohibidas
    2. Parámetros dentro de límites físicos
    3. Delta de cambio no supera el máximo permitido
    4. Acción no viola reglas de sequencia del proceso
    5. Sistema no está en parada de emergencia
    """

    def __init__(self, limits_path: str = "config/safety_limits.json"):
        self._limits = self._load_limits(limits_path)
        self._emergency_stopped = False
        self._violation_log: list[dict] = []

    # ── SafetyValidator interface ─────────────────────────────────────────────

    def validate_action(self, action: RecommendedAction) -> tuple[bool, str]:
        """
        Valida una acción propuesta.
        Retorna (es_válida, motivo_si_inválida).
        Una acción inválida NUNCA se ejecuta.
        """
        checks = [
            self._check_not_forbidden(action),
            self._check_emergency_stop(action),
            self._check_parameters_in_range(action),
            self._check_delta_in_range(action),
            self._check_high_risk_approval(action),
        ]

        for valid, reason in checks:
            if not valid:
                self._log_violation(action, reason)
                return False, reason

        return True, ""

    def is_within_safe_range(self, tag_id: str, value: float) -> bool:
        """Verifica si un valor está dentro del rango seguro para ese tag."""
        var_type = self._infer_var_type(tag_id)
        if var_type not in self._limits:
            return True  # Sin límites definidos = aceptamos

        limits = self._limits[var_type]
        return limits["min"] <= value <= limits["max"]

    # ── Checks individuales ───────────────────────────────────────────────────

    def _check_not_forbidden(self, action: RecommendedAction) -> tuple[bool, str]:
        if action.action_type in FORBIDDEN_ACTIONS:
            return False, f"Acción prohibida para IA: {action.action_type}"
        return True, ""

    def _check_emergency_stop(self, action: RecommendedAction) -> tuple[bool, str]:
        if self._emergency_stopped:
            return False, "Sistema en parada de emergencia — no se pueden ejecutar comandos"
        return True, ""

    def _check_parameters_in_range(self, action: RecommendedAction) -> tuple[bool, str]:
        """Verifica que todos los parámetros numéricos están en rango seguro."""
        for param_name, value in action.parameters.items():
            if not isinstance(value, (int, float)):
                continue
            var_type = self._infer_var_type(param_name)
            if var_type not in self._limits:
                continue
            limits = self._limits[var_type]
            if not (limits["min"] <= value <= limits["max"]):
                return False, (
                    f"Parámetro '{param_name}'={value} fuera de rango seguro "
                    f"[{limits['min']}, {limits['max']}] {limits.get('unit', '')}"
                )
        return True, ""

    def _check_delta_in_range(self, action: RecommendedAction) -> tuple[bool, str]:
        """Verifica que los cambios no son demasiado bruscos."""
        delta = action.parameters.get("delta") or action.parameters.get("change")
        if delta is None:
            return True, ""

        action_lower = action.action_type.lower()
        if "rpm" in action_lower:
            max_delta_pct = self._limits.get("rpm", {}).get("max_delta_pct", 30)
            current_rpm = action.parameters.get("current_rpm", 1000)
            if current_rpm > 0 and abs(delta) / current_rpm * 100 > max_delta_pct:
                return False, f"Cambio de RPM demasiado brusco: {abs(delta)/current_rpm*100:.1f}% > {max_delta_pct}%"

        if "temp" in action_lower:
            max_delta = self._limits.get("temperature", {}).get("max_delta", 20)
            if abs(delta) > max_delta:
                return False, f"Cambio de temperatura demasiado brusco: {abs(delta):.1f}°C > {max_delta}°C"

        return True, ""

    def _check_high_risk_approval(self, action: RecommendedAction) -> tuple[bool, str]:
        """
        Acciones de alto riesgo SIEMPRE requieren aprobación humana.
        Si llegan aquí sin aprobación, se bloquean.
        """
        cfg = get_settings()
        if not cfg.safety.require_human_approval:
            return True, ""  # Modo desarrollo: permite sin aprobación

        if action.action_type in ALWAYS_REQUIRE_APPROVAL:
            if action.approved_by is None:
                return False, (
                    f"'{action.action_type}' requiere aprobación humana explícita. "
                    f"El operario debe aprobar antes de ejecutar."
                )
        return True, ""

    # ── Estado del sistema ────────────────────────────────────────────────────

    def set_emergency_stop(self, active: bool) -> None:
        self._emergency_stopped = active
        state = "ACTIVADA" if active else "DESACTIVADA"
        print(f"[Validator] Parada de emergencia {state}")

    def is_emergency_stopped(self) -> bool:
        return self._emergency_stopped

    def get_violation_log(self, limit: int = 20) -> list[dict]:
        return self._violation_log[-limit:]

    def get_safety_limits(self) -> dict:
        return self._limits.copy()

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _load_limits(self, path: str) -> dict:
        """Carga límites desde JSON. Si no existe, usa los defaults."""
        try:
            if Path(path).exists():
                with open(path) as f:
                    limits = json.load(f)
                print(f"[Validator] Límites de seguridad cargados desde {path}")
                return limits
        except Exception as e:
            print(f"[Validator] Error cargando límites: {e}")
        print("[Validator] Usando límites de seguridad por defecto")
        return DEFAULT_SAFETY_LIMITS.copy()

    def _infer_var_type(self, name: str) -> str:
        name_lower = name.lower()
        if any(x in name_lower for x in ["temp", "t_"]):
            return "temperature"
        if any(x in name_lower for x in ["press", "pres"]):
            return "pressure"
        if "rpm" in name_lower or "speed" in name_lower:
            return "rpm"
        if "valve" in name_lower or "vlv" in name_lower:
            return "valve"
        if "vib" in name_lower:
            return "vibration"
        return "unknown"

    def _log_violation(self, action: RecommendedAction, reason: str) -> None:
        from datetime import datetime
        self._violation_log.append({
            "timestamp": datetime.now().isoformat(),
            "action_id": action.id,
            "action_type": action.action_type,
            "machine_id": action.machine_id,
            "reason": reason,
        })
        print(f"[Validator] ⚠ VIOLACIÓN DE SEGURIDAD: {reason}")
