import { useEffect, useRef } from 'react';

/**
 * Slice 3 — voice visualisation
 * =============================
 * Canvas orb + spectrum ring driven by REAL microphone amplitude via an
 * AnalyserNode, not a decorative loop. On a voice UI a waveform that ignores
 * your voice is immediately obvious, so when the panel is open we tap the mic
 * and render actual FFT data; if that is unavailable (permission denied, no
 * AudioContext) it degrades to a calm breathing pulse rather than pretending.
 *
 * The analyser stream is opened only while the panel is EXPANDED and torn down
 * on collapse — wake-word mode already holds the mic open continuously, and a
 * second always-on stream would cost battery for something nobody is looking at.
 */

const STATE_COLOR = {
  idle:     ['#7C5CFF', '#38BDF8'],
  armed:    ['#22C55E', '#4ADE80'],
  thinking: ['#F59E0B', '#FBBF24'],
  speaking: ['#38BDF8', '#7C5CFF'],
};

export default function VoiceOrb({ state = 'idle', size = 168, active = true }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(0);
  const audioRef = useRef({ ctx: null, analyser: null, stream: null, data: null });
  const stateRef = useRef(state);
  stateRef.current = state;

  // ── Mic tap (only while the panel is open) ────────────────────────────
  useEffect(() => {
    let cancelled = false;
    if (!active) return undefined;

    (async () => {
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC || !navigator.mediaDevices?.getUserMedia) return;
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        const ctx = new AC();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 128;
        analyser.smoothingTimeConstant = 0.75;
        ctx.createMediaStreamSource(stream).connect(analyser);
        audioRef.current = {
          ctx, analyser, stream, data: new Uint8Array(analyser.frequencyBinCount),
        };
      } catch {
        /* no analyser — the draw loop falls back to a breathing pulse */
      }
    })();

    return () => {
      cancelled = true;
      const { ctx, stream } = audioRef.current;
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close?.();
      audioRef.current = { ctx: null, analyser: null, stream: null, data: null };
    };
  }, [active]);

  // ── Draw loop ─────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    const ctx2d = canvas.getContext('2d');
    ctx2d.scale(dpr, dpr);

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const BARS = 64;
    const cx = size / 2;
    const cy = size / 2;
    const baseR = size * 0.26;
    let t = 0;

    const draw = () => {
      const [c1, c2] = STATE_COLOR[stateRef.current] || STATE_COLOR.idle;
      const { analyser, data } = audioRef.current;
      t += reduced ? 0 : 0.018;

      ctx2d.clearRect(0, 0, size, size);

      // Amplitude: real FFT when available, otherwise a slow breath.
      let level = 0;
      let spectrum = null;
      if (analyser && data) {
        analyser.getByteFrequencyData(data);
        spectrum = data;
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) sum += data[i];
        level = sum / data.length / 255;
      } else {
        level = 0.18 + Math.sin(t * 1.6) * 0.06;
      }
      // Thinking/speaking are EVA's turn — the mic level is irrelevant, so
      // drive those from a synthetic pulse instead of ambient room noise.
      if (stateRef.current === 'thinking') level = 0.3 + Math.sin(t * 4) * 0.12;
      if (stateRef.current === 'speaking') level = 0.4 + Math.sin(t * 6.5) * 0.18;

      // Spectrum ring
      for (let i = 0; i < BARS; i += 1) {
        const frac = i / BARS;
        const ang = frac * Math.PI * 2 - Math.PI / 2;
        let mag;
        if (spectrum && stateRef.current !== 'speaking' && stateRef.current !== 'thinking') {
          mag = spectrum[Math.floor(frac * spectrum.length)] / 255;
        } else {
          mag = level * (0.6 + 0.4 * Math.abs(Math.sin(t * 3 + frac * Math.PI * 4)));
        }
        const inner = baseR + size * 0.055;
        const len = size * 0.02 + mag * size * 0.13;
        const grad = ctx2d.createLinearGradient(
          cx + Math.cos(ang) * inner, cy + Math.sin(ang) * inner,
          cx + Math.cos(ang) * (inner + len), cy + Math.sin(ang) * (inner + len),
        );
        grad.addColorStop(0, c1);
        grad.addColorStop(1, c2);
        ctx2d.strokeStyle = grad;
        ctx2d.lineWidth = Math.max(1.5, size * 0.011);
        ctx2d.lineCap = 'round';
        ctx2d.beginPath();
        ctx2d.moveTo(cx + Math.cos(ang) * inner, cy + Math.sin(ang) * inner);
        ctx2d.lineTo(cx + Math.cos(ang) * (inner + len), cy + Math.sin(ang) * (inner + len));
        ctx2d.stroke();
      }

      // Core orb, breathing with the same level
      const r = baseR * (1 + level * 0.14);
      const orb = ctx2d.createRadialGradient(cx - r * 0.3, cy - r * 0.35, r * 0.1, cx, cy, r);
      orb.addColorStop(0, c2);
      orb.addColorStop(0.55, c1);
      orb.addColorStop(1, 'rgba(9,11,20,0.96)');
      ctx2d.fillStyle = orb;
      ctx2d.beginPath();
      ctx2d.arc(cx, cy, r, 0, Math.PI * 2);
      ctx2d.fill();

      // Soft halo
      ctx2d.strokeStyle = c1;
      ctx2d.globalAlpha = 0.22 + level * 0.3;
      ctx2d.lineWidth = Math.max(1, size * 0.006);
      ctx2d.beginPath();
      ctx2d.arc(cx, cy, r + size * 0.03, 0, Math.PI * 2);
      ctx2d.stroke();
      ctx2d.globalAlpha = 1;

      rafRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(rafRef.current);
  }, [size]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size, display: 'block' }}
      aria-hidden="true"
    />
  );
}
