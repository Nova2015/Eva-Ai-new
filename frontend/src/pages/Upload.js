import { useState, useRef, useEffect, useCallback } from 'react';

// RAG document storage lives on the HF service (persistent Supabase), not Render.
const RAG_API = process.env.REACT_APP_RAG_API_BASE || 'http://127.0.0.1:7860';

export default function Upload({ API }) {
  const [uploadStatus, setUploadStatus] = useState('');
  const [dragging, setDragging]         = useState(false);
  const [docs, setDocs]                 = useState([]);
  const [kbStats, setKbStats]           = useState(null);
  const [uploading, setUploading]       = useState(false);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(() => localStorage.getItem('eva_selected_workspace_id') || 'default-org');
  const inputRef = useRef();

  useEffect(() => {
    const syncWorkspace = () => setSelectedWorkspaceId(localStorage.getItem('eva_selected_workspace_id') || 'default-org');
    window.addEventListener('storage', syncWorkspace);
    window.addEventListener('eva:workspace-selected', syncWorkspace);
    return () => {
      window.removeEventListener('storage', syncWorkspace);
      window.removeEventListener('eva:workspace-selected', syncWorkspace);
    };
  }, []);

  const refreshToken = useCallback(async () => {
    try {
      const { getAuth } = await import('firebase/auth');
      const user = getAuth().currentUser;
      if (user) {
        const fresh = await user.getIdToken(true);
        localStorage.setItem('aria_token', fresh);
        return fresh;
      }
    } catch {}
    const stored = localStorage.getItem('aria_token');
    if (stored) return stored;
    throw new Error('Please login again');
  }, []);

  const getToken = useCallback(async ({ forceRefresh = false } = {}) => {
    const token = localStorage.getItem('aria_token');
    if (token && !forceRefresh) return token;
    return refreshToken();
  }, [refreshToken]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const safeGetToken = useCallback(async () => {
    try { return await getToken(); }
    catch { setUploadStatus('🔐 Please login again to upload files.'); return null; }
  }, [getToken]);

  const fetchWithAuth = useCallback(async (url, options = {}, retry = true) => {
    const token = localStorage.getItem('aria_token');
    if (!token) {
      setUploadStatus('🔐 Please login again to upload files.');
      throw new Error('No token');
    }
    const headers = { Authorization: `Bearer ${token}`, 'ngrok-skip-browser-warning': 'true' };
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401 && retry) {
      try {
        const fresh = await refreshToken();
        const h2 = { Authorization: `Bearer ${fresh}`, 'ngrok-skip-browser-warning': 'true' };
        if (options.body && !(options.body instanceof FormData)) h2['Content-Type'] = 'application/json';
        return fetch(url, { ...options, headers: h2 });
      } catch {
        setUploadStatus('🔐 Please login again to upload files.');
        throw new Error('Please login again');
      }
    }
    return res;
  }, [refreshToken]);

  // ── Load real documents & KB stats ──────────────────────
  const loadDocs = useCallback(async () => {
    try {
      const token = await safeGetToken();
      if (!token) return;

      const [docsRes, statsRes] = await Promise.all([
        fetchWithAuth(`${RAG_API}/rag/documents?workspace_id=${encodeURIComponent(selectedWorkspaceId || 'default-org')}`),
        fetch(`${API}/health`, {
          headers: { 'ngrok-skip-browser-warning': 'true' },
        }),
      ]);

      if (docsRes.ok) {
        const data = await docsRes.json();
        setDocs(Array.isArray(data) ? data : data.documents || []);
      }
      if (statsRes.ok) {
        const data = await statsRes.json();
        setKbStats(data);
      }
    } catch (e) {
      console.error('Load error:', e);
      setUploadStatus(`Auth error: ${e.message}`);
    }
  }, [API, fetchWithAuth, safeGetToken, selectedWorkspaceId]);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  // ── Upload single file ───────────────────────────────────
  const uploadSingleFile = async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('workspace_id', selectedWorkspaceId || 'default-org');
    const res = await fetchWithAuth(`${RAG_API}/rag/upload`, {
      method: 'POST',
      body: fd,
    });
    return res.json();
  };

  const pollUploadJob = async (jobId, onUpdate = () => {}) => {
    const terminal = new Set(['COMPLETE', 'FAILED', 'CANCELLED']);
    while (true) {
      const res = await fetchWithAuth(`${RAG_API}/rag/jobs/${encodeURIComponent(jobId)}`);
      if (!res.ok) throw new Error(`Upload job ${jobId} not found`);
      const job = await res.json();
      onUpdate(job);
      if (terminal.has(job.status)) {
        if (job.status !== 'COMPLETE') throw new Error(job.error || job.message || `Upload job ${job.status}`);
        return job;
      }
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
  };

  // ── Handle upload (file or ZIP) ──────────────────────────
  const uploadFile = async (file) => {
    if (!file) return;
    setUploading(true);
    setUploadStatus(`⏳ Uploading ${file.name}...`);

    const token = await safeGetToken();
    if (!token) { setUploading(false); return; }

    // ── ZIP: extract and upload each file ──────────────────
    if (file.name.endsWith('.zip')) {
      try {
        // Dynamically load JSZip from CDN
        if (!window.JSZip) {
          await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
          });
        }

        const zip = await window.JSZip.loadAsync(file);
        const supported = ['.pdf', '.docx', '.png', '.jpg', '.jpeg', '.txt'];
        const entries = [];

        zip.forEach((path, entry) => {
          if (!entry.dir && supported.some(ext => path.toLowerCase().endsWith(ext))) {
            entries.push({ path, entry });
          }
        });

        if (entries.length === 0) {
          setUploadStatus('❌ ZIP has no supported files (PDF, DOCX, PNG, JPG, TXT)');
          setUploading(false);
          return;
        }

        let done = 0;
        for (const { path, entry } of entries) {
          const fname = path.split('/').pop();
          setUploadStatus(`⏳ Uploading ${done + 1}/${entries.length}: ${fname}`);
          try {
            const blob = await entry.async('blob');
            const f = new File([blob], fname);
            const data = await uploadSingleFile(f, token);
            if (!data.job_id) throw new Error(data.detail || 'Upload job was not created');
            await pollUploadJob(data.job_id, (job) => {
              setUploadStatus(`${job.status}: ${job.message || job.current_step || fname}`);
            });
            done++;
          } catch (e) {
            console.error(`Failed: ${fname}`, e);
          }
        }

        setUploadStatus(`✅ Uploaded ${done}/${entries.length} files from ZIP`);
        loadDocs();

      } catch (e) {
        setUploadStatus(`❌ ZIP extraction failed: ${e.message}`);
      }

    } else {
      // ── Normal file upload ─────────────────────────────
      try {
        const data = await uploadSingleFile(file, token);
        if (!data.job_id) throw new Error(data.detail || 'Upload job was not created');
        setUploadStatus(`QUEUED: ${data.message || file.name}`);
        const job = await pollUploadJob(data.job_id, (nextJob) => {
          setUploadStatus(`${nextJob.status}: ${nextJob.message || nextJob.current_step || file.name}`);
        });
        setUploadStatus(`COMPLETE: ${job.chunk_count || 0} chunks indexed`);
        loadDocs();
      } catch (e) {
        setUploadStatus(`❌ Upload failed: ${e.message}`);
      }
    }

    setUploading(false);
  };

  // ── Status color ─────────────────────────────────────────
  const statusColor = (s) => {
    const sl = (s || '').toLowerCase();
    if (sl.includes('index') || sl.includes('done') || sl.includes('success')) return 'var(--green, #4ade80)';
    if (sl.includes('process') || sl.includes('pending')) return 'var(--warn, #fbbf24)';
    if (sl.includes('fail') || sl.includes('error')) return 'var(--red, #f87171)';
    return 'var(--accent, #3b82f6)';
  };

  const fileIcon = (name = '') => {
    if (name.endsWith('.pdf')) return '📕';
    if (name.endsWith('.docx') || name.endsWith('.doc')) return '📘';
    if (name.endsWith('.png') || name.endsWith('.jpg') || name.endsWith('.jpeg')) return '🖼️';
    if (name.endsWith('.zip')) return '🗜️';
    if (name.endsWith('.txt')) return '📄';
    return '📁';
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: '1rem', color: 'var(--text)', fontWeight: 700 }}>Document Upload</div>
          <div style={{ fontSize: '0.65rem', color: 'var(--text3)', fontFamily: 'var(--mono)', marginTop: 2 }}>OCR → Embeddings → Vector Index</div>
        </div>
        <button onClick={loadDocs}
          style={{ padding: '6px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text3)', fontSize: '0.72rem', cursor: 'pointer' }}>
          🔄 Refresh
        </button>
      </div>

      {/* Drop Zone */}
      <div
        onClick={() => inputRef.current.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); uploadFile(e.dataTransfer.files[0]); }}
        style={{
          border: `2px dashed ${dragging ? 'var(--accent, #3b82f6)' : 'var(--border2, #1e2d45)'}`,
          borderRadius: 14, padding: 40, textAlign: 'center', cursor: 'pointer',
          background: dragging ? 'rgba(59,130,246,0.06)' : 'rgba(59,130,246,0.02)',
          marginBottom: 20, transition: 'all 0.3s',
        }}>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.png,.jpg,.jpeg,.txt,.zip"
          style={{ display: 'none' }}
          onChange={e => uploadFile(e.target.files[0])}
        />
        <div style={{ fontSize: '2.5rem', marginBottom: 10 }}>📂</div>
        <div style={{ fontSize: '1rem', color: 'var(--text)', fontWeight: 600, marginBottom: 6 }}>
          Drop files here or click to browse
        </div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text3)', marginBottom: 14 }}>
          PDF, DOCX, PNG, JPG, TXT, ZIP — OCR processed automatically
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
          {['📄 PDF', '📝 DOCX', '🖼 PNG/JPG', '🗜️ ZIP'].map(t => (
            <span key={t} style={{ padding: '3px 10px', borderRadius: 20, fontSize: '0.62rem', fontFamily: 'var(--mono)', border: '1px solid var(--border2, #1e2d45)', color: 'var(--text3)' }}>{t}</span>
          ))}
        </div>
        {uploadStatus && (
          <div style={{
            marginTop: 12, fontSize: '0.72rem',
            color: uploadStatus.startsWith('✅') ? 'var(--green, #4ade80)' : uploadStatus.startsWith('❌') ? 'var(--red, #f87171)' : 'var(--warn, #fbbf24)',
          }}>{uploadStatus}</div>
        )}
        {uploading && (
          <div style={{ marginTop: 8, height: 3, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: '60%', background: 'linear-gradient(90deg, #3b82f6, #8b5cf6)', borderRadius: 2, animation: 'slide 1.5s infinite' }} />
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>

        {/* ── Real Doc List ── */}
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontSize: '0.75rem', fontWeight: 600, display: 'flex', justifyContent: 'space-between' }}>
            <span>Indexed Documents</span>
            <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)', fontSize: '0.62rem' }}>{docs.length} files</span>
          </div>

          {docs.length === 0 ? (
            <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text3)', fontSize: '0.75rem' }}>
              No files in this workspace yet.<br />Upload a file to start.
            </div>
          ) : (
            docs.map((doc, i) => {
              const name = doc.filename || doc.name || `Document ${i + 1}`;
              const status = doc.status || 'Indexed';
              const color = statusColor(status);
              const prog = status.toLowerCase().includes('fail') ? 100
                : status.toLowerCase().includes('process') ? 60 : 100;
              const meta = [
                doc.pages && `${doc.pages} pages`,
                doc.chunks && `${doc.chunks} chunks`,
                doc.created_at && new Date(doc.created_at * 1000).toLocaleDateString(),
              ].filter(Boolean).join(' · ') || status;

              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', borderBottom: '1px solid rgba(30,45,69,0.6)' }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.1rem', background: `${color}18`, flexShrink: 0 }}>
                    {fileIcon(name)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.78rem', fontWeight: 500, color: 'var(--text)', marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
                    <div style={{ fontSize: '0.62rem', color: 'var(--text3)', fontFamily: 'var(--mono)', marginBottom: 4 }}>{meta}</div>
                    <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${prog}%`, background: status.toLowerCase().includes('fail') ? 'var(--red, #f87171)' : status.toLowerCase().includes('process') ? 'var(--warn, #fbbf24)' : 'linear-gradient(90deg, var(--accent, #3b82f6), #8b5cf6)', borderRadius: 2 }} />
                    </div>
                  </div>
                  <span style={{ padding: '2px 8px', borderRadius: 20, fontSize: '0.6rem', fontFamily: 'var(--mono)', background: `${color}18`, color, border: `1px solid ${color}40`, flexShrink: 0 }}>{status}</span>
                </div>
              );
            })
          )}
        </div>

        {/* ── Real KB Stats ── */}
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--text)', fontWeight: 600, marginBottom: 12 }}>🧠 Knowledge Base Stats</div>

          {kbStats ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
                {[
                  [kbStats.total_chunks ?? kbStats.chunk_count ?? kbStats.chunks ?? '—', 'Total Chunks'],
                  [kbStats.total_docs ?? kbStats.document_count ?? kbStats.documents ?? docs.length, 'Active Docs'],
                  [kbStats.vector_dims ?? kbStats.embedding_dim ?? '—', 'Vector Dims'],
                  [kbStats.index_type ?? kbStats.vector_store ?? 'FAISS', 'Index Type'],
                ].map(([val, lbl]) => (
                  <div key={lbl} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                    <div style={{ fontSize: '1.2rem', fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--accent, #3b82f6)' }}>{String(val)}</div>
                    <div style={{ fontSize: '0.6rem', color: 'var(--text3)', marginTop: 2 }}>{lbl}</div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text3)', fontFamily: 'var(--mono)' }}>
                Status: {kbStats.status || 'online'} · v{kbStats.version || '3.0'}
              </div>
            </>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
              {['Total Chunks', 'Active Docs', 'Vector Dims', 'Index Type'].map(lbl => (
                <div key={lbl} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--border)' }}>—</div>
                  <div style={{ fontSize: '0.6rem', color: 'var(--text3)', marginTop: 2 }}>{lbl}</div>
                </div>
              ))}
            </div>
          )}

          <button onClick={loadDocs}
            style={{ marginTop: 10, width: '100%', padding: '8px', borderRadius: 7, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text3)', fontSize: '0.72rem', cursor: 'pointer' }}>
            🔄 Rebuild Index
          </button>
        </div>

      </div>
    </div>
  );
}
