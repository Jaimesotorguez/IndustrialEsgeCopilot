"""
adapters/modbus_adapter.py — M1: Adaptador Modbus TCP
======================================================
Conecta con máquinas legacy que usan protocolo Modbus TCP.
Cubre el ~60% del parque industrial antiguo.
"""

import asyncio
from datetime import datetime
from typing import Any, Optional

from backend.core.interfaces import DataSourceAdapter, SensorReading

try:
    from pymodbus.client import AsyncModbusTcpClient
    from pymodbus.exceptions import ModbusException
    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False
    print("[ModbusAdapter] pymodbus no instalado. pip install pymodbus")


class ModbusAdapter(DataSourceAdapter):
    """
    Adaptador Modbus TCP para máquinas industriales legacy.

    Lee registros holding (4xxxx) e input (3xxxx).
    Escribe en registros holding para comandos de control.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 502,
        slave_id: int = 1,
        polling_interval: int = 5,
        holding_registers: Optional[list[int]] = None,   # Registros a leer
        input_registers: Optional[list[int]] = None,
        register_names: Optional[dict[int, str]] = None, # {registro: nombre_tag}
        scale_factors: Optional[dict[int, float]] = None, # {registro: factor_escala}
    ):
        if not MODBUS_AVAILABLE:
            raise ImportError("pymodbus no instalado. pip install pymodbus")

        self._host = host
        self._port = port
        self._slave_id = slave_id
        self._polling_interval = polling_interval
        self._holding_regs = holding_registers or list(range(0, 50))
        self._input_regs = input_registers or []
        self._reg_names = register_names or {}
        self._scale_factors = scale_factors or {}
        self._client: Optional[AsyncModbusTcpClient] = None
        self._connected = False

    # ── DataSourceAdapter interface ───────────────────────────────────────────

    async def connect(self) -> bool:
        try:
            self._client = AsyncModbusTcpClient(host=self._host, port=self._port)
            result = await self._client.connect()
            if result:
                self._connected = True
                print(f"[ModbusAdapter] Conectado a {self._host}:{self._port}")
                return True
            print(f"[ModbusAdapter] No se pudo conectar a {self._host}:{self._port}")
            return False
        except Exception as e:
            print(f"[ModbusAdapter] Error: {e}")
            return False

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
        self._connected = False

    async def read(self) -> list[SensorReading]:
        if not self._connected or not self._client:
            return []

        readings = []
        now = datetime.now()

        # Lee holding registers
        if self._holding_regs:
            try:
                result = await self._client.read_holding_registers(
                    address=self._holding_regs[0],
                    count=len(self._holding_regs),
                    slave=self._slave_id,
                )
                if not result.isError():
                    for i, reg_addr in enumerate(self._holding_regs):
                        if i < len(result.registers):
                            raw_value = result.registers[i]
                            scale = self._scale_factors.get(reg_addr, 1.0)
                            value = raw_value * scale
                            tag_id = self._reg_names.get(reg_addr, f"HR_{reg_addr:04d}")
                            readings.append(SensorReading(
                                timestamp=now,
                                tag_id=tag_id,
                                value=value,
                                source="modbus",
                                quality=1.0,
                            ))
            except Exception as e:
                print(f"[ModbusAdapter] Error leyendo holding registers: {e}")

        # Lee input registers
        if self._input_regs:
            try:
                result = await self._client.read_input_registers(
                    address=self._input_regs[0],
                    count=len(self._input_regs),
                    slave=self._slave_id,
                )
                if not result.isError():
                    for i, reg_addr in enumerate(self._input_regs):
                        if i < len(result.registers):
                            raw_value = result.registers[i]
                            scale = self._scale_factors.get(reg_addr, 1.0)
                            tag_id = self._reg_names.get(reg_addr, f"IR_{reg_addr:04d}")
                            readings.append(SensorReading(
                                timestamp=now,
                                tag_id=tag_id,
                                value=raw_value * scale,
                                source="modbus",
                                quality=1.0,
                            ))
            except Exception as e:
                print(f"[ModbusAdapter] Error leyendo input registers: {e}")

        return readings

    async def write(self, tag_id: str, value: Any) -> bool:
        """Escribe en un holding register por nombre de tag o dirección."""
        if not self._connected or not self._client:
            return False

        # Busca la dirección del registro por nombre
        reg_addr = None
        for addr, name in self._reg_names.items():
            if name == tag_id:
                reg_addr = addr
                break

        # Si tag_id es directamente una dirección numérica
        if reg_addr is None:
            try:
                reg_addr = int(tag_id)
            except ValueError:
                print(f"[ModbusAdapter] Tag no encontrado: {tag_id}")
                return False

        try:
            scale = self._scale_factors.get(reg_addr, 1.0)
            raw_value = int(float(value) / scale) if scale != 0 else int(value)
            raw_value = max(0, min(65535, raw_value))  # Clipa a rango uint16

            result = await self._client.write_register(
                address=reg_addr,
                value=raw_value,
                slave=self._slave_id,
            )
            if not result.isError():
                print(f"[ModbusAdapter] WRITE: {tag_id} (reg {reg_addr}) = {value}")
                return True
            return False
        except Exception as e:
            print(f"[ModbusAdapter] Error escribiendo {tag_id}: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def source_name(self) -> str:
        return f"modbus:{self._host}:{self._port}"
