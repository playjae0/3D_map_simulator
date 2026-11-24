// 뷰어 설정. 거리 단위는 m, 좌표는 EPSG:5186.
const q = new URLSearchParams(location.search);

// artifact 빌드(npm run build:artifact)는 타일을 LOD별 묶음 파일 + index.json으로 읽는다
const ARTIFACT = import.meta.env.MODE === 'artifact';

export const CONFIG = {
  region: q.get('region') || '36',
  tileMode: ARTIFACT ? 'pack' : 'files',
  tilesBase: ARTIFACT ? './tiles/' : import.meta.env.BASE_URL,   // 개발: vite publicDir = data/processed/tiles

  // 고정 각도 카메라: 앙각(수평선 아래로 내려다보는 각)과 거리 고정, 회전·이동만 허용 (앙각 22°는 임시)
  camera: { fov: 50, elevationDeg: 22, distance: 850, near: 5, far: 8000 },
  // 이동 가능 영역: 시작 위치 기준 ±halfSize (데이터 범위 안으로 다시 자른다)
  regionHalfSize: Number(q.get('area') || 3000),

  // 카메라 주시점(지면)에서 타일 경계까지의 최단 거리로 LOD를 고른다
  // [LOD0 원래 외곽선, LOD1 박스, LOD2 큰 건물 박스], 이보다 멀면 불러오지 않는다
  lodRadii: [500, 1100, 2000],
  hysteresis: 100,                              // 단계를 낮출 때(먼 쪽으로) 더하는 여유
  maxConcurrent: 4,
  workers: 2,
  cacheTiles: 400,                              // 메모리에 남겨 둘 타일 메시 수

  fog: { near: 900, far: 2300 },                // 카메라 깊이 기준
};

// 화면 설정: URL 매개변수 > 저장값(localStorage) > 기본값.
// artifact 호스팅은 쿼리 문자열을 넘기지 않으므로 화면 안 패널로도 바꿀 수 있다.
const STORE_KEY = '3d-map-simulator.settings';
function loadStored() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
}
const stored = loadStored();
const flag = (k, def) => (q.has(k) ? q.get(k) !== '0' : (typeof stored[k] === 'boolean' ? stored[k] : def));

export const SETTINGS = {
  dpr: q.has('dpr') ? Number(q.get('dpr')) : (Number(stored.dpr) || 2),   // 픽셀 비율 상한
  aa: flag('aa', true),                                                   // 안티에일리어싱
  facade: flag('facade', true),                                           // 외장 창 격자
  ground: flag('ground', true),                                           // 접지 그늘
};

export function saveSettings() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(SETTINGS)); } catch { /* 저장 불가 환경이면 이번 화면에만 적용 */ }
}
