import { useCallback, useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader';

/*
 * EVA CAD Studio — AI 3D → 2D Engineering Drawing
 * -------------------------------------------------------------
 * Fully client-side. Upload an .stl / .obj (or load a sample impeller),
 * inspect it in a real three.js viewer, then generate a 2D engineering
 * drawing (orthographic + isometric line views on an SVG sheet with a
 * title block). Ports the standalone CADX Studio prototype into EVA's
 * CRA frontend, matching the EVA dark theme.
 *
 * Known limitation: feature edges are extracted with EdgesGeometry and
 * projected per view. Hidden-line removal is NOT performed, so occluded
 * edges are still drawn (wireframe-style projection, not true drafting).
 */

const C = {
  bg: 'var(--bg, #0a0a0c)',
  panel: 'var(--panel, #111318)',
  panel2: 'var(--panel-2, #0d0f14)',
  border: 'var(--border, #23262f)',
  borderSoft: 'rgba(148,163,184,.16)',
  text: 'var(--text, #f3f5f8)',
  muted: 'var(--muted, #9aa4b2)',
  accent: 'var(--accent, #2f6bff)',
  accentSoft: 'rgba(47,107,255,.16)',
};

const MAX_BYTES = 40 * 1024 * 1024; // 40 MB

const SHEETS = {
  A4: { w: 297, h: 210 },
  A3: { w: 420, h: 297 },
  A2: { w: 594, h: 420 },
};

const STEPS = [
  { id: 1, label: 'Model source' },
  { id: 2, label: 'Review geometry' },
  { id: 3, label: 'Drawing setup' },
  { id: 4, label: 'Generate' },
];

// ------------------------------------------------------------------
// Geometry helpers
// ------------------------------------------------------------------

// Build a procedural impeller / fan sample (hub + angled blades).
function buildSampleImpeller() {
  const parts = [];
  const hub = new THREE.CylinderGeometry(10, 10, 20, 48);
  parts.push(hub);
  const bladeCount = 7;
  for (let i = 0; i < bladeCount; i += 1) {
    const blade = new THREE.BoxGeometry(30, 3, 12);
    const angle = (i / bladeCount) * Math.PI * 2;
    const m = new THREE.Matrix4();
    const rot = new THREE.Matrix4().makeRotationY(angle);
    const tilt = new THREE.Matrix4().makeRotationZ(0.5);
    const move = new THREE.Matrix4().makeTranslation(20, 0, 0);
    m.multiply(rot).multiply(move).multiply(tilt);
    blade.applyMatrix4(m);
    parts.push(blade);
  }
  // Merge by concatenating position attributes (non-indexed).
  const merged = mergeGeometries(parts.map((g) => g.toNonIndexed()));
  merged.computeVertexNormals();
  return merged;
}

// Minimal geometry merge (position + normal) to avoid extra deps.
function mergeGeometries(geoms) {
  let total = 0;
  geoms.forEach((g) => { total += g.getAttribute('position').count; });
  const positions = new Float32Array(total * 3);
  let offset = 0;
  geoms.forEach((g) => {
    const p = g.getAttribute('position').array;
    positions.set(p, offset);
    offset += p.length;
  });
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  return out;
}

function computeStats(geometry) {
  const pos = geometry.getAttribute('position');
  const vertexCount = pos.count;
  const triCount = geometry.index ? geometry.index.count / 3 : vertexCount / 3;
  geometry.computeBoundingBox();
  const bb = geometry.boundingBox;
  const size = new THREE.Vector3();
  bb.getSize(size);
  // Signed-volume via divergence theorem over triangles (non-indexed assumed).
  let vol = 0;
  const arr = pos.array;
  const stride = 9;
  for (let i = 0; i + stride <= arr.length; i += stride) {
    const ax = arr[i], ay = arr[i + 1], az = arr[i + 2];
    const bx = arr[i + 3], by = arr[i + 4], bz = arr[i + 5];
    const cx = arr[i + 6], cy = arr[i + 7], cz = arr[i + 8];
    vol += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6;
  }
  return {
    vertexCount,
    triCount: Math.round(triCount),
    size: { x: size.x, y: size.y, z: size.z },
    volume: Math.abs(vol),
  };
}

// ------------------------------------------------------------------
// 2D projection: extract feature edges and project per view.
// Returns array of [x1,y1,x2,y2] in world-projected units (mm).
// ------------------------------------------------------------------

// View basis: u (screen right), v (screen up) as world vectors.
const VIEW_BASIS = {
  Front: { u: new THREE.Vector3(1, 0, 0), v: new THREE.Vector3(0, 1, 0) },   // look -Z
  Top: { u: new THREE.Vector3(1, 0, 0), v: new THREE.Vector3(0, 0, 1) },     // look -Y (top down)
  Right: { u: new THREE.Vector3(0, 0, -1), v: new THREE.Vector3(0, 1, 0) },  // look -X
};

function isoBasis() {
  // Standard isometric: camera along (1,1,1).
  const dir = new THREE.Vector3(1, 1, 1).normalize();
  const up = new THREE.Vector3(0, 1, 0);
  const u = new THREE.Vector3().crossVectors(up, dir).normalize(); // screen right
  const v = new THREE.Vector3().crossVectors(dir, u).normalize();  // screen up
  return { u, v };
}

function projectEdges(edgeGeom, basis) {
  const p = edgeGeom.getAttribute('position').array;
  const segs = [];
  const vec = new THREE.Vector3();
  const proj = (i) => {
    vec.set(p[i], p[i + 1], p[i + 2]);
    return { x: vec.dot(basis.u), y: vec.dot(basis.v) };
  };
  for (let i = 0; i + 6 <= p.length; i += 6) {
    const a = proj(i);
    const b = proj(i + 3);
    segs.push([a.x, a.y, b.x, b.y]);
  }
  return segs;
}

function segsBounds(segs) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  segs.forEach(([x1, y1, x2, y2]) => {
    minX = Math.min(minX, x1, x2); maxX = Math.max(maxX, x1, x2);
    minY = Math.min(minY, y1, y2); maxY = Math.max(maxY, y1, y2);
  });
  if (!isFinite(minX)) return { minX: 0, minY: 0, maxX: 1, maxY: 1, w: 1, h: 1 };
  return { minX, minY, maxX, maxY, w: maxX - minX || 1, h: maxY - minY || 1 };
}

