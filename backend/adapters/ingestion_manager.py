"""
adapters/ingestion_manager.py — M1: Orquestador de fuentes de datos
====================================================================
Gestiona múltiples adaptadores simultáneos.
El resto del sistema habla siempre con este manager, nunca con los
adaptadores directamente. Añadir una nueva fuente = registrar un
nuevo adaptador aquí.
"""

import asyncio
from datetime import datetime
from typing import Callable, Optional

from backend.core.interfaces import DataSourceAdapter, SensorReading
from backend.core.config import get_settings


class IngestionManager:
    """
    Punto central de ingesta de datos.

    Uso:
        manager = IngestionManager()
        manager.register(CsvAdapter("simulator/data/"))
        await manager.start()

        # En tu bucle de observación:
        readings = await manager.read_all()
    """

    def __init__(self):
        self._adapters: list[DataSourceAdapter] = []
        self._running = False
        self._callbacks: list[Callable[[list[SensorReading]], None]] = []
        self._last_readings: list[SensorReading] = []
        self._stats = {
            "total_readings": 0,
            "errors": 0,
            "last_read_at": None,
            "adapters_connected": 0,
        }

    def register(self, adapter: DataSourceAdapter) -> None:
        """Registra un nuevo adaptador de fuente de datos."""
        self._adapters.append(adapter)
        print(f"[IngestionManager] Adaptador registrado: {adapter.source_name}")

    def on_readings(self, callback: Callable[[list[SensorReading]], None]) -> None:
        """
        Registra un callback que se llama cada vez que llegan nuevos datos.
        Uso: manager.on_readings(lambda readings: process(readings))
        """
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Conecta todos los adaptadores registrados."""
        results = await asyncio.gather(
            *[adapter.connect() for adapter in self._adapters],
            return_exceptions=True
        )
        connected = sum(1 for r in results if r is True)
        self._stats["adapters_connected"] = connected
        print(f"[IngestionManager] {connected}/{len(self._adapters)} adaptadores conectados")
        self._running = True

    async def stop(self) -> None:
        """Desconecta todos los adaptadores."""
        self._running = False
        await asyncio.gather(
            *[adapter.disconnect() for adapter in self._adapters],
            return_exceptions=True
        )
        print("[IngestionManager] Todos los adaptadores desconectados")

    async def read_all(self) -> list[SensorReading]:
        """
        Lee de todos los adaptadores conectados en paralelo.
        Retorna todas las lecturas combinadas.
        """
        if not self._adapters:
            return []

        results = await asyncio.gather(
            *[self._safe_read(adapter) for adapter in self._adapters],
            return_exceptions=True
        )

        all_readings: list[SensorReading] = []
        for result in results:
            if isinstance(result, list):
                all_readings.extend(result)
            elif isinstance(result, Exception):
                self._stats["errors"] += 1

        self._last_readings = all_readings
        self._stats["total_readings"] += len(all_readings)
        self._stats["last_read_at"] = datetime.now().isoformat()

        # Dispara callbacks
        if all_readings:
            for cb in self._callbacks:
                try:
                    cb(all_readings)
                except Exception as e:
                    print(f"[IngestionManager] Error en callback: {e}")

        return all_readings

    async def write(self, source_name: str, tag_id: str, value: float) -> bool:
        """
        Escribe un valor en un adaptador específico.
        Usado por el módulo de control (M10) para enviar comandos al PLC.
        """
        for adapter in self._adapters:
            if adapter.source_name == source_name and adapter.is_connected:
                return await adapter.write(tag_id, value)
        print(f"[IngestionManager] Adaptador no encontrado o desconectado: {source_name}")
        return False

    async def write_to_any(self, tag_id: str, value: float) -> bool:
        """Escribe en el primer adaptador conectado que acepte el tag."""
        for adapter in self._adapters:
            if adapter.is_connected:
                success = await adapter.write(tag_id, value)
                if success:
                    return True
        return False

    def get_status(self) -> dict:
        return {
            **self._stats,
            "adapters": [
                {
                    "name": a.source_name,
                    "connected": a.is_connected,
                }
                for a in self._adapters
            ],
        }

    def get_last_readings(self) -> list[SensorReading]:
        return self._last_readings

    def get_adapters_of_type(self, cls) -> list:
        """Retorna los adaptadores que son instancia del tipo dado."""
        return [a for a in self._adapters if isinstance(a, cls)]

    async def _safe_read(self, adapter: DataSourceAdapter) -> list[SensorReading]:
        """Lee con timeout y manejo de errores."""
        try:
            return await asyncio.wait_for(adapter.read(), timeout=10.0)
        except asyncio.TimeoutError:
            print(f"[IngestionManager] Timeout leyendo {adapter.source_name}")
            return []
        except Exception as e:
            print(f"[IngestionManager] Error leyendo {adapter.source_name}: {e}")
            return []


def build_ingestion_manager() -> IngestionManager:
    """
    Factory que construye el manager con los adaptadores
    configurados en config.yaml. Punto de entrada principal.
    """
    from backend.adapters.csv_adapter import CsvAdapter

    cfg = get_settings()
    manager = IngestionManager()

    # CSV (siempre disponible para desarrollo)
    if cfg.data_sources.csv.enabled:
        manager.register(CsvAdapter(
            path=cfg.data_sources.csv.path,
            polling_interval=cfg.data_sources.csv.polling_interval_seconds,
        ))

    # OPC-UA
    if cfg.data_sources.opcua.enabled:
        try:
            from backend.adapters.opcua_adapter import OpcUaAdapter
            manager.register(OpcUaAdapter(
                url=cfg.data_sources.opcua.url,
                username=cfg.data_sources.opcua.username,
                password=cfg.data_sources.opcua.password,
                polling_interval=cfg.data_sources.opcua.polling_interval_seconds,
            ))
        except ImportError:
            print("[IngestionManager] OPC-UA no disponible — instala asyncua")

    # Modbus
    if cfg.data_sources.modbus.enabled:
        try:
            from backend.adapters.modbus_adapter import ModbusAdapter
            manager.register(ModbusAdapter(
                host=cfg.data_sources.modbus.host,
                port=cfg.data_sources.modbus.port,
            ))
        except ImportError:
            print("[IngestionManager] Modbus no disponible — instala pymodbus")

    return manager
