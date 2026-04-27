"""
api/main.py — Servidor FastAPI (versión completa integrada)
===========================================================
Integra todos los módulos via AppContainer.
Expone REST + WebSocket para el dashboard.

Endpoints:
  GET  /api/status                          → estado completo del sistema
  GET  /api/readings                        → últimas lecturas de sensores
  GET  /api/events                          → últimos eventos de anomalías
  GET  /api/commands                        → comandos pendientes
  POST /api/commands/{id}/approve           → aprobar comando
  POST /api/commands/{id}/reject            → rechazar comando
  POST /api/emergency-stop                  → parada total
  POST /api/emergency-resume                → reanudar
  POST /api/chat                            → chat con el agente
  GET  /api/process-model                   → grafo de proceso aprendido
  GET  /api/process-model/question          → siguiente pregunta al operario
  POST /api/process-model/question/{id}/answer → responder pregunta
  GET  /api/history                         → log de auditoría
  GET  /api/config                          → configuración actual
  GET  /api/safety/limits                   → límites de seguridad
  WS   /ws                                  → WebSocket tiempo real
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pathlib

from backend.core.config import get_settings
from backend.core.interfaces import ActionStatus

# ── Estado global ─────────────────────────────────────────────────────────────
app_container = None
active_ws: list[WebSocket] = []


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_container
    print("[API] Arrancando Industrial Edge Copilot...")

    from backend.core.app import AppContainer
    app_container = await AppContainer.build()

    if app_container.observer:
        app_container.observer.on_anomaly(
            lambda e: asyncio.create_task(broadcast("anomaly", {
                "timestamp": e.timestamp.isoformat(),
                "score": round(e.anomaly_score, 3),
                "severity": e.severity.value,
                "description": e.description,
                "tag_ids": e.tag_ids[:5],
            }))
        )
        app_container.observer.on_readings(
            lambda readings: asyncio.create_task(broadcast("readings", {
                r.tag_id: round(r.value, 4) for r in readings[-30:]
            }))
        )

    await app_container.start()
    yield
    await app_container.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Industrial Edge Copilot", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Sirve frontend si existe
frontend_path = pathlib.Path("frontend/dist")
if frontend_path.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/app", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_ws.append(ws)
    try:
        if app_container:
            await ws.send_json({"type": "init", "data": app_container.get_full_status()})
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
                if data.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if ws in active_ws:
            active_ws.remove(ws)


async def broadcast(event_type: str, data: dict) -> None:
    if not active_ws:
        return
    msg = json.dumps({"type": event_type, "data": data, "ts": datetime.now().isoformat()})
    dead = []
    for ws in active_ws:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_ws.remove(ws)


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    if not app_container:
        return {"error": "Sistema no iniciado"}
    return app_container.get_full_status()


@app.get("/api/readings")
async def get_readings():
    if not app_container or not app_container.observer:
        return {"readings": {}}
    readings = app_container.observer.get_latest_readings()
    return {"readings": {
        tag: {"value": round(r.value, 4), "ts": r.timestamp.isoformat(), "quality": r.quality}
        for tag, r in readings.items()
    }}


@app.get("/api/events")
async def get_events(limit: int = 20):
    if not app_container or not app_container.observer:
        return {"events": []}
    events = app_container.observer.get_latest_events(limit=limit)
    return {"events": [
        {"timestamp": e.timestamp.isoformat(), "tag_ids": e.tag_ids,
         "score": round(e.anomaly_score, 3), "severity": e.severity.value,
         "description": e.description}
        for e in events
    ]}


# ── Comandos ──────────────────────────────────────────────────────────────────

@app.get("/api/commands")
async def get_commands():
    if not app_container or not app_container.recommender:
        return {"commands": []}
    pending = app_container.recommender.get_pending()
    return {"commands": [
        {"id": c.id, "machine_id": c.machine_id, "action_type": c.action_type,
         "reason": c.reason, "estimated_impact": c.estimated_impact,
         "estimated_saving_eur": c.estimated_saving_eur,
         "risk_level": c.risk_level.value, "status": c.status.value,
         "timestamp": c.timestamp.isoformat()}
        for c in pending.values()
    ]}


@app.post("/api/commands/{command_id}/approve")
async def approve_command(command_id: str, approved_by: str = "operator"):
    if app_container and app_container.validator:
        if app_container.validator.is_emergency_stopped():
            raise HTTPException(423, "Sistema en parada de emergencia")
    if not app_container or not app_container.recommender:
        raise HTTPException(503, "No disponible")
    pending = app_container.recommender.get_pending()
    cmd = pending.get(command_id)
    if not cmd:
        raise HTTPException(404, "Comando no encontrado")
    cmd.status = ActionStatus.APPROVED
    cmd.approved_by = approved_by
    cmd.approved_at = datetime.now()
    success = await app_container.recommender.execute(cmd)
    await broadcast("command_update", {"id": command_id, "status": cmd.status.value})
    return {"status": cmd.status.value, "success": success}


@app.post("/api/commands/{command_id}/reject")
async def reject_command(command_id: str):
    if not app_container or not app_container.recommender:
        raise HTTPException(503)
    pending = app_container.recommender.get_pending()
    cmd = pending.get(command_id)
    if not cmd:
        raise HTTPException(404)
    cmd.status = ActionStatus.REJECTED
    if app_container.memory:
        app_container.memory.update_action_status(command_id, ActionStatus.REJECTED)
    await broadcast("command_update", {"id": command_id, "status": "rejected"})
    return {"status": "rejected"}


# ── Emergencia ────────────────────────────────────────────────────────────────

@app.post("/api/emergency-stop")
async def emergency_stop():
    if app_container:
        if app_container.validator:
            app_container.validator.set_emergency_stop(True)
        if app_container.recommender:
            await app_container.recommender.emergency_stop()
    await broadcast("emergency", {"active": True})
    return {"status": "emergency_stop_active"}


@app.post("/api/emergency-resume")
async def emergency_resume():
    if app_container and app_container.validator:
        app_container.validator.set_emergency_stop(False)
    await broadcast("emergency", {"active": False})
    return {"status": "resumed"}


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "Mensaje vacío")
    if not app_container or not app_container.llm:
        return {"response": "⚠ Agente IA no disponible. Configura ANTHROPIC_API_KEY.", "ts": datetime.now().isoformat()}

    plant_state = {}
    if app_container.observer:
        readings = app_container.observer.get_latest_readings()
        events = app_container.observer.get_latest_events(5)
        plant_state = {
            "n_sensores": len(readings),
            "anomalias_recientes": len(events),
            "ultima_anomalia": events[-1].description if events else None,
            "emergency": app_container.validator.is_emergency_stopped() if app_container.validator else False,
        }

    history = app_container.memory.get_recent_interactions(10) if app_container.memory else []

    response = await app_container.llm.answer_operator(
        question=req.message,
        plant_state=plant_state,
        conversation_history=history,
    )

    if app_container.memory:
        app_container.memory.save_interaction("user", req.message)
        app_container.memory.save_interaction("agent", response)

    return {"response": response, "ts": datetime.now().isoformat()}


# ── Modelo de proceso ─────────────────────────────────────────────────────────

@app.get("/api/process-model")
async def get_process_model():
    if not app_container or not app_container.process_graph:
        return {"nodes": [], "edges": [], "summary": {}}
    g = app_container.process_graph
    return {
        "nodes": [{"id": n.id, "name": n.name, "type": n.node_type,
                   "tags": n.tags, "confidence": n.confidence,
                   "validated": n.validated_by_operator} for n in g.get_nodes()],
        "edges": [{"id": e.id, "source": e.source, "target": e.target,
                   "relation": e.relation_type, "confidence": e.confidence,
                   "correlation": e.correlation} for e in g.get_edges()],
        "summary": g.get_summary(),
    }


@app.get("/api/process-model/question")
async def get_next_question():
    if not app_container or not app_container.interaction:
        return {"question": None}
    q = app_container.interaction.get_next_question()
    if not q:
        return {"question": None}
    return {"question": {"id": q.id, "question": q.question,
                         "options": q.options, "related_tags": q.related_tags}}


class AnswerRequest(BaseModel):
    answer: str


@app.post("/api/process-model/question/{question_id}/answer")
async def answer_question(question_id: str, req: AnswerRequest):
    if not app_container or not app_container.interaction:
        raise HTTPException(503)
    result = app_container.interaction.submit_answer(question_id, req.answer)
    await broadcast("model_updated", {"type": "question_answered"})
    return result


# ── Historial ─────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history(limit: int = 50):
    if not app_container or not app_container.memory:
        return {"history": []}
    return {"history": app_container.memory.get_audit_log(limit=limit)}


@app.get("/api/memory/stats")
async def get_memory_stats():
    if not app_container or not app_container.memory:
        return {}
    return app_container.memory.get_stats()


# ── Config y seguridad ────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    cfg = get_settings()
    return {
        "plant": {"name": cfg.plant.name, "sector": cfg.plant.sector, "language": cfg.plant.language},
        "llm": {"provider": cfg.llm.provider, "model": cfg.llm.model},
        "observer": {"interval": cfg.observer.polling_interval_seconds, "threshold": cfg.observer.anomaly_threshold},
        "safety": {"require_approval": cfg.safety.require_human_approval},
    }


@app.get("/api/safety/limits")
async def get_safety_limits():
    if not app_container or not app_container.validator:
        return {}
    return app_container.validator.get_safety_limits()


@app.get("/api/safety/violations")
async def get_violations():
    if not app_container or not app_container.validator:
        return {"violations": []}
    return {"violations": app_container.validator.get_violation_log()}


# ── Arranque directo ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    cfg = get_settings()
    uvicorn.run("backend.api.main:app", host=cfg.server.host, port=cfg.server.port,
                reload=cfg.server.debug, log_level="info")
