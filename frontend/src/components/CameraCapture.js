import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Camera, RefreshCw, X } from 'lucide-react';

/**
 * Update 63 — Vision: camera capture
 * ==================================
 * Opens the device camera, shows a live preview, and turns a captured frame
 * into a normal image File. That File is handed to Chat's existing
 * handleSelectedFile(), so a photo travels the SAME path as an uploaded
 * image — vision agent, OCR, routing, memory, firewall, history. No new
 * backend endpoint and no second vision pipeline.
 *
 * Privacy: the stream is opened only on explicit user action and every track
 * is stopped on close, on unmount, and on tab hide. A camera left running is
 * a real problem, not a cosmetic one, so teardown is centralised in
 * stopStream() and called from every exit path.
 */
export default function CameraCapture({ open, onClose, onCapture }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [facing, setFacing] = useState('environment');
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [multiCam, setMultiCam] = useState(false);

  const stopStream = useCallback(() => {
    const s = streamRef.current;
    if (s) s.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setReady(false);
  }, []);

  const startStream = useCallback(async (mode) => {
    setError('');
    stopStream();
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser does not expose a camera API.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: mode, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setReady(true);
    } catch (e) {
      if (e.name === 'NotAllowedError') setError('Camera permission denied.');
      else if (e.name === 'NotFoundError') setError('No camera found on this device.');
      else setError(`Camera unavailable: ${e.name}`);
    }
  }, [stopStream]);

  useEffect(() => {
    if (!open) { stopStream(); return undefined; }
    startStream(facing);
    // Only offer the flip control when there really is more than one camera.
    navigator.mediaDevices?.enumerateDevices?.()
      .then((d) => setMultiCam(d.filter((x) => x.kind === 'videoinput').length > 1))
      .catch(() => {});
    return stopStream;
  }, [open, facing, startStream, stopStream]);

  // Never keep the camera live behind a hidden tab.
  useEffect(() => {
    const onHide = () => { if (document.hidden) stopStream(); };
    document.addEventListener('visibilitychange', onHide);
    return () => document.removeEventListener('visibilitychange', onHide);
  }, [stopStream]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && open) onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    // Un-mirror the selfie view so text in the frame stays readable for OCR.
    if (facing === 'user') {
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) { setError('Could not read a frame from the camera.'); return; }
      const file = new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
      stopStream();
      onCapture?.(file);
      onClose?.();
    }, 'image/jpeg', 0.9);
  }, [facing, onCapture, onClose, stopStream]);

  if (!open) return null;

  // Rendered into <body>, NOT in place. The component is mounted inside the
  // chat composer, and an ancestor in the page shell uses transform /
  // backdrop-filter — either of which makes it the containing block for
  // position:fixed descendants. That is why `inset:0` was resolving to the
  // composer's box near the bottom of the page instead of the viewport: the
  // sheet opened mid-page with its controls pushed off-screen, and the mobile
  // full-screen rules looked like they were being ignored. A portal escapes
  // any such ancestor, which is why modals belong on document.body.
  return createPortal(
    <div className="eva-cam-backdrop" role="dialog" aria-modal="true" aria-label="Camera">
      <div className="eva-cam-panel">
        <div className="eva-cam-head">
          <span>Camera</span>
          <button type="button" onClick={onClose} aria-label="Close camera"><X size={17} /></button>
        </div>

        <div className="eva-cam-stage">
          {error ? (
            <div className="eva-cam-error">{error}</div>
          ) : (
            <video
              ref={videoRef}
              playsInline
              muted
              className={facing === 'user' ? 'is-mirrored' : ''}
            />
          )}
        </div>

        <div className="eva-cam-actions">
          <button type="button" onClick={onClose}>Cancel</button>
          {multiCam && !error && (
            <button
              type="button"
              onClick={() => setFacing((f) => (f === 'user' ? 'environment' : 'user'))}
              title="Switch camera"
            >
              <RefreshCw size={16} /><span>Flip</span>
            </button>
          )}
          <button
            type="button"
            className="eva-cam-shutter"
            onClick={capture}
            disabled={!ready || !!error}
          >
            <Camera size={17} /><span>Capture</span>
          </button>
        </div>
        <p className="eva-cam-hint">
          The photo is attached to your next message — ask about it, or send it alone to have EVA describe it.
        </p>
      </div>

      <style>{`
        .eva-cam-backdrop{position:fixed;inset:0;z-index:4000;background:rgba(6,8,18,.72);
          display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(3px)}
        /* Column layout with a hard height cap: the video stage flexes and the
           controls never leave the viewport. dvh tracks mobile browser chrome
           (collapsing URL bar); the vh line above it is the fallback. */
        .eva-cam-panel{width:min(560px,100%);
          max-height:calc(100vh - 32px);
          max-height:calc(100dvh - 32px);
          display:flex;flex-direction:column;
          background:var(--eva-surface,#141826);
          border:1px solid var(--eva-border,#2a2f45);border-radius:16px;overflow:hidden;
          box-shadow:0 18px 50px rgba(0,0,0,.45);color:inherit}
        .eva-cam-head{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;
          padding:11px 14px;border-bottom:1px solid var(--eva-border,#2a2f45);font-size:14px;font-weight:600}
        .eva-cam-head button{background:none;border:0;color:inherit;cursor:pointer;padding:4px;border-radius:8px}
        /* min-height:0 is what actually lets a flex child shrink below its
           aspect-ratio height — without it the stage refuses to compress and
           pushes the buttons off-screen. */
        .eva-cam-stage{flex:1 1 auto;min-height:0;aspect-ratio:4/3;background:#05070f;
          display:flex;align-items:center;justify-content:center;overflow:hidden}
        .eva-cam-stage video{width:100%;height:100%;object-fit:cover}
        .eva-cam-stage video.is-mirrored{transform:scaleX(-1)}
        .eva-cam-error{color:#f87171;font-size:13px;padding:20px;text-align:center}
        .eva-cam-actions{flex:0 0 auto;display:flex;gap:10px;justify-content:center;
          padding:13px;background:var(--eva-surface,#141826)}
        .eva-cam-actions button{display:inline-flex;align-items:center;gap:7px;padding:11px 18px;
          border-radius:999px;border:1px solid var(--eva-border,#2a2f45);
          background:var(--eva-surface-2,#1b2033);color:inherit;cursor:pointer;font-size:13px}
        .eva-cam-shutter{background:#8b5cf6!important;border-color:#8b5cf6!important;color:#fff!important}
        .eva-cam-actions button:disabled{opacity:.5;cursor:default}
        .eva-cam-hint{flex:0 0 auto;font-size:11.5px;opacity:.6;text-align:center;padding:0 16px 14px;margin:0}

        /* Mobile: full-screen sheet with the controls pinned to the bottom,
           the pattern used by every native camera UI. */
        @media (max-width:768px){
          .eva-cam-backdrop{padding:0}
          .eva-cam-panel{width:100%;height:100vh;height:100dvh;
            max-height:100vh;max-height:100dvh;border:0;border-radius:0}
          .eva-cam-stage{aspect-ratio:auto}
          .eva-cam-actions{padding:14px 14px calc(14px + env(safe-area-inset-bottom))}
          .eva-cam-actions button{padding:13px 20px;font-size:14px}
          .eva-cam-hint{display:none}
        }
        /* Landscape phones have almost no vertical room — drop the chrome. */
        @media (max-height:430px){
          .eva-cam-head{padding:7px 12px;font-size:13px}
          .eva-cam-actions{padding:8px}
          .eva-cam-hint{display:none}
        }
      `}</style>
    </div>,
    document.body,
  );
}
