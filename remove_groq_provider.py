from pathlib import Path

p = Path(r"D:\Rag project\src\providers.py")
s = p.read_text(encoding="utf-8")

old = '''def _call_groq(messages: List[Dict[str, str]], model: str,
               max_tokens: int, temperature: Optional[float]) -> str:
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    resp = client.chat.completions.create(
        **_messages_with_optional_temperature(model, messages, max_tokens, temperature))
    return resp.choices[0].message.content or ""


'''

if old not in s:
    raise SystemExit("ERROR: _call_groq block not found")

s = s.replace(old, "", 1)

old_adapter = '    "groq": _call_groq,\n'

if old_adapter not in s:
    raise SystemExit("ERROR: Groq adapter entry not found")

s = s.replace(old_adapter, "", 1)

p.write_text(s, encoding="utf-8")

print("DONE: Groq adapter removed from providers.py")
