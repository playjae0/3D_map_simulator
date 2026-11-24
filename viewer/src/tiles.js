// 카메라 주시점 기준으로 타일과 LOD 단계를 골라 불러오고, 멀어진 타일은 내린다.
import * as THREE from 'three';
import { CONFIG } from './config.js';

// 타일 바이트 받기. files: 타일마다 파일 1개(manifest.json)
// pack: LOD별 묶음 파일 + index.json의 offset·length로 잘라 읽기(artifact 배포용, 파일 수 제한).
//       artifact가 임의 바이너리를 제공하지 않아 묶음은 타일별 base64 텍스트를 이어 붙인 것이다
export class TileSource {
  constructor(mode, base, region) {
    this.mode = mode;
    this.dir = `${base}${region}/`;
    this.packs = {};
    this.netBytes = 0;                           // 실제로 받은 바이트(묶음 파일을 통째로 받은 경우 포함)
  }

  async loadIndex() {
    const name = this.mode === 'pack' ? 'index.json' : 'manifest.json';
    const res = await fetch(`${this.dir}${name}`);
    if (!res.ok) throw new Error(`${name}를 읽지 못했습니다 (${res.status}). scripts/tile.py로 타일을 먼저 만드세요.`);
    this.index = await res.json();
    return this.index;
  }

  async get(lod, t) {
    if (this.mode === 'files') {
      const res = await fetch(`${this.dir}${lod}/${t.x}_${t.y}.bin`);
      if (!res.ok) throw new Error(`${res.status} ${lod}/${t.x}_${t.y}`);
      const buf = await res.arrayBuffer();
      this.netBytes += buf.byteLength;
      return buf;
    }
    const e = t.lod[lod];
    const pack = this.index.packs[lod];
    const st = (this.packs[lod] ??= { range: null, probe: null, whole: null });
    // 첫 요청으로 서버가 Range(부분 요청)를 지원하는지 본다. 지원하지 않으면 묶음 파일을 한 번만 받아 잘라 쓴다
    if (st.range === null) {
      if (!st.probe) {
        st.probe = this._fetch(pack, e).then((r) => {
          st.range = r.partial;
          if (!r.partial) st.whole = r.buf;
          return r;
        }).catch((err) => { st.probe = null; throw err; });
        const r = await st.probe;
        if (r.partial) return r.buf;
      } else {
        await st.probe;
      }
    }
    if (st.range) {
      const r = await this._fetch(pack, e);
      if (r.partial) return r.buf;
      st.range = false; st.whole = r.buf;
    }
    return b64ToBuffer(st.whole.substring(e.o, e.o + e.l));
  }

  async _fetch(pack, e) {
    const url = `${this.dir}${pack.file}`;
    const res = await fetch(url, { headers: { Range: `bytes=${e.o}-${e.o + e.l - 1}` } });
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    const txt = await res.text();
    this.netBytes += txt.length;
    if (res.status === 206 && txt.length === e.l) return { partial: true, buf: b64ToBuffer(txt) };
    if (txt.length !== pack.bytes) throw new Error(`묶음 파일 크기가 색인과 다릅니다: ${url}`);
    return { partial: false, buf: txt };   // 전체 텍스트(잘라 쓰기는 get에서)
  }
}

