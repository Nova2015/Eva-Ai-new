import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Copy, Download, Maximize2, RefreshCw, Share2, Sparkles, X, ZoomIn, ZoomOut,
} from 'lucide-react';
import { UNVERIFIED_IMAGE_NOTE } from '../lib/visualIntent';

/**
 * Slice 1 — in-chat image generation experience
 * =============================================
 * Renders a generation result inside the conversation: shimmer skeletons while
 * the images resolve, then a grid with per-image actions and a full-screen
 * viewer.
 *
 * Everything here is client-side on top of the EXISTING /image/generate-v2
 * endpoint. That endpoint returns a seeded Pollinations URL, which makes the
 * whole action set derivable without touching the backend:
 *   variations -> same prompt, new seeds
 *   upscale    -> SAME seed at larger dimensions, so it is genuinely the same
 *                 image at higher resolution rather than a different one
 *   regenerate -> fresh seeds for the whole set
 *
 * The viewer is portalled to document.body: the chat composer sits inside a
 * transformed ancestor, which would otherwise capture position:fixed (the same
 * containing-block trap that broke the camera modal).
 */

export function ImageSkeleton({ count = 4, label = 'Generating with EVA Vision…' }) {
  return (
    <div className="eva-img-wrap">
      <div className="eva-img-status">
        <Sparkles size={14} className="eva-img-spark" />
        <span>{label}</span>
      </div>
      <div className="eva-img-grid">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="eva-img-skel" style={{ animationDelay: `${i * 90}ms` }} />
        ))}
      </div>
      <ImageStyles />
    </div>
  );
}

