from pathlib import Path

p = Path(r"D:\Rag project\src\app.py")
s = p.read_text(encoding="utf-8")

old = '''                if providers.configured("eva_local"):
                    try:
                        answer = providers.dispatch("eva_local", messages,
                                                    max_tokens=1024, temperature=0.7)
                        _log_raw_model_response(answer or "", system_msg)
                    except Exception as _local_err:
                        print(f"eva_local failed: {_local_err}")

                if not answer:
                    answer = providers.complete(
                        messages,
                        max_tokens=1024,
                        temperature=0.7,
                    )
                    _log_raw_model_response(answer or "", system_msg)
'''

new = '''                if providers.configured("eva_local"):
                    try:
                        answer = providers.dispatch(
                            "eva_local",
                            messages,
                            max_tokens=1024,
                            temperature=0.7,
                        )
                        _log_raw_model_response(answer or "", system_msg)
                    except Exception as _local_err:
                        print(f"eva_local failed: {_local_err}")

                if not answer:
                    _provider_result = providers.complete(
                        messages,
                        max_tokens=1024,
                        temperature=0.7,
                    )
                    if _provider_result.ok:
                        answer = _provider_result.text or ""
                        _log_raw_model_response(answer, system_msg)
                    else:
                        print(f"providers.complete failed: {_provider_result.error}")
                        answer = ""
'''

if old not in s:
    raise SystemExit("TARGET BLOCK NOT FOUND")

p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("DONE: ProviderResult handled correctly in /chat")
