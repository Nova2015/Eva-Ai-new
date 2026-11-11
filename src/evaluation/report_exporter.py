from datetime import datetime


def render_markdown_report(result: dict) -> str:
    scores = result.get("scores", {})
    failed = result.get("failed_questions", [])
    lines = [
        "# EVA Domain Evaluation Report",
        "",
        f"Generated: {datetime.utcnow().isoformat()} UTC",
        "",
        f"- Accuracy: {scores.get('accuracy', 0)}%",
        f"- Hallucination: {scores.get('hallucination', 0)}%",
        f"- Citation match: {scores.get('citation_match', 0)}%",
        f"- Retrieval quality: {scores.get('retrieval_quality', 0)}%",
        "",
        "## Failed Questions",
    ]
    if not failed:
        lines.append("No failed questions recorded.")
    for item in failed:
        lines.append(f"- {item.get('question', 'Untitled question')}")
    return "\n".join(lines) + "\n"