export default function ImageResult({
  images = [], prompt = '', onRegenerate, onVariations, onUpscale,
}) {
  const [viewer, setViewer] = useState(null);   // index being viewed
  const [busy, setBusy] = useState('');
  const [toast, setToast] = useState('');

  const flash = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast(''), 2200);
  }, []);

  const download = useCallback(async (img, i) => {
    try {
      // Fetch as a blob so the file saves rather than opening a new tab.
      const r = await fetch(img.url);
      const blob = await r.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = `eva-${(prompt || 'image').slice(0, 40).replace(/[^\w-]+/g, '-')}-${i + 1}.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
      flash('Downloaded');
    } catch {
      window.open(img.url, '_blank', 'noopener');
    }
  }, [prompt, flash]);

  const share = useCallback(async (img) => {
    try {
      if (navigator.share) await navigator.share({ title: 'EVA image', text: prompt, url: img.url });
      else { await navigator.clipboard.writeText(img.url); flash('Link copied'); }
    } catch { /* user dismissed the share sheet */ }
  }, [prompt, flash]);

  const run = useCallback(async (name, fn, arg) => {
    if (!fn) return;
    setBusy(name);
    try { await fn(arg); } finally { setBusy(''); }
  }, []);

  if (!images.length) return null;

  return (
    <div className="eva-img-wrap">
      <div className="eva-img-grid">
        {images.map((img, i) => (
          <figure key={img.url + i} className="eva-img-cell">
            <img
              src={img.url}
              alt={`${prompt} (${i + 1})`}
              loading="lazy"
              onClick={() => setViewer(i)}
            />
            <figcaption className="eva-img-hover">
              <button type="button" title="Full screen" onClick={() => setViewer(i)}><Maximize2 size={14} /></button>
              <button type="button" title="Download" onClick={() => download(img, i)}><Download size={14} /></button>
              <button
                type="button"
                title="Upscale (same image, higher resolution)"
                onClick={() => run('upscale', onUpscale, img)}
              ><ZoomIn size={14} /></button>
              <button type="button" title="Share" onClick={() => share(img)}><Share2 size={14} /></button>
            </figcaption>
          </figure>
        ))}
      </div>

      <div className="eva-img-actions">
        <span style={{ color: 'red', fontSize: 11}}>  
          UPSCLE-TEST
        </span>
        
        <button type="button" disabled={!!busy} onClick={() => run('regen', onRegenerate)}>
          <RefreshCw size={13} className={busy === 'regen' ? 'eva-img-spin' : ''} /> Regenerate
        </button>

        <button type="button" disabled={!!busy} onClick={() => run('vary', onVariations)}>
          <Sparkles size={13} className={busy === 'vary' ? 'eva-img-spin' : ''} /> Variations
        </button>

        <button
          type="button"
          disabled={!!busy || !onUpscale}
          onClick={() => run('upscale', onUpscale, images[0])}
        >
          <ZoomIn size={13} className={busy === 'upscale' ? 'eva-img-spin' : ''} />
          Upscale
        </button>

        <button
          type="button"
          onClick={() => { navigator.clipboard.writeText(prompt); flash('Prompt copied'); }}
        >
          <Copy size={13} /> Copy prompt
        </button>

        {toast && <span className="eva-img-toast">{toast}</span>}
      </div>

      {/* Update 35c. Every other artifact EVA produces can be checked — a
          workbook opens, a chart's values trace to the source rows, a mermaid
          diagram is readable text. A generated image cannot, and one that
          looks like a diagram or a screenshot invites being read as fact.
          Saying so is the only honest option available here. */}
      <p className="eva-img-unverified">{UNVERIFIED_IMAGE_NOTE}</p>

      {viewer !== null && (
        <ImageViewer
          images={images}
          index={viewer}
          prompt={prompt}
          onClose={() => setViewer(null)}
          onIndex={setViewer}
          onDownload={download}
        />
      )}
      <ImageStyles />
    </div>
  );
}

/* ── Full-screen viewer: zoom, pan, keyboard nav ─────────────────────────── */
function ImageViewer({ images, index, prompt, onClose, onIndex, onDownload }) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef(null);
  const img = images[index];

  useEffect(() => { setZoom(1); setPan({ x: 0, y: 0 }); }, [index]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight' && index < images.length - 1) onIndex(index + 1);
      if (e.key === 'ArrowLeft' && index > 0) onIndex(index - 1);
      if (e.key === '+' || e.key === '=') setZoom((z) => Math.min(4, z + 0.25));
      if (e.key === '-') setZoom((z) => Math.max(1, z - 0.25));
    };
    window.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [index, images.length, onClose, onIndex]);

  const startDrag = (e) => {
    if (zoom === 1) return;
    const p = e.touches ? e.touches[0] : e;
    drag.current = { x: p.clientX - pan.x, y: p.clientY - pan.y };
  };
  const moveDrag = (e) => {
    if (!drag.current) return;
    const p = e.touches ? e.touches[0] : e;
    setPan({ x: p.clientX - drag.current.x, y: p.clientY - drag.current.y });
  };
  const endDrag = () => { drag.current = null; };

  return createPortal(
    <div className="eva-viewer" role="dialog" aria-modal="true" aria-label="Image preview">
      <header>
        <span className="eva-viewer-count">{index + 1} / {images.length}</span>
        <div className="eva-viewer-tools">
          <button type="button" onClick={() => setZoom((z) => Math.max(1, z - 0.25))} aria-label="Zoom out"><ZoomOut size={16} /></button>
          <span className="eva-viewer-zoom">{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => setZoom((z) => Math.min(4, z + 0.25))} aria-label="Zoom in"><ZoomIn size={16} /></button>
          <button type="button" onClick={() => onDownload(img, index)} aria-label="Download"><Download size={16} /></button>
          <button type="button" onClick={onClose} aria-label="Close preview"><X size={18} /></button>
        </div>
      </header>

      <div
        className="eva-viewer-stage"
        onMouseDown={startDrag} onMouseMove={moveDrag} onMouseUp={endDrag} onMouseLeave={endDrag}
        onTouchStart={startDrag} onTouchMove={moveDrag} onTouchEnd={endDrag}
        style={{ cursor: zoom > 1 ? (drag.current ? 'grabbing' : 'grab') : 'default' }}
      >
        <img
          src={img.url}
          alt={prompt}
          draggable={false}
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
          onDoubleClick={() => setZoom((z) => (z === 1 ? 2 : 1))}
        />
      </div>

      {images.length > 1 && (
        <nav className="eva-viewer-strip">
          {images.map((im, i) => (
            <button
              key={im.url + i}
              type="button"
              className={i === index ? 'is-active' : ''}
              onClick={() => onIndex(i)}
              aria-label={`Image ${i + 1}`}
            >
              <img src={im.url} alt="" loading="lazy" />
            </button>
          ))}
        </nav>
      )}
      <p className="eva-viewer-prompt">{prompt}</p>
    </div>,
    document.body,
  );
}

/* ── Styles (scoped by class; injected once per mount) ───────────────────── */
function ImageStyles() {
  return (
    <style>{`
      .eva-img-wrap{margin:2px 0 4px}
      .eva-img-status{display:flex;align-items:center;gap:7px;font-size:12.5px;
        color:var(--text2,#c6cbe6);margin-bottom:8px}
      .eva-img-spark{color:#7C5CFF;animation:evaImgPulse 1.4s ease-in-out infinite}
      .eva-img-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;max-width:520px}
      .eva-img-skel{aspect-ratio:1;border-radius:12px;
        background:linear-gradient(100deg,rgba(255,255,255,.045) 30%,rgba(124,92,255,.16) 50%,rgba(255,255,255,.045) 70%);
        background-size:220% 100%;animation:evaImgShimmer 1.25s linear infinite}
      .eva-img-cell{position:relative;margin:0;border-radius:12px;overflow:hidden;
        border:1px solid rgba(255,255,255,.09);background:#0d1120;aspect-ratio:1}
      .eva-img-cell img{width:100%;height:100%;object-fit:cover;display:block;cursor:zoom-in;
        opacity:0;animation:evaImgIn 420ms ease-out forwards}
      .eva-img-hover{position:absolute;inset:auto 0 0 0;display:flex;gap:6px;justify-content:center;
        padding:8px;background:linear-gradient(to top,rgba(6,8,18,.86),transparent);
        opacity:0;transition:opacity 160ms ease}
      .eva-img-cell:hover .eva-img-hover,.eva-img-cell:focus-within .eva-img-hover{opacity:1}
      .eva-img-hover button{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;
        border:1px solid rgba(255,255,255,.14);background:rgba(18,24,38,.82);color:#F8FAFC;cursor:pointer}
      .eva-img-hover button:hover{background:#7C5CFF;border-color:#7C5CFF}
      /* Legible, not shouty: a caveat nobody can read is the same as no
         caveat. #a3a3ad on the panel background measures above 4.5:1. */
      .eva-img-unverified{margin:8px 0 0;font-size:12px;line-height:1.5;
        color:#a3a3ad}
      .eva-img-actions{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:9px}
      .eva-img-actions button{display:inline-flex;align-items:center;gap:6px;padding:6px 11px;
        border-radius:9px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.04);
        color:var(--text2,#c6cbe6);font-size:12px;cursor:pointer;transition:background 150ms ease}
      .eva-img-actions button:hover:not(:disabled){background:rgba(124,92,255,.16);color:#F8FAFC}
      .eva-img-actions button:disabled{opacity:.5;cursor:default}
      .eva-img-toast{font-size:11.5px;color:#22C55E}
      .eva-img-spin{animation:evaImgSpin .9s linear infinite}
      @keyframes evaImgShimmer{from{background-position:180% 0}to{background-position:-80% 0}}
      @keyframes evaImgIn{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
      @keyframes evaImgPulse{0%,100%{opacity:.5}50%{opacity:1}}
      @keyframes evaImgSpin{to{transform:rotate(360deg)}}

      .eva-viewer{position:fixed;inset:0;z-index:5000;background:rgba(6,8,18,.95);
        display:flex;flex-direction:column;color:#F8FAFC}
      .eva-viewer header{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;
        padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.08)}
      .eva-viewer-count{font-size:12.5px;color:#94A3B8}
      .eva-viewer-tools{display:flex;align-items:center;gap:6px}
      .eva-viewer-tools button{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;
        border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.05);color:inherit;cursor:pointer}
      .eva-viewer-tools button:hover{background:rgba(124,92,255,.2)}
      .eva-viewer-zoom{font-size:12px;color:#94A3B8;min-width:42px;text-align:center}
      .eva-viewer-stage{flex:1 1 auto;min-height:0;display:flex;align-items:center;justify-content:center;
        overflow:hidden;padding:12px}
      .eva-viewer-stage img{max-width:100%;max-height:100%;object-fit:contain;
        transition:transform 140ms ease-out;user-select:none}
      .eva-viewer-strip{flex:0 0 auto;display:flex;gap:7px;justify-content:center;padding:8px;overflow-x:auto}
      .eva-viewer-strip button{width:52px;height:52px;padding:0;border-radius:9px;overflow:hidden;
        border:2px solid transparent;background:none;cursor:pointer;flex:0 0 auto}
      .eva-viewer-strip button.is-active{border-color:#7C5CFF}
      .eva-viewer-strip img{width:100%;height:100%;object-fit:cover;display:block}
      .eva-viewer-prompt{flex:0 0 auto;margin:0;padding:0 16px calc(12px + env(safe-area-inset-bottom));
        font-size:12px;color:#94A3B8;text-align:center;max-height:3.4em;overflow:hidden}

      @media (max-width:768px){
        .eva-img-grid{max-width:100%;gap:6px}
        .eva-img-hover{opacity:1;background:linear-gradient(to top,rgba(6,8,18,.7),transparent);padding:6px}
        .eva-img-hover button{width:34px;height:34px}
        .eva-img-actions button{padding:9px 12px;font-size:12.5px}
      }
      @media (prefers-reduced-motion: reduce){
        .eva-img-skel,.eva-img-spark,.eva-img-spin{animation:none}
        .eva-img-cell img{animation:none;opacity:1}
        .eva-viewer-stage img{transition:none}
      }
    `}</style>
  );
}
