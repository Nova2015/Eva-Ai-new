from pathlib import Path

p = Path(r"D:\Rag project\src\app.py")
s = p.read_text(encoding="utf-8")

start = s.index('    groq_key = os.getenv("GROQ_API_KEY", "")', s.index('@app.post("/chat/stream")'))
end_marker = '\n    return StreamingResponse(\n        generate(),\n        media_type="text/event-stream",'
end = s.index(end_marker, start)

new = '''    async def generate():
        try:
            stream_question = getattr(req, "message", None) or req.question

            history = [
                {"role": m["role"], "content": m["content"]}
                for m in (getattr(req, "history", None) or [])
            ]

            messages = (
                [{"role": "system",
                  "content": chart_system_prompt(BASE_SYSTEM_PROMPT, stream_question)}]
                + history
                + [{"role": "user", "content": stream_question}]
            )

            # EVA provider abstraction:
            # eva_local -> local -> gemini (according to configured chain).
            result = providers.complete(
                messages,
                max_tokens=getattr(req, "max_tokens", None) or 1024,
                temperature=getattr(req, "temperature", None) or 0.7,
            )

            full_reply = result.text or ""

            if full_reply:
                # Preserve the existing SSE contract.
                data = json.dumps({
                    "token": full_reply,
                    "choices": [{"delta": {"content": full_reply}}]
                })
                yield f"data: {data}\\\\n\\\\n"

            try:
                mem = get_memory()
                mem.add_message(req.user_id, "user", stream_question)
                mem.add_message(req.user_id, "assistant", full_reply)
            except Exception as mem_exc:
                logger.warning(f"chat_stream memory save skipped: {mem_exc}")

            if not full_reply:
                error_data = json.dumps({
                    "token": "\\\\n\\\\n⚠️ AI service unavailable."
                })
                yield f"data: {error_data}\\\\n\\\\n"

            yield "data: [DONE]\\\\n\\\\n"

        except Exception as e:
            error_data = json.dumps({"token": f"\\\\n\\\\n❌ Error: {str(e)}"})
            yield f"data: {error_data}\\\\n\\\\n"
            yield "data: [DONE]\\\\n\\\\n"
'''

s = s[:start] + new + s[end:]

p.write_text(s, encoding="utf-8")
print("DONE: /chat/stream raw Groq path replaced with EVA provider failover")
