"""A small, typed API layer on Starlette + Pydantic with OpenAPI 3.1 generation.

FastAPI could not be installed in the build sandbox, so this module provides the parts of
it SAMANVAY needs, on the same foundations (Starlette routing, Pydantic validation):

* `APIRouter` decorators declare method, path, query model, body model, response type and
  the permission required (`perm=`). Handlers are plain synchronous functions
  `handler(ctx, <path params>, q=<query model>, body=<body model>)` executed in a thread pool,
  each with its own SQLite connection (`ctx.db`) and resolved demo user (`ctx.user`).
* Inputs are validated with Pydantic; responses are validated against the declared
  response type before serialisation, so the OpenAPI document matches real payloads.
* Errors use one envelope: {"error": {"code", "message", "details"}}; unexpected
  exceptions are logged server-side and returned as a generic 500 (no stack traces).
* Denied permission checks on state-changing routes are written to the audit chain.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from ..db import database
from .config import get_settings
from .errors import ApiError, bad_request
from .security import User, require, resolve_user

log = logging.getLogger("samanvay.api")


@dataclass
class Ctx:
    request: Request
    user: User
    db: database.Conn
    form: Any = None

    def require(self, perm: str) -> None:
        require(self.user, perm)


@dataclass
class Endpoint:
    method: str
    path: str
    func: Callable[..., Any]
    summary: str
    description: str | None
    tags: list[str]
    query: type[BaseModel] | None
    body: type[BaseModel] | None
    response: Any
    perm: str | None
    status_code: int
    multipart: bool
    media: str | None


class APIRouter:
    def __init__(self, prefix: str = "", tags: list[str] | None = None):
        self.prefix = prefix
        self.tags = tags or []
        self.endpoints: list[Endpoint] = []

    def route(self, method: str, path: str, *, summary: str | None = None, query=None, body=None,
              response=None, perm: str | None = None, status_code: int = 200,
              multipart: bool = False, media: str | None = None, tags: list[str] | None = None):
        def deco(func: Callable[..., Any]) -> Callable[..., Any]:
            doc = inspect.getdoc(func)
            self.endpoints.append(Endpoint(
                method=method, path=self.prefix + path, func=func,
                summary=summary or (doc.splitlines()[0] if doc else func.__name__.replace("_", " ")),
                description=doc, tags=tags or self.tags, query=query, body=body,
                response=response, perm=perm, status_code=status_code,
                multipart=multipart, media=media,
            ))
            return func
        return deco

    def get(self, path: str, **kw):
        return self.route("GET", path, **kw)

    def post(self, path: str, **kw):
        return self.route("POST", path, **kw)

    def put(self, path: str, **kw):
        return self.route("PUT", path, **kw)

    def patch(self, path: str, **kw):
        return self.route("PATCH", path, **kw)

    def delete(self, path: str, **kw):
        return self.route("DELETE", path, **kw)


_adapters: dict[Any, TypeAdapter] = {}


def _adapter(tp: Any) -> TypeAdapter:
    key = tp if isinstance(tp, type) else repr(tp)
    ad = _adapters.get(key)
    if ad is None:
        ad = TypeAdapter(tp)
        _adapters[key] = ad
    return ad


def _is_list(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (list, tuple, set, frozenset):
        return True
    if origin in (typing.Union, types.UnionType):
        return any(_is_list(a) for a in typing.get_args(annotation) if a is not type(None))
    return False


def _query_dict(model: type[BaseModel], request: Request) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        key = field.alias or name
        if _is_list(field.annotation):
            items: list[str] = []
            for raw in request.query_params.getlist(key):
                items.extend(part.strip() for part in raw.split(",") if part.strip())
            if items:
                data[key] = items
        else:
            raw = request.query_params.get(key)
            if raw is not None and raw.strip() != "":
                data[key] = raw.strip()
    return data


def _clean_errors(exc: ValidationError) -> list[dict[str, Any]]:
    out = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False):
        out.append({"loc": [str(p) for p in err.get("loc", ())], "msg": err.get("msg"), "type": err.get("type")})
    return out


def _audit_denied(db: database.Conn, user: User, ep: Endpoint, err: ApiError) -> None:
    from ..audit import chain

    try:
        with db.tx():
            chain.record(db, user, "ACCESS_DENIED", "endpoint", f"{ep.method} {ep.path}",
                         after={"permission": ep.perm, "role": user.role}, remarks=err.message)
    except Exception:  # pragma: no cover - auditing a denial must never mask the 403
        log.exception("could not audit access denial")


def make_route(ep: Endpoint) -> Route:
    accepted = set(inspect.signature(ep.func).parameters)

    async def endpoint(request: Request) -> Response:
        settings = get_settings()
        form = None
        try:
            user_id = request.headers.get("x-demo-user") or settings.default_demo_user
            kwargs: dict[str, Any] = {k: v for k, v in request.path_params.items() if k in accepted}
            if ep.query is not None:
                kwargs["q"] = ep.query.model_validate(_query_dict(ep.query, request))
            if ep.body is not None:
                raw = await request.body()
                try:
                    payload = json.loads(raw) if raw.strip() else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise bad_request("Request body must be valid JSON.") from None
                kwargs["body"] = ep.body.model_validate(payload)
            if ep.multipart:
                form = await request.form(max_files=3, max_fields=40, max_part_size=1024 * 1024)

            def run() -> Any:
                with database.connect(settings.db_path) as db:
                    user = resolve_user(db, user_id)
                    ctx = Ctx(request=request, user=user, db=db, form=form)
                    try:
                        if ep.perm:
                            require(user, ep.perm)
                        return ep.func(ctx, **kwargs)
                    except ApiError as err:
                        # Role-restricted operations that were refused are part of the audit trail.
                        if err.status == 403 and ep.method != "GET" and not db.in_tx:
                            _audit_denied(db, user, ep, err)
                        raise

            result = await run_in_threadpool(run)
        except ApiError as err:
            return JSONResponse(err.payload(), status_code=err.status)
        except ValidationError as err:
            return JSONResponse(
                {"error": {"code": "validation_error", "message": "Request validation failed.",
                           "details": _clean_errors(err)}},
                status_code=422,
            )
        except Exception:
            log.exception("unhandled error in %s %s", ep.method, ep.path)
            return JSONResponse(
                {"error": {"code": "internal_error",
                           "message": "Unexpected server error. Details were written to the server log."}},
                status_code=500,
            )
        finally:
            if form is not None:
                await form.close()

        if isinstance(result, Response):
            return result
        if ep.response is None:
            return JSONResponse(result, status_code=ep.status_code)
        try:
            adapter = _adapter(ep.response)
            payload = adapter.dump_python(adapter.validate_python(result), mode="json")
        except ValidationError:
            log.exception("response validation failed for %s %s", ep.method, ep.path)
            return JSONResponse(
                {"error": {"code": "internal_error", "message": "Server produced an invalid response."}},
                status_code=500,
            )
        return JSONResponse(payload, status_code=ep.status_code)

    return Route(ep.path, endpoint, methods=[ep.method], name=f"{ep.method}:{ep.path}")


# --------------------------------------------------------------------------------------
# OpenAPI 3.1 generation
# --------------------------------------------------------------------------------------

ERROR_SCHEMA = {
    "type": "object",
    "title": "ErrorResponse",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {},
            },
            "required": ["code", "message"],
        }
    },
    "required": ["error"],
}


def _schema(tp: Any, mode: str, components: dict[str, Any]) -> dict[str, Any]:
    sch = _adapter(tp).json_schema(ref_template="#/components/schemas/{model}", mode=mode)
    for name, definition in sch.pop("$defs", {}).items():
        components.setdefault(name, definition)
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        components.setdefault(tp.__name__, sch)
        return {"$ref": f"#/components/schemas/{tp.__name__}"}
    return sch


def build_openapi(endpoints: list[Endpoint], *, title: str, version: str, description: str) -> dict[str, Any]:
    components: dict[str, Any] = {"ErrorResponse": ERROR_SCHEMA}
    paths: dict[str, Any] = {}
    seen_ops: set[str] = set()
    for ep in endpoints:
        op_id = ep.func.__name__
        if op_id in seen_ops:
            op_id = f"{op_id}_{ep.method.lower()}"
        seen_ops.add(op_id)
        params: list[dict[str, Any]] = []
        for name in re.findall(r"{(\w+)(?::\w+)?}", ep.path):
            params.append({"name": name, "in": "path", "required": True, "schema": {"type": "string"}})
        if ep.query is not None:
            qs = ep.query.model_json_schema(ref_template="#/components/schemas/{model}")
            for name, definition in qs.pop("$defs", {}).items():
                components.setdefault(name, definition)
            required = set(qs.get("required", []))
            for pname, pschema in qs.get("properties", {}).items():
                desc = pschema.pop("description", None)
                param = {"name": pname, "in": "query", "required": pname in required, "schema": pschema}
                if desc:
                    param["description"] = desc
                params.append(param)
        op: dict[str, Any] = {
            "operationId": op_id,
            "summary": ep.summary,
            "tags": ep.tags,
            "parameters": params,
            "x-permission": ep.perm,
        }
        if ep.description and ep.description != ep.summary:
            op["description"] = ep.description
        if ep.body is not None:
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": _schema(ep.body, "validation", components)}}}
        if ep.multipart:
            op["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
                "type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}}}}
        responses: dict[str, Any] = {}
        if ep.media:
            responses[str(ep.status_code)] = {"description": "File download",
                                              "content": {ep.media: {"schema": {"type": "string", "format": "binary"}}}}
        elif ep.response is not None:
            responses[str(ep.status_code)] = {"description": "Successful response",
                                              "content": {"application/json": {"schema": _schema(ep.response, "serialization", components)}}}
        else:
            responses[str(ep.status_code)] = {"description": "Successful response"}
        err_ref = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}
        responses["4XX"] = {"description": "Client error (validation, permission, not found, conflict)", **err_ref}
        responses["5XX"] = {"description": "Server error (generic message; details only in server log)", **err_ref}
        op["responses"] = responses
        oa_path = re.sub(r"{(\w+):\w+}", r"{\1}", ep.path)
        paths.setdefault(oa_path, {})[ep.method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version, "description": description},
        "servers": [{"url": "/"}],
        "paths": paths,
        "components": {
            "schemas": components,
            "securitySchemes": {
                "DemoUser": {
                    "type": "apiKey", "in": "header", "name": "X-Demo-User",
                    "description": "Prototype role simulation (not authentication). Values: rb.officer, "
                                   "pgrc.officer, ro.central, senior.mgmt, competent.authority.",
                }
            },
        },
        "security": [{"DemoUser": []}],
    }


DOCS_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AgniDrishti API docs</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f7fb;color:#1a1a1a}
header{background:#1F3864;color:#fff;padding:14px 20px}header h1{margin:0;font-size:18px}
header p{margin:4px 0 0;font-size:13px;opacity:.85}main{max-width:1100px;margin:0 auto;padding:16px}
.tag{margin:18px 0 6px;font-size:15px;color:#1F3864;text-transform:uppercase;letter-spacing:.04em}
details{background:#fff;border:1px solid #dde5f0;border-radius:8px;margin:6px 0}
summary{cursor:pointer;padding:9px 12px;display:flex;gap:10px;align-items:center;font-size:14px}
.m{font-weight:700;font-size:12px;padding:2px 8px;border-radius:4px;color:#fff;min-width:52px;text-align:center}
.GET{background:#0071C1}.POST{background:#2E8B3E}.PUT,.PATCH{background:#F28C28}.DELETE{background:#D64545}
.p{font-family:ui-monospace,Menlo,Consolas,monospace}.perm{margin-left:auto;font-size:12px;color:#6B7585}
.body{padding:8px 14px 14px;border-top:1px solid #eef1f7;font-size:13px}pre{background:#0f1b33;color:#e8eefc;
padding:10px;border-radius:6px;overflow:auto;max-height:360px;font-size:12px}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid #eef1f7;padding:4px 6px;text-align:left;vertical-align:top}
.try{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:8px}input,select{padding:4px 6px;border:1px solid #c9d3e3;border-radius:4px}
button{background:#0071C1;color:#fff;border:0;border-radius:4px;padding:5px 10px;cursor:pointer}
</style></head><body><header><h1>AgniDrishti API — OpenAPI 3.1</h1>
<p>Offline API reference generated from the server's route declarations. Raw spec: <a style="color:#fff" href="/api/openapi.json">/api/openapi.json</a>.
Role header X-Demo-User simulates roles for the prototype (not authentication).</p></header><main id="root">Loading…</main>
<script>
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
fetch('/api/openapi.json').then(r=>r.json()).then(spec=>{
 const byTag={};for(const [p,ops] of Object.entries(spec.paths))for(const [m,op] of Object.entries(ops)){
  const t=(op.tags&&op.tags[0])||'other';(byTag[t]=byTag[t]||[]).push({p,m:m.toUpperCase(),op});}
 let h='<p>'+Object.values(byTag).reduce((a,b)=>a+b.length,0)+' operations · '+Object.keys(spec.components.schemas).length+' schemas</p>';
 for(const t of Object.keys(byTag).sort()){h+='<div class="tag">'+esc(t)+'</div>';
  for(const {p,m,op} of byTag[t]){const id=op.operationId;
   const params=(op.parameters||[]).map(x=>'<tr><td class="p">'+esc(x.name)+'</td><td>'+x.in+(x.required?' · required':'')+'</td><td>'+esc(JSON.stringify(x.schema))+'</td><td>'+esc(x.description||'')+'</td></tr>').join('');
   const req=op.requestBody?'<p><b>Request body</b></p><pre>'+esc(JSON.stringify(op.requestBody.content,null,1))+'</pre>':'';
   const res='<p><b>Responses</b></p><pre>'+esc(JSON.stringify(op.responses,null,1))+'</pre>';
   const tr=m==='GET'&&!p.includes('{')?'<div class="try"><select id="u_'+id+'"><option>senior.mgmt</option><option>competent.authority</option><option>rb.officer</option><option>pgrc.officer</option><option>ro.central</option></select><input id="q_'+id+'" placeholder="query string e.g. page=1"><button onclick="tryIt(\\''+id+'\\',\\''+p+'\\')">Try it</button></div><pre id="o_'+id+'" hidden></pre>':'';
   h+='<details><summary><span class="m '+m+'">'+m+'</span><span class="p">'+esc(p)+'</span><span>'+esc(op.summary||'')+'</span><span class="perm">'+esc(op['x-permission']||'public')+'</span></summary><div class="body">'+(op.description?'<p>'+esc(op.description)+'</p>':'')+(params?'<table><tr><th>Name</th><th>In</th><th>Schema</th><th>Description</th></tr>'+params+'</table>':'')+req+res+tr+'</div></details>';}}
 document.getElementById('root').innerHTML=h;});
function tryIt(id,p){const q=document.getElementById('q_'+id).value,u=document.getElementById('u_'+id).value,o=document.getElementById('o_'+id);
 fetch(p+(q?'?'+q:''),{headers:{'X-Demo-User':u}}).then(async r=>{o.hidden=false;const t=await r.text();try{o.textContent=r.status+'\\n'+JSON.stringify(JSON.parse(t),null,1).slice(0,20000)}catch(e){o.textContent=r.status+'\\n'+t.slice(0,4000)}});}
</script></body></html>"""


def docs_response() -> HTMLResponse:
    return HTMLResponse(DOCS_HTML)
