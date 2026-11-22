import os, subprocess, threading, uuid
from collections import Counter
from pydantic import BaseModel, SecretStr
from fastapi import FastAPI, APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.conversation.state import (
    ConversationExecutionStatus,
    ConversationState,
)
from openhands.sdk.security.confirmation_policy import AlwaysConfirm
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"env var missing: {name}")
    return v


class AgentRunRequest(BaseModel):
    task: str
    workspace: str


router = APIRouter()
WORKSPACE = env("AGENT_WORKSPACE")
AGENT_KEY = env("AGENT_API_KEY")
MAX_STEPS = 30
APPROVAL_TIMEOUT = 600

api_key_header = APIKeyHeader(name="X-Agent-Key")


def require_key(key: str = Depends(api_key_header)):
    if key != AGENT_KEY:
        raise HTTPException(401, "bad key")


jobs = {}


def run_agent(job_id: str, task: str):
    job = jobs[job_id]
    try:
        llm = LLM(
            usage_id="agent",
            model=env("AGENT_MODEL"),
            api_key=SecretStr(env("GEMINI_API_KEY")),
            num_retries=8,  # error aala tar ha ol kadha
        )
        agent = Agent(llm=llm, tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
        ])

        def on_event(event):
            job["counts"][type(event).__name__] += 1
            job["log"].append(str(event)[:500])
            del job["log"][:-50]

        conv = Conversation(agent=agent, workspace=job["workspace"],
                            callbacks=[on_event])
        conv.set_confirmation_policy(AlwaysConfirm())
        conv.send_message(task)

        steps = 0
        while conv.state.execution_status != ConversationExecutionStatus.FINISHED:
            steps += 1
            if steps > MAX_STEPS:
                job["status"] = "error: too many steps"
                return

            if (conv.state.execution_status
                    == ConversationExecutionStatus.WAITING_FOR_CONFIRMATION):
                pending = ConversationState.get_unmatched_actions(conv.state.events)
                job["pending"] = [
                    {"tool": a.tool_name,
                     "summary": a.summary,
                     "action": str(a.action)}  # full, kapleli nahi
                    for a in pending
                ]
                job["approved"] = False
                job["event"].clear()
                job["status"] = "waiting_approval"
                got_answer = job["event"].wait(timeout=APPROVAL_TIMEOUT)
                job["pending"] = []
                if not got_answer or not job["approved"]:
                    conv.reject_pending_actions("User rejected the actions")
                    continue

            job["status"] = "running"
            conv.run()

        job["status"] = "done"
    except Exception as e:
        job["status"] = f"error: {e}"


@router.post("/agent/run", dependencies=[Depends(require_key)])
def start(request: AgentRunRequest):
    task = request.task.strip()
    workspace = os.path.realpath(request.workspace.strip())

    if not task:
        raise HTTPException(400, "task is required")
    if not os.path.isdir(workspace):
        raise HTTPException(400, "Selected workspace folder does not exist")

    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"status": "running", "pending": [], "approved": False,
                    "event": threading.Event(), "log": [],
                    "counts": Counter(), "workspace": workspace}
    threading.Thread(target=run_agent, args=(job_id, task), daemon=True).start()
    return {"job_id": job_id}


@router.get("/agent/status/{job_id}", dependencies=[Depends(require_key)])
def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404)
    return {"status": job["status"], "pending": job["pending"],
            "counts": dict(job["counts"]), "log": job["log"][-20:]}


@router.post("/agent/approve/{job_id}", dependencies=[Depends(require_key)])
def approve(job_id: str, ok: bool):
    job = jobs.get(job_id)
    if not job or job["status"] != "waiting_approval":
        raise HTTPException(400, "nothing to approve")
    job["approved"] = ok
    job["event"].set()
    return {"ok": True}


@router.get("/agent/diff/{job_id}", dependencies=[Depends(require_key)])
def diff(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    workspace = job["workspace"]

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=workspace,
            capture_output=True, text=True
        ).stdout

    return {"status": git("status", "--short"), "diff": git("diff")}
app = FastAPI()
app.include_router(router)





