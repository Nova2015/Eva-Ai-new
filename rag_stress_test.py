import io
import json
import os
import tempfile
import time
import requests
from pathlib import Path

urls = [
    'https://keshav1212-eva-ml-service.hf.space/rag/upload',
    'https://keshav1212-eva-ml-service.hf.space/api/rag/upload',
]

parts = []
for i in range(1400):
    parts.append(f"SECTION {i+1} " + ("dense technical documentation for async stress testing. " * 80))
text = '\n\n'.join(parts)
content = text.encode('utf-8')
print(f'payload_bytes={len(content)}')

for url in urls:
    print(f'POST {url}')
    start = time.time()
    try:
        resp = requests.post(
            url,
            files={'file': ('stress-test.txt', io.BytesIO(content), 'text/plain')},
            data={'workspace_id': 'stress-test'},
            timeout=1800,
        )
        elapsed = time.time() - start
        print('status', resp.status_code)
        print('elapsed_seconds', round(elapsed, 3))
        try:
            data = resp.json()
            print('json_keys', sorted(data.keys()))
            print('body_preview', json.dumps(data, indent=2)[:12000])
        except Exception as exc:
            print('body_text', resp.text[:12000])
    except Exception as exc:
        print('error', repr(exc))
        print('elapsed_seconds', round(time.time() - start, 3))
