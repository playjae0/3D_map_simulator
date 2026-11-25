// 뷰어 설정. 거리 단위는 m, 좌표는 EPSG:5186.
const q = new URLSearchParams(location.search);

// artifact 빌드(npm run build:artifact)는 타일을 LOD별 묶음 파일 + index.json으로 읽는다
const ARTIFACT = import.meta.env.MODE === 'artifact';

export const CONFIG = {
  // 지역(타일 폴더). URL ?region= > 빌드 시 VITE_REGION > 36(세종)
  region: q.get('region') || import.meta.env.VITE_REGION || '36',
  tileMode: ARTIFACT ? 'pack' : 'files',
  tilesBase: ARTIFACT ? './tiles/' : import.meta.env.BASE_URL,   // 개발: vite publicDir = data/processed/tiles

  // 카메라: 회전·이동·줌. 줌은 카메라 높이로 제한하고, 높이에 따라 앙각(내려다보는 각)을 바꾼다(모두 임시)
  //   높이 hFlat 이하: 앙각 elNear(22°, v0.2 화면과 같음, 하늘이 보임)
  //   hFlat~hMax: 로그 높이 기준으로 elFar(60°)까지 부드럽게 증가
  camera: { fov: 50, near: 5, far: 9000, hMin: 150, hMax: 1500, hStart: 318, hFlat: 400, elNear: 22, elFar: 60 },
  // 이동 가능 영역: 기본은 데이터 범위 전체. ?area=3000 이면 시작 위치 기준 ±3000m로 제한
  regionHalfSize: q.has('area') ? Number(q.get('area')) : null,

  // LOD: 카메라에서 타일(건물 높이까지의 상자)까지 거리로 고른다 → 줌에 따라 자동으로 바뀐다
  //   < lodDist[0] LOD0 원래 외곽선, < lodDist[1] LOD1 박스, < 안개 끝 LOD2 큰 건물 박스, 그 밖은 불러오지 않음
  //   시야(조금 넓힌 절두체)에 걸친 타일 + 주시점 주변 nearKeep 안 타일만 불러온다(회전 대비)
  lodDist: [1000, 2000],
  nearKeep: 900,
  hysteresis: 100,                              // 단계를 낮출 때(먼 쪽으로) 더하는 여유
  maxConcurrent: 4,
  workers: 2,
  cacheTiles: 400,                              // 메모리에 남겨 둘 타일 메시 수

  // 안개(카메라 깊이 기준): 끝 = max(farMin, farPerDist × 카메라-주시점 거리), 시작 = 끝 × nearRatio
  fog: { farMin: 2300, farPerDist: 2.6, nearRatio: 0.39 },
  labels: { minHeight: 600 },                   // 카메라 높이가 이 이상이면 법정동 라벨 표시
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
