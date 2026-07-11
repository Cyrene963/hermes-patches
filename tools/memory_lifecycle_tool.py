"""Authorized leaf-memory deletion and rollback tools."""

from __future__ import annotations

import json
from agent.memory_lifecycle import MemoryLifecycleManager, load_delete_grant_authority
from tools.registry import registry
from tools import memory_graph_tool

_TOOLSET = "memory_graph"


def _json(raw):
    data=json.loads(raw)
    return None if isinstance(data,dict) and data.get("error") else data


def _manager(namespace):
    def read(uri,ns): return _json(memory_graph_tool._read({"uri":uri,"namespace":ns}))
    def children(uri,ns):
        data=_json(memory_graph_tool._list({"uri":uri,"namespace":ns})) or {}
        return list(data.get("children") or [])
    def delete(uri,ns):
        data=_json(memory_graph_tool._delete({"uri":uri,"namespace":ns})) or {}
        return bool(data.get("deleted"))
    def create(domain,parent,title,content,priority):
        return _json(memory_graph_tool._create({"domain":domain,"parent_uri":f"{domain}://{parent}" if parent else "","title":title,"content":content,"priority":priority,"namespace":namespace})) or {}
    def update(uri,ns,content,priority):
        return _json(memory_graph_tool._update({"uri":uri,"namespace":ns,"content":content,"priority":priority})) or {}
    return MemoryLifecycleManager(read=read,children=children,delete=delete,create=create,update=update)


DELETE_SCHEMA={"name":"memory_lifecycle_delete","description":"Delete exactly one leaf memory using a short-lived host-signed grant issued from the current explicit user request. Never recursively deletes subtrees.","parameters":{"type":"object","properties":{"uri":{"type":"string"},"namespace":{"type":"string"},"delete_grant":{"type":"string"},"candidate_count":{"type":"integer"}},"required":["uri","namespace","delete_grant","candidate_count"],"additionalProperties":False}}
ROLLBACK_SCHEMA={"name":"memory_lifecycle_rollback","description":"Idempotently restore a memory deleted through memory_lifecycle_delete, scoped to its original namespace.","parameters":{"type":"object","properties":{"changeset_id":{"type":"string"},"namespace":{"type":"string"}},"required":["changeset_id","namespace"],"additionalProperties":False}}


def _delete(args,**kw):
    ns=str(args.get("namespace") or "")
    grant = load_delete_grant_authority().consume(str(args.get("delete_grant") or ""), uri=str(args.get("uri") or ""), namespace=ns)
    if not grant.get("ok"):
        return json.dumps({"ok":False,"error":grant.get("error")},ensure_ascii=False)
    req={**args,"authorization_evidence":grant["message_sha256"],"source":"user_direct","explicit_user_authorization":True}
    return json.dumps(_manager(ns).delete_leaf(req),ensure_ascii=False)


def _rollback(args,**kw):
    ns=str(args.get("namespace") or "")
    return json.dumps(_manager(ns).rollback(changeset_id=str(args["changeset_id"]),namespace=ns),ensure_ascii=False)


registry.register(name="memory_lifecycle_delete",toolset=_TOOLSET,schema=DELETE_SCHEMA,handler=_delete,description=DELETE_SCHEMA["description"])
registry.register(name="memory_lifecycle_rollback",toolset=_TOOLSET,schema=ROLLBACK_SCHEMA,handler=_rollback,description=ROLLBACK_SCHEMA["description"])
