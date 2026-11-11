from pathlib import Path

p = Path(r"D:\Rag project\src\providers.py")
s = p.read_text(encoding="utf-8")

s = s.replace("Groq -> OpenAI -> Gemini cascade", "provider cascade")
s = s.replace("PROVIDER_ORDER is groq -> openai -> gemini", "PROVIDER_ORDER controls the configured provider order")
s = s.replace("Groq first because it is the provider actually", "Configured providers are tried in failover order")
s = s.replace("empty groq answer fell through to openai", "empty provider answer falls through to the next provider")
s = s.replace("never requires groq/openai/google-generativeai to be installed", "provider SDKs are loaded lazily only when required")

p.write_text(s, encoding="utf-8")
print("DONE: stale provider comments cleaned")
