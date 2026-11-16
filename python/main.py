"""Mini-Task API — version Python / FastAPI (Uvicorn, port 8080).

Lancement (voir scripts/server.sh) :
    uvicorn main:app --host 127.0.0.1 --port 8080 --log-level warning --no-access-log
"""
import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

MAX_N = 40
DIGITS = re.compile(r"[0-9]+")


class Utf8JSONResponse(JSONResponse):
    """JSONResponse standard (JSON compact, UTF-8 non échappé) avec le
    Content-Type exigé par le contrat : application/json; charset=utf-8."""
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    default_response_class=Utf8JSONResponse,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)

# --- Données en mémoire -----------------------------------------------------
TASKS = json.loads((Path(__file__).parent / "tasks.json").read_text(encoding="utf-8"))
BY_ID = {t["id"]: t for t in TASKS}
NEXT_ID = len(TASKS) + 1


def not_found():
    return Utf8JSONResponse({"error": "not found"}, status_code=404)


def bad_payload():
    return Utf8JSONResponse({"error": "invalid payload"}, status_code=400)


def _reject_constant(_name):
    raise ValueError("NaN/Infinity interdits en JSON")


def fib(n: int) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)


# --- Routes -------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/tasks")
async def list_tasks():
    return TASKS


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if len(task_id) <= 18 and task_id.isascii() and task_id.isdigit():
        task = BY_ID.get(int(task_id))
        if task is not None:
            return task
    return not_found()


@app.post("/tasks")
async def create_task(request: Request):
    global NEXT_ID
    try:
        payload = json.loads(await request.body(), parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError):
        return bad_payload()
    if not isinstance(payload, dict):
        return bad_payload()

    title = payload.get("title")
    priority = payload.get("priority")
    done = payload.get("done", False)
    if (
        not isinstance(title, str) or title == ""
        or not isinstance(priority, int) or isinstance(priority, bool)
        or not 1 <= priority <= 5
        or not isinstance(done, bool)
    ):
        return bad_payload()

    task = {"id": NEXT_ID, "title": title, "done": done, "priority": priority}
    NEXT_ID += 1
    TASKS.append(task)
    BY_ID[task["id"]] = task
    return Utf8JSONResponse(task, status_code=201)


# `def` (et non `async def`) : calcul CPU bloquant, FastAPI l'exécute dans son
# pool de threads, comme le recommande sa documentation.
@app.get("/compute")
def compute(request: Request):
    raw = request.query_params.get("n")
    if raw is None or not DIGITS.fullmatch(raw) or len(raw) > 18 or int(raw) > MAX_N:
        return Utf8JSONResponse({"error": "invalid n"}, status_code=400)
    n = int(raw)
    return {"n": n, "result": fib(n)}


# Toute route/méthode inconnue (y compris 405) -> 404 au format du contrat.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, _exc: StarletteHTTPException):
    return not_found()
