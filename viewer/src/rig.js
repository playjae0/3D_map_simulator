// 줌 ↔ 카메라 높이·앙각 관계. 거리 d = 높이 / sin(앙각)
import { CONFIG } from './config.js';

const C = CONFIG.camera;
const rad = (deg) => (deg * Math.PI) / 180;

export function elevationFor(h) {
  if (h <= C.hFlat) return C.elNear;
  const s = Math.min(1, Math.log(h / C.hFlat) / Math.log(C.hMax / C.hFlat));
  const ss = s * s * (3 - 2 * s);
  return C.elNear + (C.elFar - C.elNear) * ss;
}

export function distFor(h) {
  return h / Math.sin(rad(elevationFor(h)));
}

// distFor는 높이에 대해 단조 증가 → 이분 탐색으로 거꾸로 구한다
export function heightForDist(d) {
  let lo = C.hMin, hi = C.hMax;
  if (d <= distFor(lo)) return lo;
  if (d >= distFor(hi)) return hi;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    if (distFor(mid) < d) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

export const polarFor = (h) => Math.PI / 2 - rad(elevationFor(h));
