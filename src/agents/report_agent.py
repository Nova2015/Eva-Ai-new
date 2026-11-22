import html
import os
import zipfile
from datetime import datetime
from pathlib import Path

from . import task_manager


ROOT_DIR = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(os.getenv("EVA_AGENT_REPORT_DIR", ROOT_DIR / "generated" / "agent_reports"))


def _file_size(path):
    path = Path(path)
    if not path.exists():
        return "0 KB"
    return f"{path.stat().st_size / 1024:.1f} KB"


def generate_project_report(user_id="user_001"):
    tasks = task_manager.list_tasks(user_id, limit=50)
    history = task_manager.list_history(user_id, limit=30)
    schedules = task_manager.list_schedules(user_id)

    open_bugs = [task for task in tasks if task["status"] in ("running", "failed")]
    completed = [task for task in tasks if task["status"] == "completed"]
    env_keys = {
        "GROQ_API_KEY": bool(os.getenv("GROQ_API_KEY")),
        "GITHUB_TOKEN": bool(os.getenv("GITHUB_TOKEN")),
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
    }

    lines = [
        "# EVA AI Project Report",
        "",
        f"Generated: {datetime.utcnow().isoformat()} UTC",
        f"User: {user_id}",
        "",
        "## Project Status",
        f"- Agent tasks: {len(tasks)}",
        f"- Completed tasks: {len(completed)}",
        f"- Running or failed tasks: {len(open_bugs)}",
        f"- Scheduled jobs: {len([s for s in schedules if s.get('enabled')])}",
        "",
        "## Open Bugs",
    ]
    if open_bugs:
        lines.extend(f"- {task['title']} ({task['status']})" for task in open_bugs[:12])
    else:
        lines.append("- No open Agent OS task failures recorded.")

    lines.extend([
        "",
        "## Security Issues",
        "- Review Security Dashboard and firewall logs for live threat details.",
        "- Agent OS Security Agent can scan pasted logs or deployment traces.",
        "",
        "## Deployment Status",
        "- Backend health endpoint: /health",
        "- Render health checks are available through Deployment Agent tasks.",
        "",
        "## Database Size",
        f"- Memory database: {_file_size(ROOT_DIR / 'memory.db')}",
        f"- Agent OS database: {_file_size(task_manager.DB_PATH)}",
        "",
        "## Memory Usage",
        "- Memory V2 stores recent chat rows and long-term project memories.",
        "- Memory Agent can identify duplicates and create project summaries.",
        "",
        "## Model Usage",
    ])
    lines.extend(f"- {name}: {'configured' if configured else 'missing'}" for name, configured in env_keys.items())
    lines.extend([
        "",
        "## Recent Agent Events",
    ])
    if history:
        lines.extend(f"- {item['created_at']} / {item['agent_type']} / {item['event']}" for item in history[:12])
    else:
        lines.append("- No Agent OS history yet.")

    return "\n".join(lines)


def _write_markdown(markdown, path):
    path.write_text(markdown, encoding="utf-8")


def _write_docx(markdown, path):
    paragraphs = []
    for line in markdown.splitlines():
        text = html.escape(line or " ")
        paragraphs.append(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paragraphs)}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ))
        zf.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        ))
        zf.writestr("word/document.xml", document_xml)


def _pdf_escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(markdown, path):
    lines = []
    for raw in markdown.splitlines():
        while len(raw) > 92:
            lines.append(raw[:92])
            raw = raw[92:]
        lines.append(raw)
    lines = lines[:48]
    y = 760
    commands = ["BT", "/F1 10 Tf"]
    for line in lines:
        commands.append(f"72 {y} Td ({_pdf_escape(line)}) Tj")
        commands.append("0 -14 Td")
        y -= 14
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="ignore")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = [b"%PDF-1.4\n"]
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in pdf))
        pdf.append(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = sum(len(part) for part in pdf)
    pdf.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        pdf.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.append(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii")
    )
    path.write_bytes(b"".join(pdf))


def save_report(user_id="user_001", fmt="md"):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    markdown = generate_project_report(user_id)
    fmt = (fmt or "md").lower()
    if fmt not in ("md", "markdown", "docx", "pdf"):
        fmt = "md"
    ext = "md" if fmt == "markdown" else fmt
    path = REPORT_DIR / f"eva-agent-report-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{ext}"
    if ext == "docx":
        _write_docx(markdown, path)
    elif ext == "pdf":
        _write_pdf(markdown, path)
    else:
        _write_markdown(markdown, path)
    return {"path": str(path), "format": ext, "markdown": markdown}


def run_report_task(user_id="user_001", instruction="", payload=None):
    report = generate_project_report(user_id)
    return {
        "status": "completed",
        "summary": "Report Agent generated the EVA project status report.",
        "report": report,
    }
