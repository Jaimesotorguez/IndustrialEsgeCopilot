"""
adapters/opcua_adapter.py — M1: Adaptador OPC-UA
=================================================
Conecta con cualquier servidor OPC-UA (Factory I/O, PLCs reales, simuladores).
Usa asyncua — librería open source, sin dependencias propietarias.

Uso típico:
    adapter = OpcUaAdapter(url="opc.tcp://localhost:4840")
    await adapter.connect()
    readings = await adapter.read()
    await adapter.write("ns=2;i=1001", 75.0)  # Escribe en PLC
"""

import asyncio
from datetime import datetime
from typing import Any, Optional

from backend.core.interfaces import DataSourceAdapter, SensorReading

# asyncua se importa con guard para no romper si no está instalado
try:
    from asyncua import Client, Node
    from asyncua.common.subscription import Subscription
    OPCUA_AVAILABLE = True
except ImportError:
    OPCUA_AVAILABLE = False
    print("[OpcUaAdapter] asyncua no instalado. pip install asyncua")


class OpcUaAdapter(DataSourceAdapter):
    """
    Adaptador OPC-UA con soporte para:
    - Lectura por polling (modo por defecto)
    - Lectura por subscripción (más eficiente, push en vez de pull)
    - Escritura de valores en nodos del PLC
    - Autodescubrimiento de tags disponibles
    """

    def __init__(
        self,
        url: str = "opc.tcp://localhost:4840",
        username: Optional[str] = None,
        password: Optional[str] = None,
        polling_interval: int = 5,
        node_ids: Optional[list[str]] = None,  # None = autodescubrir
    ):
        if not OPCUA_AVAILABLE:
            raise ImportError("asyncua no está instalado. pip install asyncua")

        self._url = url
        self._username = username
        self._password = password
        self._polling_interval = polling_interval
        self._node_ids = node_ids or []
        self._client: Optional[Client] = None
        self._nodes: dict[str, Any] = {}  # node_id → Node object
        self._connected = False

    # ── DataSourceAdapter interface ───────────────────────────────────────────

    async def connect(self) -> bool:
        try:
            self._client = Client(url=self._url)
            if self._username:
                self._client.set_user(self._username)
                self._client.set_password(self._password or "")

            await self._client.connect()
            self._connected = True
            print(f"[OpcUaAdapter] Conectado a {self._url}")

            # Si no hay node_ids configurados, autodescubre
            if not self._node_ids:
                self._node_ids = await self._discover_nodes()
                print(f"[OpcUaAdapter] {len(self._node_ids)} nodos descubiertos")

            # Pre-carga referencias a los nodos
            for nid in self._node_ids:
                try:
                    self._nodes[nid] = self._client.get_node(nid)
                except Exception as e:
                    print(f"[OpcUaAdapter] Nodo no encontrado: {nid} — {e}")

            return True

        except Exception as e:
            print(f"[OpcUaAdapter] Error al conectar con {self._url}: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._client and self._connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._connected = False
        self._nodes = {}

    async def read(self) -> list[SensorReading]:
        """Lee todos los nodos configurados en paralelo."""
        if not self._connected or not self._nodes:
            return []

        readings = []
        now = datetime.now()

        # Lectura paralela de todos los nodos
        tasks = {nid: node.read_value() for nid, node in self._nodes.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for nid, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                continue
            try:
                readings.append(SensorReading(
                    timestamp=now,
                    tag_id=nid,
                    value=float(result),
                    source="opcua",
                    quality=1.0,
                ))
            except (TypeError, ValueError):
                continue  # Ignora valores no numéricos

        return readings

    async def write(self, tag_id: str, value: Any) -> bool:
        """
        Escribe un valor en un nodo OPC-UA.
        IMPORTANTE: El PLC tiene sus propias protecciones hardware.
        Esta escritura solo funciona si el nodo es writable.
        """
        if not self._connected:
            return False

        try:
            from asyncua.ua import DataValue, Variant
            node = self._client.get_node(tag_id)
            dv = DataValue(Variant(float(value)))
            await node.write_value(dv)
            print(f"[OpcUaAdapter] WRITE: {tag_id} = {value}")
            return True
        except Exception as e:
            print(f"[OpcUaAdapter] Error escribiendo {tag_id}: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def source_name(self) -> str:
        return f"opcua:{self._url}"

    # ── Utilidades ────────────────────────────────────────────────────────────

    async def _discover_nodes(self, max_nodes: int = 200) -> list[str]:
        """Autodescubre nodos numéricos en el servidor OPC-UA."""
        discovered = []
        try:
            root = self._client.get_root_node()
            objects = await root.get_child(["0:Objects"])
            children = await objects.get_children()

            for child in children[:max_nodes]:
                try:
                    nid = str(child.nodeid)
                    val = await child.read_value()
                    if isinstance(val, (int, float)):
                        discovered.append(nid)
                except Exception:
                    continue
        except Exception as e:
            print(f"[OpcUaAdapter] Error en autodescubrimiento: {e}")

        return discovered

    async def get_available_tags(self) -> list[str]:
        """Retorna los node_ids disponibles."""
        if not self._node_ids:
            self._node_ids = await self._discover_nodes()
        return self._node_ids
