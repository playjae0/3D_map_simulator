// 뷰어 설정. 거리 단위는 m, 좌표는 EPSG:5186.
const q = new URLSearchParams(location.search);

export const CONFIG = {
  region: q.get('region') || '36',
  tilesBase: import.meta.env.BASE_URL,          // vite publicDir = data/processed/tiles

  // 고정 각도 카메라: 앙각(수평선 아래로 내려다보는 각)과 거리 고정, 회전·이동만 허용
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
  pixelRatioMax: Number(q.get('dpr') || 2),
  antialias: q.get('aa') !== '0',
};
