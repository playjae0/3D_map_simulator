// artifact(claude.ai 호스팅 웹페이지) 배포용 빌드: npm run build:artifact
//
// 제약: 한 번에 올릴 수 있는 파일 256개 이하, 쿼리 문자열 전달 없음, 외부 호스트 요청 차단.
// → 타일을 LOD별 묶음 파일 1개씩(tiles/<지역>/lod<n>.bin)으로 합치고 색인(index.json)에 offset·length를 적는다.
//   뷰어는 Range 요청으로 묶음에서 타일을 잘라 읽고, 서버가 Range를 지원하지 않으면 묶음을 한 번 받아 잘라 쓴다.
// 입력: ../data/processed/tiles/<지역>/ (scripts/tile.py 결과)
import { build } from 'vite';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REGION = process.env.REGION || '36';
const SRC = path.resolve(ROOT, '../data/processed/tiles', REGION);
const OUT = path.resolve(ROOT, 'dist-artifact');
const MAX_FILES = 256;

if (!fs.existsSync(path.join(SRC, 'manifest.json'))) {
  console.error(`타일이 없습니다: ${SRC}\n먼저 scripts/refine.py, scripts/tile.py를 실행하세요 (README 1번).`);
  process.exit(1);
}

// 1) 앱 빌드 (모드 artifact: 묶음 파일 읽기, 상대 경로)
await build({
  root: ROOT,
  mode: 'artifact',
  base: './',
  publicDir: false,
  logLevel: 'warn',
  build: { outDir: OUT, emptyOutDir: true, chunkSizeWarningLimit: 1000 },
});

// 2) 타일 묶기
const manifest = JSON.parse(fs.readFileSync(path.join(SRC, 'manifest.json'), 'utf8'));
const tileDir = path.join(OUT, 'tiles', REGION);
fs.mkdirSync(tileDir, { recursive: true });
const packs = [];
for (let lod = 0; lod < manifest.lods.length; lod++) {
  const file = `lod${lod}.bin`;
  const parts = [];
  let offset = 0;
  for (const t of manifest.tiles) {
    const e = t.lod[lod];
    if (!e) continue;
    const buf = fs.readFileSync(path.join(SRC, String(lod), `${t.x}_${t.y}.bin`));
    if (buf.length !== e.b) throw new Error(`크기 불일치 ${lod}/${t.x}_${t.y}`);
    e.o = offset;                                  // 색인: offset(o), length(b)
    parts.push(buf);
    offset += buf.length;
  }
  fs.writeFileSync(path.join(tileDir, file), Buffer.concat(parts));
  packs.push({ lod, file, bytes: offset, tiles: parts.length });
}
const index = { ...manifest, packs, packed_from: 'manifest.json' };
fs.writeFileSync(path.join(tileDir, 'index.json'), JSON.stringify(index));

// 3) 점검: 파일 수, 용량, 외부 URL 참조
const files = [];
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((f) => {
  const p = path.join(d, f.name);
  if (f.isDirectory()) walk(p); else files.push({ p: path.relative(OUT, p), bytes: fs.statSync(p).size });
});
walk(OUT);
const total = files.reduce((s, f) => s + f.bytes, 0);
const external = [];
for (const f of files.filter((x) => /\.(html|js|css)$/.test(x.p))) {
  const txt = fs.readFileSync(path.join(OUT, f.p), 'utf8');
  // 실행 중 불러오는 주소만 본다(라이브러리 주석·문자열의 URL은 제외하기 어려우므로 src/href/import/fetch 형태만)
  for (const m of txt.matchAll(/(?:src|href)=["'](https?:)?\/\/[^"']+|import\(\s*["']https?:\/\/[^"']+|fetch\(\s*["']https?:\/\/[^"']+/g)) {
    external.push(`${f.p}: ${m[0].slice(0, 80)}`);
  }
}
for (const f of files.sort((a, b) => a.p.localeCompare(b.p))) console.log(`${String(f.bytes).padStart(10)}  ${f.p}`);
console.log(`\n파일 ${files.length}개, 합계 ${(total / 1024 / 1024).toFixed(2)} MB (${total} bytes)`);
if (external.length) { console.error('외부 주소 참조:\n' + external.join('\n')); process.exit(1); }
if (files.length > MAX_FILES) { console.error(`파일 수가 ${MAX_FILES}개를 넘습니다`); process.exit(1); }
