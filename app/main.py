"""FastAPI app: auth, RBAC-aware rate limiting, SSE streaming of agent activity + answer tokens."""
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.agents.graph import build_graph
from app.agents.state import fresh_turn
from app.auth import User, authenticate, decode_token, issue_token
from app.config import PROJECT_ROOT, settings
from app.context import current_emitter, current_user, request_id_var
from app.errors import AppError, AuthError
from app.logging_conf import configure_logging
from app.permissions import tools_for
from app.rate_limit import TokenBucketLimiter
from app.schemas import ChatRequest, FeedbackRequest, LoginRequest
from app.services import get_registry, get_retriever

configure_logging()
log = logging.getLogger("api")
bearer = HTTPBearer(auto_error=False)
FEEDBACK_FILE = PROJECT_ROOT / "data" / "feedback.jsonl"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = build_graph()
    app.state.limiter = TokenBucketLimiter(settings.rate_limit_capacity, settings.rate_limit_refill_per_sec)
    app.state.sessions = {}  # session_id -> owner username (prevents cross-user session access)
    get_retriever(), get_registry()  # warm singletons
    log.info("api started", extra={"ctx": {"model": settings.llm_model, "chunks": len(get_retriever().bm25.chunks)}})
    yield


app = FastAPI(title=f"{settings.bank_name} Knowledge Assistant", lifespan=lifespan)


# ------------------------------------------------------------------ middleware & errors
@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id_var.set(request.headers.get("x-request-id", uuid.uuid4().hex[:12]))
    t0 = time.perf_counter()
    response = await call_next(request)
    log.info("request", extra={"ctx": {"path": request.url.path, "status": response.status_code,
                                       "ms": int((time.perf_counter() - t0) * 1000)}})
    response.headers["x-request-id"] = request_id_var.get()
    return response


def _err(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return _err(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    return _err(422, "invalid_request", f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}")


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return _err(500, "internal_error", "Something went wrong. Please try again.")  # no internals leaked


# ------------------------------------------------------------------ dependencies
async def get_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if creds is None:
        raise AuthError("Missing bearer token")
    return decode_token(creds.credentials)


async def rate_limited_user(request: Request, user: User = Depends(get_user)) -> User:
    allowed, retry_after = await request.app.state.limiter.try_consume(user.username)
    if not allowed:
        log.warning("rate limited", extra={"ctx": {"user": user.username, "retry_after": retry_after}})
        raise HTTPException(429, f"Rate limit exceeded. Retry in {retry_after:.0f}s.", headers={"Retry-After": str(int(retry_after) + 1)})
    return user


# ------------------------------------------------------------------ routes
@app.get("/health")
async def health():
    return {"status": "ok", "indexed_chunks": len(get_retriever().bm25.chunks), "pinecone": get_retriever().store.configured}


@app.post("/auth/login")
async def login(body: LoginRequest):
    user = authenticate(body.username, body.password)
    if not user:
        raise AuthError("Invalid username or password")
    return {"token": issue_token(user), "username": user.username, "role": user.role.value, "tools": tools_for(user.role)}


@app.get("/me")
async def me(user: User = Depends(get_user)):
    return {"username": user.username, "role": user.role.value, "tools": tools_for(user.role)}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request, user: User = Depends(rate_limited_user)):
    sessions: dict = request.app.state.sessions
    session_id = body.session_id or uuid.uuid4().hex
    if sessions.setdefault(session_id, user.username) != user.username:
        raise AppError("Session belongs to another user", 403, "forbidden")

    graph, run_id = request.app.state.graph, str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()

    async def emitter(event: dict) -> None:
        await queue.put(event)

    async def run_graph() -> None:
        current_user.set(user)        # identity comes from the verified token, never from the LLM
        current_emitter.set(emitter)
        config = {"configurable": {"thread_id": f"{user.username}:{session_id}"},  # session memory
                  "run_id": run_id, "run_name": "chat_turn", "tags": [f"role:{user.role.value}"],
                  "metadata": {"user": user.username, "role": user.role.value, "session_id": session_id}}
        try:
            await asyncio.wait_for(graph.ainvoke(fresh_turn(body.message), config), settings.request_timeout_s)
        except asyncio.TimeoutError:
            await emitter({"type": "error", "node": "graph", "message": "The request timed out."})
        except Exception as exc:  # noqa: BLE001
            log.exception("graph run failed")
            await emitter({"type": "error", "node": "graph", "message": f"{type(exc).__name__}"})
            await emitter({"type": "final", "answer": "I'm sorry - something went wrong while processing your request.",
                           "sources": [], "validation": {"ok": False}, "errors": [type(exc).__name__]})
        finally:
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(run_graph())
        try:
            yield _sse("session", {"session_id": session_id, "run_id": run_id})
            while (event := await queue.get()) is not None:
                yield _sse(event["type"], event)
            yield _sse("done", {"run_id": run_id, "session_id": session_id})
        finally:
            if not task.done():
                task.cancel()  # client disconnected

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/feedback")
async def feedback(body: FeedbackRequest, user: User = Depends(get_user)):
    """Answer-quality feedback loop: stored locally and attached to the LangSmith trace when possible."""
    record = {"ts": time.time(), "user": user.username, **body.model_dump()}
    FEEDBACK_FILE.parent.mkdir(exist_ok=True)
    with FEEDBACK_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")
    try:
        from langsmith import Client

        await asyncio.to_thread(Client().create_feedback, body.run_id, key="user_score", score=body.score, comment=body.comment)
    except Exception:  # noqa: BLE001 - LangSmith being unreachable must not fail the user's request
        log.warning("could not push feedback to LangSmith")
    return {"status": "recorded"}