// Cell placement per projection method. Grid 2 cols x 2 rows.
// Returns { Front, Top, Right, Iso } -> {col,row}
function cellLayout(method) {
  if (method === 'first') {
    return { Front: { c: 1, r: 0 }, Right: { c: 0, r: 0 }, Top: { c: 1, r: 1 }, Iso: { c: 0, r: 1 } };
  }
  // third-angle (default)
  return { Top: { c: 0, r: 0 }, Iso: { c: 1, r: 0 }, Front: { c: 0, r: 1 }, Right: { c: 1, r: 1 } };
}

function esc(s) { return String(s || '').replace(/[<>&]/g, (ch) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[ch])); }

// Build the full SVG drawing sheet.
function buildDrawingSVG({ edgeGeom, views, method, sheet, orientation, units, scaleMode, dims, title }) {
  const sheetDef = SHEETS[sheet] || SHEETS.A4;
  let W = sheetDef.w, H = sheetDef.h;
  if (orientation === 'portrait') { const t = W; W = H; H = t; }

  const margin = 10;
  const tbW = 120, tbH = 40; // title block
  // Drawing area (excluding border margin).
  const areaX = margin, areaY = margin;
  const areaW = W - margin * 2;
  const areaH = H - margin * 2;

  const layout = cellLayout(method);
  const active = ['Front', 'Top', 'Right', 'Iso'].filter((v) => views[v]);

  // Compute projected segments + bounds per active view.
  const projected = {};
  active.forEach((name) => {
    const basis = name === 'Iso' ? isoBasis() : VIEW_BASIS[name];
    const segs = projectEdges(edgeGeom, basis);
    projected[name] = { segs, b: segsBounds(segs) };
  });

  // Cell grid geometry.
  const cols = 2, rows = 2;
  const gap = 8;
  const cellW = (areaW - gap) / cols;
  const cellH = (areaH - gap) / rows;
  const pad = 10;

  // Global scale so all views share one scale (Auto) or fixed ratio.
  let scaleFactor;
  if (scaleMode === 'auto') {
    let best = Infinity;
    active.forEach((name) => {
      const { b } = projected[name];
      best = Math.min(best, (cellW - pad * 2) / b.w, (cellH - pad * 2) / b.h);
    });
    scaleFactor = isFinite(best) ? best : 1;
  } else {
    const map = { '1:1': 1, '1:2': 0.5, '2:1': 2 };
    scaleFactor = map[scaleMode] || 1;
  }

  const parts = [];
  // Sheet + border.
  parts.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#ffffff"/>`);
  parts.push(`<rect x="${margin - 4}" y="${margin - 4}" width="${W - (margin - 4) * 2}" height="${H - (margin - 4) * 2}" fill="none" stroke="#111" stroke-width="0.6"/>`);
  parts.push(`<rect x="${areaX}" y="${areaY}" width="${areaW}" height="${areaH}" fill="none" stroke="#111" stroke-width="0.3"/>`);

  const viewLabels = { Front: 'FRONT', Top: 'TOP', Right: 'RIGHT SIDE', Iso: 'ISOMETRIC' };

  active.forEach((name) => {
    const cell = layout[name] || { c: 0, r: 0 };
    const cx0 = areaX + cell.c * (cellW + gap);
    const cy0 = areaY + cell.r * (cellH + gap);
    const { segs, b } = projected[name];
    const drawW = b.w * scaleFactor;
    const drawH = b.h * scaleFactor;
    // Center within cell.
    const ox = cx0 + (cellW - drawW) / 2;
    const oy = cy0 + (cellH - drawH) / 2;
    // Map a projected point -> sheet coords (SVG y is down, so flip v).
    const mapX = (x) => ox + (x - b.minX) * scaleFactor;
    const mapY = (y) => oy + (b.maxY - y) * scaleFactor;

    const lines = segs.map(([x1, y1, x2, y2]) =>
      `<line x1="${mapX(x1).toFixed(2)}" y1="${mapY(y1).toFixed(2)}" x2="${mapX(x2).toFixed(2)}" y2="${mapY(y2).toFixed(2)}"/>`
    ).join('');
    parts.push(`<g stroke="#111" stroke-width="0.35" stroke-linecap="round" fill="none">${lines}</g>`);
    parts.push(`<text x="${(cx0 + cellW / 2).toFixed(1)}" y="${(cy0 + cellH - 3).toFixed(1)}" font-family="Arial" font-size="4" fill="#333" text-anchor="middle">${viewLabels[name]}</text>`);

    // Dimension annotations on the Front view (overall W x H).
    if (dims && name === 'Front') {
      const dimOffset = 6;
      const dimY = oy + drawH + dimOffset;
      const wMM = b.w;
      const hMM = b.h;
      const unitLabel = units === 'inch' ? '"' : '';
      const wTxt = units === 'inch' ? (wMM / 25.4).toFixed(2) : wMM.toFixed(1);
      const hTxt = units === 'inch' ? (hMM / 25.4).toFixed(2) : hMM.toFixed(1);
      // Horizontal dimension.
      parts.push(`<g stroke="#c0392b" stroke-width="0.25" fill="#c0392b" font-family="Arial" font-size="3.2">`);
      parts.push(`<line x1="${mapX(b.minX).toFixed(2)}" y1="${dimY.toFixed(2)}" x2="${mapX(b.maxX).toFixed(2)}" y2="${dimY.toFixed(2)}"/>`);
      parts.push(`<line x1="${mapX(b.minX).toFixed(2)}" y1="${(dimY - 1.5).toFixed(2)}" x2="${mapX(b.minX).toFixed(2)}" y2="${(dimY + 1.5).toFixed(2)}"/>`);
      parts.push(`<line x1="${mapX(b.maxX).toFixed(2)}" y1="${(dimY - 1.5).toFixed(2)}" x2="${mapX(b.maxX).toFixed(2)}" y2="${(dimY + 1.5).toFixed(2)}"/>`);
      parts.push(`<text x="${((mapX(b.minX) + mapX(b.maxX)) / 2).toFixed(2)}" y="${(dimY + 3.5).toFixed(2)}" text-anchor="middle">${wTxt}${unitLabel}</text>`);
      // Vertical dimension.
      const dimX = ox - dimOffset;
      parts.push(`<line x1="${dimX.toFixed(2)}" y1="${mapY(b.maxY).toFixed(2)}" x2="${dimX.toFixed(2)}" y2="${mapY(b.minY).toFixed(2)}"/>`);
      parts.push(`<text x="${(dimX - 1).toFixed(2)}" y="${((mapY(b.minY) + mapY(b.maxY)) / 2).toFixed(2)}" text-anchor="middle" transform="rotate(-90 ${(dimX - 1).toFixed(2)} ${((mapY(b.minY) + mapY(b.maxY)) / 2).toFixed(2)})">${hTxt}${unitLabel}</text>`);
      parts.push(`</g>`);
    }
  });

  // Projection-method symbol (truncated-cone glyph).
  const methodLabel = method === 'first' ? '1st ANGLE' : '3rd ANGLE';

  // Title block (bottom-right).
  const tbX = W - margin - tbW;
  const tbY = H - margin - tbH;
  const row = tbH / 4;
  const scaleText = scaleMode === 'auto' ? `~1:${(1 / scaleFactor).toFixed(1)}` : scaleMode;
  parts.push(`<g font-family="Arial" fill="#111">`);
  parts.push(`<rect x="${tbX}" y="${tbY}" width="${tbW}" height="${tbH}" fill="#fff" stroke="#111" stroke-width="0.5"/>`);
  parts.push(`<line x1="${tbX}" y1="${tbY + row}" x2="${tbX + tbW}" y2="${tbY + row}" stroke="#111" stroke-width="0.3"/>`);
  parts.push(`<line x1="${tbX}" y1="${tbY + row * 3}" x2="${tbX + tbW}" y2="${tbY + row * 3}" stroke="#111" stroke-width="0.3"/>`);
  parts.push(`<line x1="${tbX + tbW * 0.6}" y1="${tbY + row}" x2="${tbX + tbW * 0.6}" y2="${tbY + tbH}" stroke="#111" stroke-width="0.3"/>`);
  parts.push(`<text x="${tbX + 3}" y="${tbY + row - 2}" font-size="5" font-weight="bold">${esc(title.title || 'Untitled Part')}</text>`);
  parts.push(`<text x="${tbX + 3}" y="${tbY + row * 2 - 1.5}" font-size="3">DWG NO: ${esc(title.number || '—')}</text>`);
  parts.push(`<text x="${tbX + 3}" y="${tbY + row * 3 - 1.5}" font-size="3">BY: ${esc(title.author || '—')}</text>`);
  parts.push(`<text x="${tbX + tbW * 0.6 + 2}" y="${tbY + row * 2 - 1.5}" font-size="3">SCALE ${esc(scaleText)}</text>`);
  parts.push(`<text x="${tbX + tbW * 0.6 + 2}" y="${tbY + row * 3 - 1.5}" font-size="3">${esc(sheet)} · ${esc(units)}</text>`);
  parts.push(`<text x="${tbX + 3}" y="${tbY + row * 4 - 1.5}" font-size="3">REV ${esc(title.rev || 'A')} · ${esc(title.date || '')}</text>`);
  parts.push(`<text x="${tbX + tbW * 0.6 + 2}" y="${tbY + row * 4 - 1.5}" font-size="3">${methodLabel}</text>`);
  parts.push(`<text x="${tbX + tbW - 3}" y="${tbY + row - 2}" font-size="4" font-weight="bold" text-anchor="end" fill="#2f6bff">EVA CAD</text>`);
  parts.push(`</g>`);

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="100%" style="background:#fff">${parts.join('')}</svg>`;
}

// ------------------------------------------------------------------
// Component
// ------------------------------------------------------------------
export default function CADStudio() {
  const [step, setStep] = useState(1);
  const [fileName, setFileName] = useState('');
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [stats, setStats] = useState(null);
  const [wireframe, setWireframe] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [svg, setSvg] = useState('');

  const geometryRef = useRef(null); // centered BufferGeometry (mm)
  const edgeRef = useRef(null);     // EdgesGeometry
  const mountRef = useRef(null);
  const threeRef = useRef(null);    // { renderer, scene, camera, controls, mesh, grid, raf }

  const [setup, setSetup] = useState({
    sheet: 'A3', orientation: 'landscape', units: 'mm', method: 'third', scale: 'auto',
    views: { Front: true, Top: true, Right: true, Iso: true }, dims: true,
    title: 'Untitled Part', number: 'EVA-001', author: 'EVA', rev: 'A',
    date: new Date().toISOString().slice(0, 10),
  });

  // --- load geometry into state and prep viewer ---
  const ingestGeometry = useCallback((rawGeom, name) => {
    try {
      let geom = rawGeom.index ? rawGeom.toNonIndexed() : rawGeom;
      geom.computeVertexNormals();
      geom.computeBoundingBox();
      const center = new THREE.Vector3();
      geom.boundingBox.getCenter(center);
      geom.translate(-center.x, -center.y, -center.z);
      geometryRef.current = geom;
      edgeRef.current = new THREE.EdgesGeometry(geom, 20);
      setStats(computeStats(geom));
      setFileName(name);
      setError('');
      setSvg('');
      setStep(2);
    } catch (e) {
      setError('Could not parse geometry: ' + (e.message || e));
    }
  }, []);

  const handleFile = useCallback((file) => {
    setError('');
    if (!file) return;
    if (file.size > MAX_BYTES) { setError('File is larger than 40 MB.'); return; }
    const ext = file.name.split('.').pop().toLowerCase();
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        if (ext === 'stl') {
          const geom = new STLLoader().parse(ev.target.result);
          ingestGeometry(geom, file.name);
        } else if (ext === 'obj') {
          const obj = new OBJLoader().parse(ev.target.result);
          const geoms = [];
          obj.traverse((c) => { if (c.isMesh && c.geometry) geoms.push(c.geometry.toNonIndexed()); });
          if (!geoms.length) { setError('No mesh found in OBJ.'); return; }
          const merged = mergeGeometries(geoms);
          ingestGeometry(merged, file.name);
        } else {
          setError('Unsupported format. Upload .stl or .obj.');
        }
      } catch (e) {
        setError('Failed to read file: ' + (e.message || e));
      }
    };
    if (ext === 'stl') reader.readAsArrayBuffer(file);
    else reader.readAsText(file);
  }, [ingestGeometry]);

  const loadSample = useCallback(() => {
    ingestGeometry(buildSampleImpeller(), 'sample-impeller.stl');
  }, [ingestGeometry]);

  // --- three.js viewer for step 2 ---
  useEffect(() => {
    if (step !== 2 || !mountRef.current || !geometryRef.current) return undefined;
    const mount = mountRef.current;
    const width = mount.clientWidth || 600;
    const height = mount.clientHeight || 420;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0d0f14);
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 5000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const geom = geometryRef.current;
    geom.computeBoundingSphere();
    const radius = geom.boundingSphere.radius || 50;

    const material = new THREE.MeshStandardMaterial({ color: 0x9fb4d8, metalness: 0.25, roughness: 0.55, wireframe });
    const mesh = new THREE.Mesh(geom, material);
    scene.add(mesh);
    const edgeLines = new THREE.LineSegments(edgeRef.current, new THREE.LineBasicMaterial({ color: 0x1b2740 }));
    mesh.add(edgeLines);

    const grid = new THREE.GridHelper(radius * 6, 24, 0x2f6bff, 0x1b2130);
    grid.position.y = -radius;
    grid.visible = showGrid;
    scene.add(grid);

    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 0.9); key.position.set(1, 2, 1); scene.add(key);
    const fill = new THREE.DirectionalLight(0x88aaff, 0.4); fill.position.set(-1, -1, -1); scene.add(fill);

    camera.position.set(radius * 2, radius * 1.6, radius * 2.4);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0, 0);

    let raf;
    const animate = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(animate); };
    animate();

    const onResize = () => {
      const w = mount.clientWidth, h = mount.clientHeight;
      camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h);
    };
    window.addEventListener('resize', onResize);

    threeRef.current = { renderer, mesh, grid, material };

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      material.dispose();
      threeRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // Reflect wireframe / grid toggles live.
  useEffect(() => { if (threeRef.current) threeRef.current.material.wireframe = wireframe; }, [wireframe]);
  useEffect(() => { if (threeRef.current) threeRef.current.grid.visible = showGrid; }, [showGrid]);

  const generate = useCallback(() => {
    if (!edgeRef.current) { setError('No geometry loaded.'); return; }
    const out = buildDrawingSVG({
      edgeGeom: edgeRef.current,
      views: setup.views,
      method: setup.method,
      sheet: setup.sheet,
      orientation: setup.orientation,
      units: setup.units,
      scaleMode: setup.scale,
      dims: setup.dims,
      title: { title: setup.title, number: setup.number, author: setup.author, rev: setup.rev, date: setup.date },
    });
    setSvg(out);
    setStep(4);
  }, [setup]);

  const downloadSVG = useCallback(() => {
    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${setup.number || 'drawing'}.svg`; a.click();
    URL.revokeObjectURL(url);
  }, [svg, setup.number]);

  const downloadPNG = useCallback(() => {
    const sheetDef = SHEETS[setup.sheet] || SHEETS.A4;
    let W = sheetDef.w, H = sheetDef.h;
    if (setup.orientation === 'portrait') { const t = W; W = H; H = t; }
    const scale = 4;
    const img = new Image();
    const svgBlob = new Blob([svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(svgBlob);
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = W * scale; canvas.height = H * scale;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        const purl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = purl; a.download = `${setup.number || 'drawing'}.png`; a.click();
        URL.revokeObjectURL(purl);
      });
    };
    img.src = url;
  }, [svg, setup.sheet, setup.orientation, setup.number]);

  const startOver = useCallback(() => {
    geometryRef.current = null; edgeRef.current = null;
    setStats(null); setSvg(''); setFileName(''); setError(''); setStep(1);
  }, []);

  const fmt = (n) => (n == null ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: 2 }));

  return (
    <div style={S.page}>
      <header style={S.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={S.logoMark}>◨</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 16, color: C.text }}>EVA CAD Studio</div>
            <div style={{ fontSize: 12, color: C.muted }}>AI 3D → 2D engineering drawing</div>
          </div>
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>{fileName || 'No model loaded'}</div>
      </header>

      <div style={S.body}>
        <nav style={S.steps}>
          {STEPS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => { if (s.id < step || (s.id <= 2 && geometryRef.current)) setStep(s.id); }}
              style={{ ...S.stepItem, ...(step === s.id ? S.stepActive : {}), cursor: s.id <= step ? 'pointer' : 'default' }}
            >
              <span style={{ ...S.stepDot, ...(step >= s.id ? { background: C.accent, borderColor: C.accent } : {}) }}>{s.id}</span>
              {s.label}
            </button>
          ))}
        </nav>

        <main style={S.main}>
          {error && <div style={S.error}>{error}</div>}

          {step === 1 && (
            <section style={S.card}>
              <h2 style={S.h2}>Choose a model source</h2>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
                style={{ ...S.drop, ...(dragOver ? { borderColor: C.accent, background: C.accentSoft } : {}) }}
              >
                <div style={{ fontSize: 34, opacity: 0.7 }}>⬆</div>
                <div style={{ color: C.text, fontWeight: 600 }}>Drag &amp; drop a 3D model here</div>
                <div style={{ color: C.muted, fontSize: 13 }}>Accepted: .stl, .obj · max 40 MB</div>
                <label style={S.btnPrimary}>
                  Browse files
                  <input type="file" accept=".stl,.obj" style={{ display: 'none' }}
                    onChange={(e) => handleFile(e.target.files[0])} />
                </label>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '18px 0' }}>
                <div style={{ flex: 1, height: 1, background: C.border }} />
                <span style={{ color: C.muted, fontSize: 12 }}>or</span>
                <div style={{ flex: 1, height: 1, background: C.border }} />
              </div>
              <button type="button" onClick={loadSample} style={S.btnGhost}>Load sample model (impeller)</button>
            </section>
          )}

          {step === 2 && (
            <section style={{ ...S.card, display: 'grid', gridTemplateColumns: '1fr 260px', gap: 16, alignItems: 'stretch' }}>
              <div>
                <h2 style={S.h2}>Review imported geometry</h2>
                <div ref={mountRef} style={S.viewport} />
                <div style={{ display: 'flex', gap: 16, marginTop: 10 }}>
                  <label style={S.check}><input type="checkbox" checked={wireframe} onChange={(e) => setWireframe(e.target.checked)} /> Wireframe</label>
                  <label style={S.check}><input type="checkbox" checked={showGrid} onChange={(e) => setShowGrid(e.target.checked)} /> Grid</label>
                </div>
              </div>
              <aside style={S.sidePanel}>
                <div style={S.panelTitle}>Properties</div>
                {stats && (
                  <div style={{ display: 'grid', gap: 10 }}>
                    <Stat label="Triangles" value={fmt(stats.triCount)} />
                    <Stat label="Vertices" value={fmt(stats.vertexCount)} />
                    <Stat label="Width (X)" value={`${fmt(stats.size.x)} mm`} />
                    <Stat label="Height (Y)" value={`${fmt(stats.size.y)} mm`} />
                    <Stat label="Depth (Z)" value={`${fmt(stats.size.z)} mm`} />
                    <Stat label="Volume" value={`${fmt(stats.volume / 1000)} cm³`} />
                  </div>
                )}
                <button type="button" onClick={() => setStep(3)} style={{ ...S.btnPrimary, marginTop: 16, width: '100%', justifyContent: 'center' }}>Continue →</button>
              </aside>
            </section>
          )}

          {step === 3 && (
            <section style={S.card}>
              <h2 style={S.h2}>Set up your engineering drawing</h2>
              <div style={S.formGrid}>
                <Field label="Sheet size">
                  <select value={setup.sheet} onChange={(e) => setSetup({ ...setup, sheet: e.target.value })} style={S.input}>
                    <option>A4</option><option>A3</option><option>A2</option>
                  </select>
                </Field>
                <Field label="Orientation">
                  <select value={setup.orientation} onChange={(e) => setSetup({ ...setup, orientation: e.target.value })} style={S.input}>
                    <option value="landscape">Landscape</option><option value="portrait">Portrait</option>
                  </select>
                </Field>
                <Field label="Units">
                  <select value={setup.units} onChange={(e) => setSetup({ ...setup, units: e.target.value })} style={S.input}>
                    <option value="mm">mm</option><option value="inch">inch</option>
                  </select>
                </Field>
                <Field label="Projection method">
                  <select value={setup.method} onChange={(e) => setSetup({ ...setup, method: e.target.value })} style={S.input}>
                    <option value="third">Third-angle</option><option value="first">First-angle</option>
                  </select>
                </Field>
                <Field label="Scale">
                  <select value={setup.scale} onChange={(e) => setSetup({ ...setup, scale: e.target.value })} style={S.input}>
                    <option value="auto">Auto (fit)</option><option value="1:1">1:1</option><option value="1:2">1:2</option><option value="2:1">2:1</option>
                  </select>
                </Field>
                <Field label="Views">
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                    {['Front', 'Top', 'Right', 'Iso'].map((v) => (
                      <label key={v} style={S.check}>
                        <input type="checkbox" checked={setup.views[v]} onChange={(e) => setSetup({ ...setup, views: { ...setup.views, [v]: e.target.checked } })} /> {v}
                      </label>
                    ))}
                  </div>
                </Field>
                <Field label="Annotations">
                  <label style={S.check}><input type="checkbox" checked={setup.dims} onChange={(e) => setSetup({ ...setup, dims: e.target.checked })} /> Overall dimensions</label>
                </Field>
              </div>

              <div style={S.panelTitle}>Title block</div>
              <div style={S.formGrid}>
                <Field label="Drawing title"><input style={S.input} value={setup.title} onChange={(e) => setSetup({ ...setup, title: e.target.value })} /></Field>
                <Field label="Drawing number"><input style={S.input} value={setup.number} onChange={(e) => setSetup({ ...setup, number: e.target.value })} /></Field>
                <Field label="Author"><input style={S.input} value={setup.author} onChange={(e) => setSetup({ ...setup, author: e.target.value })} /></Field>
                <Field label="Revision"><input style={S.input} value={setup.rev} onChange={(e) => setSetup({ ...setup, rev: e.target.value })} /></Field>
                <Field label="Date"><input style={S.input} type="date" value={setup.date} onChange={(e) => setSetup({ ...setup, date: e.target.value })} /></Field>
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
                <button type="button" onClick={() => setStep(2)} style={S.btnGhost}>← Back</button>
                <button type="button" onClick={generate} style={S.btnPrimary}>Generate drawing</button>
              </div>
            </section>
          )}

          {step === 4 && (
            <section style={S.card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                <h2 style={{ ...S.h2, margin: 0 }}>Engineering drawing</h2>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="button" onClick={downloadSVG} style={S.btnGhost}>Download SVG</button>
                  <button type="button" onClick={downloadPNG} style={S.btnGhost}>Download PNG</button>
                  <button type="button" onClick={() => setStep(3)} style={S.btnGhost}>Edit setup</button>
                  <button type="button" onClick={startOver} style={S.btnPrimary}>Start over</button>
                </div>
              </div>
              <div style={S.sheetWrap} dangerouslySetInnerHTML={{ __html: svg }} />
              <p style={{ color: C.muted, fontSize: 12, marginTop: 10 }}>
                Note: feature edges are projected without hidden-line removal, so occluded edges are visible (wireframe-style projection).
              </p>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
      <span style={{ color: C.muted }}>{label}</span>
      <span style={{ color: C.text, fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'grid', gap: 6 }}>
      <span style={{ color: C.muted, fontSize: 12 }}>{label}</span>
      {children}
    </label>
  );
}

const S = {
  page: { minHeight: '100%', background: C.bg, color: C.text, display: 'flex', flexDirection: 'column' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 22px', borderBottom: `1px solid ${C.border}` },
  logoMark: { width: 34, height: 34, borderRadius: 8, background: C.accentSoft, color: C.accent, display: 'grid', placeItems: 'center', fontSize: 18, border: `1px solid ${C.accent}` },
  body: { display: 'grid', gridTemplateColumns: '210px 1fr', gap: 0, flex: 1, minHeight: 0 },
  steps: { display: 'flex', flexDirection: 'column', gap: 4, padding: 16, borderRight: `1px solid ${C.border}` },
  stepItem: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 8, border: '1px solid transparent', background: 'transparent', color: C.muted, fontSize: 14, textAlign: 'left' },
  stepActive: { background: C.panel, color: C.text, borderColor: C.border },
  stepDot: { width: 22, height: 22, borderRadius: 999, border: `1px solid ${C.border}`, display: 'grid', placeItems: 'center', fontSize: 12, color: '#fff' },
  main: { padding: 24, overflow: 'auto' },
  card: { background: C.panel, border: `1px solid ${C.border}`, borderRadius: 14, padding: 22, maxWidth: 980, margin: '0 auto' },
  h2: { fontSize: 18, margin: '0 0 16px', color: C.text },
  drop: { border: `1.5px dashed ${C.border}`, borderRadius: 12, padding: '40px 20px', display: 'grid', gap: 10, justifyItems: 'center', textAlign: 'center', transition: 'all .15s' },
  btnPrimary: { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 9, border: `1px solid ${C.accent}`, background: C.accent, color: '#fff', fontWeight: 700, cursor: 'pointer' },
  btnGhost: { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderRadius: 9, border: `1px solid ${C.border}`, background: 'transparent', color: C.text, fontWeight: 600, cursor: 'pointer' },
  viewport: { width: '100%', height: 420, borderRadius: 10, overflow: 'hidden', border: `1px solid ${C.border}`, background: '#0d0f14' },
  sidePanel: { background: C.panel2, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column' },
  panelTitle: { fontSize: 13, fontWeight: 700, color: C.text, margin: '18px 0 10px', textTransform: 'uppercase', letterSpacing: 0.5 },
  formGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14 },
  input: { padding: '9px 11px', borderRadius: 8, border: `1px solid ${C.border}`, background: C.panel2, color: C.text, fontSize: 14, width: '100%' },
  check: { display: 'flex', alignItems: 'center', gap: 6, color: C.text, fontSize: 13 },
  error: { background: 'rgba(220,60,60,.14)', border: '1px solid rgba(220,60,60,.4)', color: '#fca5a5', padding: '10px 14px', borderRadius: 8, marginBottom: 16, maxWidth: 980, marginLeft: 'auto', marginRight: 'auto' },
  sheetWrap: { marginTop: 16, background: '#fff', borderRadius: 8, padding: 12, boxShadow: '0 4px 24px rgba(0,0,0,.4)' },
};
