import asyncio
from datetime import datetime, timedelta
import json
from fastapi import FastAPI, Response, status, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from . import models
from .database import engine, get_db, SessionLocal

app = FastAPI()

class Monitor(BaseModel):
    id: str
    timeout: int
    alert_email: str

active_timers = {}

async def start_countdown(monitor_id: str, timeout_seconds: int):
    """
    Internal function that manages the countdown timer for each monitor.
    """
    try:
        if timeout_seconds > 0:
            await asyncio.sleep(timeout_seconds)
        
        db = SessionLocal()
        try:
            db_monitor = db.query(models.Monitors).filter(models.Monitors.id == monitor_id).first()
            if db_monitor and db_monitor.status == models.MonitorStatus.ACTIVE:
                db_monitor.status = models.MonitorStatus.DOWN
                db.commit()
                
                alert_payload = {
                    "ALERT": f"Device {monitor_id} is down!",
                    "time": datetime.utcnow().isoformat()
                }
                print(json.dumps(alert_payload), flush=True)
        finally:
            db.close()
    except asyncio.CancelledError:
        pass
    finally:
        active_timers.pop(monitor_id, None)

@app.on_event("startup")
async def startup_event():
    """
    Initializes the application on startup, 
    including creating the database tables and resuming any active monitors.
    """
    models.Base.metadata.create_all(bind=engine)
    
    # Resume timers for active monitors
    db = SessionLocal()
    try:
        active_monitors = db.query(models.Monitors).filter(models.Monitors.status == models.MonitorStatus.ACTIVE).all()
        for m in active_monitors:
            remaining_seconds = (m.expires_at - datetime.utcnow()).total_seconds()
            if remaining_seconds <= 0:
                asyncio.create_task(start_countdown(m.id, 0))
            else:
                asyncio.create_task(start_countdown(m.id, int(remaining_seconds)))
    finally:
        db.close()


@app.post("/monitor", status_code=status.HTTP_201_CREATED)
async def create_monitor(monitor: Monitor, db: Session = Depends(get_db)):
    """
    Creates a new monitor or updates an existing one.
    """
    expires_at = datetime.utcnow() + timedelta(seconds=monitor.timeout)
    
    # Cancel previous timer if it exists
    if monitor.id in active_timers:
        active_timers[monitor.id].cancel()
    
    existing = db.query(models.Monitors).filter(models.Monitors.id == monitor.id).first()
    if existing:
        existing.timeout = monitor.timeout
        existing.alert_email = monitor.alert_email
        existing.status = models.MonitorStatus.ACTIVE
        existing.expires_at = expires_at
        db.commit()
        db.refresh(existing)
        new_monitor = existing
    else:
        new_monitor = models.Monitors(
            id=monitor.id,
            timeout=monitor.timeout,
            alert_email=monitor.alert_email,
            status=models.MonitorStatus.ACTIVE,
            expires_at=expires_at
        )
        db.add(new_monitor)
        db.commit()
        db.refresh(new_monitor)
        
    # Start the asyncio task countdown
    task = asyncio.create_task(start_countdown(monitor.id, monitor.timeout))
    active_timers[monitor.id] = task
    
    return Response(status_code=status.HTTP_201_CREATED)


@app.post("/monitors/{id}/heartbeat")
async def heartbeat(id: str, db: Session = Depends(get_db)):
    """
    Updates the heartbeat of a monitor, effectively resetting its countdown timer.
    """
    monitor = db.query(models.Monitors).filter(models.Monitors.id == id).first()
    if not monitor:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    
    # Update the monitor's status and expires_at
    expires_at = datetime.utcnow() + timedelta(seconds=monitor.timeout)
    monitor.status = models.MonitorStatus.ACTIVE
    monitor.expires_at = expires_at
    db.commit()
    
    # Reset/restart the background timer task
    if id in active_timers:
        active_timers[id].cancel()
    task = asyncio.create_task(start_countdown(id, monitor.timeout))
    active_timers[id] = task
    
    return Response(status_code=status.HTTP_200_OK)


@app.post("/monitors/{id}/pause")
async def pause_monitor(id: str, db: Session = Depends(get_db)):
    """
    Pauses a monitor
    """
    monitor = db.query(models.Monitors).filter(models.Monitors.id == id).first()
    if not monitor:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    # Update the monitor's status
    monitor.status = models.MonitorStatus.PAUSED
    db.commit()
    
    # Cancel the background timer task
    if id in active_timers:
        active_timers[id].cancel()

    return Response(status_code=status.HTTP_200_OK)


@app.get("/monitors")
def get_monitors(db: Session = Depends(get_db)):
    """
    DEVELOPER'S CHOICE
    This endpoint should return a list of all monitors with their current status (active, down, paused) 
    and the time remaining until they are considered down (if active).
    """
    monitors = db.query(models.Monitors).all()
    return {"Monitors": monitors}

