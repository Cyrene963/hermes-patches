from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class DiffRequest(BaseModel):
    text_a: str = Field(..., description="旧文本")
    text_b: str = Field(..., description="新文本")


class DiffResponse(BaseModel):
    diff_html: str = Field(..., description="HTML格式的diff")
    diff_unified: str = Field(..., description="unified格式的diff")
    summary: str = Field(..., description="变化摘要")


# ============ Review / Rollback ============

class ChangeInfo(BaseModel):
    """One affected URI in the changeset pool."""
    uri: str
    change_type: str  # "created", "modified", "deleted"


class PathChange(BaseModel):
    action: str  # "created", "deleted"
    uri: str
    namespace: str = ""


class GlossaryChange(BaseModel):
    action: str  # "created", "deleted"
    keyword: str


class UriDiff(BaseModel):
    """Diff between before-state and current DB state for one URI."""
    uri: str
    change_type: str
    action: str = "modified"
    before_content: Optional[str] = None
    current_content: Optional[str] = None
    before_meta: Optional[Dict[str, Any]] = None
    current_meta: Optional[Dict[str, Any]] = None
    path_changes: Optional[List[PathChange]] = None
    glossary_changes: Optional[List[GlossaryChange]] = None
    active_paths: Optional[List[str]] = None
    path_namespaces: Optional[Dict[str, List[str]]] = None
    has_changes: bool


class RollbackResponse(BaseModel):
    uri: str
    success: bool
    message: str


class ChangeGroup(BaseModel):
    node_uuid: str
    display_uri: str
    top_level_table: str
    action: str = "modified"
    row_count: int
    namespaces: Optional[List[str]] = None


class GroupRollbackResponse(BaseModel):
    node_uuid: str
    success: bool
    message: str
