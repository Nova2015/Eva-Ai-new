from pathlib import Path

p = Path(r"D:\Rag project\src\app.py")
s = p.read_text(encoding="utf-8")

old = '''            except Exception as _groq_err:
                print(f"Groq failed: {_groq_err}")
'''

new = '''            except Exception as _groq_err:
                logger.exception("[CHAT LLM] provider execution failed")
                print(f"[CHAT LLM] provider execution failed: {_groq_err}")
'''

if old not in s:
    raise SystemExit("TARGET NOT FOUND")

s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

print("DONE: full /chat provider traceback enabled")
