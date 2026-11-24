// 타일 바이너리(BLDT v1, docs/tiles.md)를 받아 LOD1 extrude 메시 버퍼를 만든다.
// 메인 스레드를 막지 않도록 fetch·디코딩·삼각분할을 모두 여기서 한다.
import earcut from 'earcut';

const HEADER = 32;

function decode(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'BLDT') throw new Error('BLDT 형식이 아닙니다');
  const version = dv.getUint8(4);
  if (version !== 1) throw new Error(`지원하지 않는 버전 ${version}`);
  const n = dv.getUint32(8, true);
  const nRings = dv.getUint32(12, true);
  const nVerts = dv.getUint32(16, true);
  let o = HEADER;
  const prismRing = new Uint32Array(buf, o, n + 1); o += 4 * (n + 1);
  const ringVert = new Uint32Array(buf, o, nRings + 1); o += 4 * (nRings + 1);
  const verts = new Float32Array(buf, o, nVerts * 2); o += 8 * nVerts;
  const height = new Float32Array(buf, o, n); o += 4 * n;
  const facade = new Uint8Array(buf, o, n);
  return { n, nRings, nVerts, prismRing, ringVert, verts, height, facade };
}

// EPSG:5186 (x 동, y 북, z 높이) → three.js (X = x, Y = 높이, Z = -y)
function build(t, offX, offY) {
  const { n, prismRing, ringVert, verts, height } = t;
  // 정점 수: 벽은 변마다 4개(면 음영용 독립 법선), 지붕은 꼭짓점마다 1개
  let wallEdges = 0;
  for (let r = 0; r < t.nRings; r++) wallEdges += ringVert[r + 1] - ringVert[r];
  const nV = wallEdges * 4 + t.nVerts;
  let nTri = wallEdges * 2;
  for (let i = 0; i < n; i++) {
    const e = ringVert[prismRing[i + 1]] - ringVert[prismRing[i]];
    const holes = prismRing[i + 1] - prismRing[i] - 1;
    nTri += e - 2 + 2 * holes;
  }
  const pos = new Float32Array(nV * 3);
  const nor = new Float32Array(nV * 3);
  const idx = nV > 65535 ? new Uint32Array(nTri * 3) : new Uint16Array(nTri * 3);
  let v = 0, k = 0;

  for (let i = 0; i < n; i++) {
    const h = height[i];
    const r0 = prismRing[i], r1 = prismRing[i + 1];
    // 벽: 링은 재료가 진행 방향 왼쪽(외곽 반시계, 구멍 시계)이므로 바깥 법선 = (dy, -dx)
    for (let r = r0; r < r1; r++) {
      const s = ringVert[r], e = ringVert[r + 1];
      for (let j = s; j < e; j++) {
        const jn = j + 1 < e ? j + 1 : s;
        const ax = verts[2 * j] + offX, ay = verts[2 * j + 1] + offY;
        const bx = verts[2 * jn] + offX, by = verts[2 * jn + 1] + offY;
        let nx = by - ay, ny = -(bx - ax);
        const len = Math.hypot(nx, ny) || 1;
        nx /= len; ny /= len;
        const base = v;
        const quad = [ax, ay, 0, bx, by, 0, bx, by, h, ax, ay, h];
        for (let q = 0; q < 4; q++) {
          pos[3 * v] = quad[3 * q]; pos[3 * v + 1] = quad[3 * q + 2]; pos[3 * v + 2] = -quad[3 * q + 1];
          nor[3 * v] = nx; nor[3 * v + 1] = 0; nor[3 * v + 2] = -ny;
          v++;
        }
        // 바깥에서 볼 때 반시계: a0 b0 b1 / a0 b1 a1
        idx[k++] = base; idx[k++] = base + 1; idx[k++] = base + 2;
        idx[k++] = base; idx[k++] = base + 2; idx[k++] = base + 3;
      }
    }
    // 지붕: earcut. 결과 삼각형은 위(+Y)에서 볼 때 반시계가 되도록 방향을 맞춘다
    const vs = ringVert[r0], ve = ringVert[r1];
    const flat = verts.subarray(2 * vs, 2 * ve);
    const holes = [];
    for (let r = r0 + 1; r < r1; r++) holes.push(ringVert[r] - vs);
    const tri = earcut(flat, holes.length ? holes : undefined, 2);
    const base = v;
    for (let j = vs; j < ve; j++) {
      pos[3 * v] = verts[2 * j] + offX; pos[3 * v + 1] = h; pos[3 * v + 2] = -(verts[2 * j + 1] + offY);
      nor[3 * v] = 0; nor[3 * v + 1] = 1; nor[3 * v + 2] = 0;
      v++;
    }
    for (let m = 0; m < tri.length; m += 3) {
      const a = tri[m], b = tri[m + 1], c = tri[m + 2];
      const cross = (flat[2 * b] - flat[2 * a]) * (flat[2 * c + 1] - flat[2 * a + 1]) - (flat[2 * b + 1] - flat[2 * a + 1]) * (flat[2 * c] - flat[2 * a]);
      if (cross >= 0) { idx[k++] = base + a; idx[k++] = base + b; idx[k++] = base + c; }
      else { idx[k++] = base + a; idx[k++] = base + c; idx[k++] = base + b; }
    }
  }
  // earcut이 퇴화 다각형에서 삼각형을 덜 내면 k < idx.length
  return { pos, nor, idx: idx.subarray(0, k), triangles: k / 3 };
}

self.onmessage = async (ev) => {
  const { id, url, offX, offY } = ev.data;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    const buf = await res.arrayBuffer();
    const t = decode(buf);
    const g = build(t, offX, offY);
    const idx = g.idx.slice();   // subarray → 독립 버퍼로 복사해 transfer
    self.postMessage({ id, ok: true, pos: g.pos, nor: g.nor, idx, triangles: g.triangles, bytes: buf.byteLength, prisms: t.n },
      [g.pos.buffer, g.nor.buffer, idx.buffer]);
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err) });
  }
};
