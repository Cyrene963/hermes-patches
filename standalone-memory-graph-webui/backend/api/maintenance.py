from fastapi import APIRouter, HTTPException, Body
from db import get_graph_service
from db.models import MemoryAccessLog
from db.namespace import get_namespace
from sqlalchemy import select, func, delete
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/orphans")
async def get_orphans():
    """
    Get all orphan memories (all have deprecated=True).
    
    - deprecated: old versions created by update_memory (migrated_to is set)
    - orphaned: node lost all paths, auto-deprecated (migrated_to is NULL)
    
    Includes migration target paths for deprecated memories so the human can see
    where the memory used to live without clicking into each one.
    """
    graph = get_graph_service()
    return await graph.get_all_orphan_memories()


@router.get("/orphans/{memory_id}")
async def get_orphan_detail(memory_id: int):
    """
    Get full detail of an orphan memory, including migration target's
    full content for diff comparison.
    """
    graph = get_graph_service()
    detail = await graph.get_orphan_detail(memory_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    return detail


@router.delete("/orphans/{memory_id}")
async def delete_orphan(memory_id: int):
    """
    Permanently delete an orphan memory.
    This action is irreversible. Repairs the version chain if applicable.
    
    Safety: requires deprecated=True; active memories are never deleted.
    """
    graph = get_graph_service()
    try:
        result = await graph.permanently_delete_memory(memory_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/access-logs/stats")
async def get_access_log_stats():
    """
    Get stats for access logs (total count, oldest record date) for the current namespace.
    """
    graph = get_graph_service()
    
    async with graph.session() as session:
        ns = get_namespace()
        count = await session.scalar(
            select(func.count(MemoryAccessLog.id))
            .where(MemoryAccessLog.namespace == ns)
        )
        oldest = await session.scalar(
            select(func.min(MemoryAccessLog.accessed_at))
            .where(MemoryAccessLog.namespace == ns)
        )
        
    return {
        "count": count or 0,
        "oldest": oldest.isoformat() if oldest else None
    }


class ClearLogsRequest(BaseModel):
    keep_days: Optional[int] = Field(default=None, ge=0, le=3650)

@router.delete("/access-logs")
async def clear_access_logs(req: ClearLogsRequest):
    """
    Clear access logs. If keep_days is provided, deletes logs older than X days.
    If keep_days is 0 or None, deletes all logs.
    """
    graph = get_graph_service()
    
    async with graph.session() as session:
        ns = get_namespace()
        stmt = delete(MemoryAccessLog).where(MemoryAccessLog.namespace == ns)
        
        if req.keep_days and req.keep_days > 0:
            cutoff = datetime.now() - timedelta(days=req.keep_days)
            stmt = stmt.where(MemoryAccessLog.accessed_at < cutoff)
            
        result = await session.execute(stmt)
        return {"deleted": result.rowcount}