function b64ToBuffer(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

export class TileManager {
  constructor(scene, manifest, material, origin, source) {
    this.scene = scene;
    this.manifest = manifest;
    this.material = material;
    this.origin = origin;                       // 장면 원점(EPSG:5186)
    this.source = source;
    this.size = manifest.tile_size;
    this.tiles = manifest.tiles.map((t) => ({
      ...t, xmin: t.x * this.size, ymin: t.y * this.size, xmax: (t.x + 1) * this.size, ymax: (t.y + 1) * this.size,
      want: -1, shown: -1, mesh: null,
    }));
    this.cache = new Map();                      // key → {geometry, triangles, bytes, used}
    this.pending = new Map();                    // key → true
    this.queue = [];
    this.workers = Array.from({ length: CONFIG.workers }, () =>
      new Worker(new URL('./tileWorker.js', import.meta.url), { type: 'module' }));
    this.workers.forEach((w) => { w.onmessage = (e) => this._onBuilt(e.data); });
    this.nextWorker = 0;
    this.reqId = 0;
    this.callbacks = new Map();
    this.loadedBytes = 0;
    this.errors = 0;
  }

  setMaterial(material) {
    this.material = material;
    for (const t of this.tiles) if (t.mesh) t.mesh.material = material;
  }

  _dist(t, x, y) {
    const dx = Math.max(t.xmin - x, 0, x - t.xmax);
    const dy = Math.max(t.ymin - y, 0, y - t.ymax);
    return Math.hypot(dx, dy);
  }

  _lodFor(t, d) {
    const R = CONFIG.lodRadii;
    let lod = -1;
    for (let i = 0; i < R.length; i++) {
      // 지금 보이는 단계보다 먼 단계로 바꿀 때만 여유를 준다(경계에서 깜빡임 방지)
      const r = t.shown >= 0 && i >= t.shown ? R[i] + CONFIG.hysteresis : R[i];
      if (d < r) { lod = i; break; }
    }
    // LOD2에 남는 건물이 없는 타일은 파일이 없다
    if (lod >= 0 && !t.lod[lod]) lod = -1;
    return lod;
  }

  // x, y: 주시점(EPSG:5186)
  update(x, y) {
    const need = [];
    for (const t of this.tiles) {
      const d = this._dist(t, x, y);
      t.want = this._lodFor(t, d);
      if (t.want !== t.shown) {
        if (t.want < 0) { this._hide(t); continue; }
        const key = `${t.want}/${t.x}_${t.y}`;
        if (this.cache.has(key)) this._show(t, key);
        else if (!this.pending.has(key)) need.push({ t, key, d, lod: t.want });
      }
    }
    // 가까운 타일, 상세한 단계부터
    need.sort((a, b) => a.d - b.d);
    this.queue = need;
    this._pump();
  }

  _pump() {
    while (this.pending.size < CONFIG.maxConcurrent && this.queue.length) {
      const { t, key, lod } = this.queue.shift();
      if (t.want !== lod) continue;
      this.pending.set(key, true);
      this.source.get(lod, t).then((buf) => {
        const id = ++this.reqId;
        this.callbacks.set(id, { t, key });
        const w = this.workers[this.nextWorker++ % this.workers.length];
        // 타일 원점을 장면 원점 기준으로 옮겨 float32 정밀도를 지킨다
        w.postMessage({ id, buf, offX: t.xmin - this.origin.x, offY: t.ymin - this.origin.y }, [buf]);
      }).catch((err) => {
        this.errors++;
        console.error(err);
        this.pending.delete(key);
        this._pump();
      });
    }
  }

  _onBuilt(msg) {
    const cb = this.callbacks.get(msg.id);
    this.callbacks.delete(msg.id);
    this.pending.delete(cb.key);
    if (!msg.ok) {
      this.errors++;
      console.error(msg.error);
    } else {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(msg.pos, 3));
      g.setAttribute('normal', new THREE.BufferAttribute(msg.nor, 3));
      g.setAttribute('aWall', new THREE.BufferAttribute(msg.wall, 4));
      g.setIndex(new THREE.BufferAttribute(msg.idx, 1));
      g.computeBoundingSphere();
      this.cache.set(cb.key, { geometry: g, triangles: msg.triangles, bytes: msg.bytes, used: performance.now() });
      this.loadedBytes += msg.bytes;
      const lod = Number(cb.key.split('/')[0]);
      if (cb.t.want === lod) this._show(cb.t, cb.key);
      this._evict();
    }
    this._pump();
  }

  _show(t, key) {
    const c = this.cache.get(key);
    c.used = performance.now();
    if (!t.mesh) {
      t.mesh = new THREE.Mesh(c.geometry, this.material);
      t.mesh.matrixAutoUpdate = false;
      this.scene.add(t.mesh);
    } else {
      t.mesh.geometry = c.geometry;              // 새 단계가 준비된 뒤에 교체해 빈 화면을 만들지 않는다
    }
    t.shown = Number(key.split('/')[0]);
    t.shownKey = key;
  }

  _hide(t) {
    if (t.mesh) { this.scene.remove(t.mesh); t.mesh = null; }
    t.shown = -1;
    t.shownKey = null;
  }

  _evict() {
    if (this.cache.size <= CONFIG.cacheTiles) return;
    const inUse = new Set(this.tiles.filter((t) => t.shownKey).map((t) => t.shownKey));
    const old = [...this.cache.entries()].filter(([k]) => !inUse.has(k)).sort((a, b) => a[1].used - b[1].used);
    for (const [k, c] of old.slice(0, this.cache.size - CONFIG.cacheTiles)) {
      c.geometry.dispose();
      this.cache.delete(k);
    }
  }

  stats() {
    const byLod = [0, 0, 0];
    let tri = 0;
    for (const t of this.tiles) if (t.shown >= 0) { byLod[t.shown]++; tri += this.cache.get(t.shownKey).triangles; }
    return { byLod, tri, pending: this.pending.size + this.queue.length, cached: this.cache.size, loadedBytes: this.loadedBytes, netBytes: this.source.netBytes, errors: this.errors };
  }
}
