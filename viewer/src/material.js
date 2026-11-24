// 건물 재질: MeshLambertMaterial(면 음영·안개)에 외장 창 격자와 접지 그늘을 덧붙인다.
// 이미지 텍스처 없이 shader 계산만 쓴다. 정점 속성 aWall = (u, 벽 반길이(지붕 -1), 층 간격, 외장 그룹).
import * as THREE from 'three';

// manifest.facade_enum 순서: unknown, apartment, house, commercial, office, industrial, public
// 창 격자(m): [기둥 간격, 창 폭, 창 아래 높이(층 바닥에서), 창 높이]
const GROUPS = [
  { name: 'unknown',    grid: [3.2, 1.0, 1.0, 1.0], wall: 0xe4dfd5, win: 0x9ca2a6 },  // 중립: 대비 낮게
  { name: 'apartment',  grid: [3.0, 2.3, 0.9, 1.5], wall: 0xf0ede6, win: 0x5b6b78 },  // 넓은 창 띠 + 층 슬래브 선
  { name: 'house',      grid: [3.8, 1.2, 1.0, 1.2], wall: 0xe8d9c0, win: 0x56616b },  // 작은 창, 넓은 간격
  { name: 'commercial', grid: [3.2, 2.2, 0.9, 1.7], wall: 0xd8d5cf, win: 0x4c5964 },  // 1층은 상점 전면
  { name: 'office',     grid: [1.6, 1.4, 0.35, 2.9], wall: 0xc4ccd3, win: 0x3f566a }, // 촘촘한 커튼월
  { name: 'industrial', grid: [6.0, 3.6, 3.2, 1.0], wall: 0xd3d8dc, win: 0x6c7884 },  // 높은 띠창 + 판넬 이음
  { name: 'public',     grid: [3.6, 2.4, 0.9, 1.9], wall: 0xe2d0bb, win: 0x4b5965 },  // 규칙적인 큰 창
];
const PLAIN = 0xece7de;      // 외장 패턴을 끈 경우의 단색

export function createBuildingMaterial({ facade, ground }) {
  const mat = new THREE.MeshLambertMaterial({ color: facade ? 0xffffff : PLAIN });
  mat.defines = {};
  if (facade) mat.defines.USE_FACADE = '';
  if (ground) mat.defines.USE_GROUND = '';
  const uniforms = {
    uGrid: { value: GROUPS.map((g) => new THREE.Vector4(...g.grid)) },
    uWallCol: { value: GROUPS.map((g) => new THREE.Color(g.wall)) },
    uWinCol: { value: GROUPS.map((g) => new THREE.Color(g.win)) },
  };
  mat.customProgramCacheKey = () => `bldg-${facade ? 1 : 0}${ground ? 1 : 0}`;
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', /* glsl */`#include <common>
        #ifdef USE_FACADE
          attribute vec4 aWall;
          varying vec4 vWall;
        #endif
        varying float vH;
        varying float vRoof;`)
      .replace('#include <begin_vertex>', /* glsl */`#include <begin_vertex>
        #ifdef USE_FACADE
          vWall = aWall;
        #endif
        vH = position.y;
        vRoof = step(0.5, normal.y);`);

    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', /* glsl */`#include <common>
        varying float vH;
        varying float vRoof;
        #ifdef USE_FACADE
          varying vec4 vWall;
          uniform vec4 uGrid[7];
          uniform vec3 uWallCol[7];
          uniform vec3 uWinCol[7];

          // [lo, hi] 구간이면 1. w(화면 한 픽셀의 크기)만큼 경계를 부드럽게
          float band(float x, float lo, float hi, float w) {
            return smoothstep(lo - w, lo + w, x) - smoothstep(hi - w, hi + w, x);
          }
          float hash12(vec2 p) {
            vec3 p3 = fract(vec3(p.xyx) * 0.1031);
            p3 += dot(p3, p3.yzx + 33.33);
            return fract((p3.x + p3.y) * p3.z);
          }

          vec3 facadeColor() {
            int g = int(vWall.w + 0.5);
            vec3 wallC = uWallCol[g];
            vec3 winC = uWinCol[g];
            if (vRoof > 0.5) return mix(wallC, vec3(0.42), 0.35);

            vec4 p = uGrid[g];
            float colW = p.x, winW = p.y, sill = p.z, winH = p.w;
            float fh = max(vWall.z, 2.0);
            float fl = vH / fh;
            float fi = floor(fl);
            float y = (fl - fi) * fh;                       // 층 바닥에서 높이(m)
            if (g == 3 && fi < 0.5) {                        // 상업 1층: 상점 전면
              winW = colW - 0.3; sill = 0.25; winH = min(fh * 0.8, 3.2);
            }
            sill = min(sill, fh * 0.3);
            winH = max(min(winH, fh - sill - 0.25), 0.0);    // 층 안에 들어가도록

            float u = vWall.x;
            float halfLen = vWall.y;
            float cu = u / colW;
            float ci = floor(cu + 0.5);                      // 기둥 번호(벽 가운데가 0)
            float cx = (cu - ci) * colW;                     // 기둥 중심에서 거리(m)
            // 벽 끝에 걸리는 창은 그리지 않는다
            float inside = step(abs(ci) * colW + 0.5 * winW + 0.3, halfLen);

            float wu = max(fwidth(u), 1e-4);
            float wy = max(fwidth(vH), 1e-4);
            float mask = band(cx, -0.5 * winW, 0.5 * winW, wu) * band(y, sill, sill + winH, wy) * inside;
            float cover = (winW / colW) * (winH / fh) * 0.85;

            // 창마다 밝기 조금씩 다르게(벽 길이로 건물 간 차이)
            vec3 winV = winC * (0.85 + 0.3 * hash12(vec2(fi, ci) + vec2(halfLen * 3.1, 0.0)));

            // 멀어지면 격자 대신 평균색. 무늬의 가장 작은 치수가 화면에서 약 4픽셀 아래로 줄면
            // 흐리기 시작해 약 1.7픽셀에서 평균색만 남긴다(깜빡임 방지). 무늬마다 따로 판단한다
            float winFeature = min(min(winW, colW - winW), min(max(winH, 0.3), fh));
            float fadeWin = smoothstep(0.25, 0.6, max(wu, wy) / max(winFeature, 0.05));
            vec3 c = mix(mix(wallC, winV, mask), mix(wallC, winC, cover), fadeWin);
            if (g == 1) {                                    // 공동주택: 층 슬래브 선
              float slab = band(y, 0.0, 0.25, wy);
              float fs = smoothstep(0.25, 0.6, wy / 0.25);
              c *= 1.0 - 0.18 * mix(slab, 0.25 / fh, fs);
            } else if (g == 5) {                             // 공장·창고: 1m 간격 판넬 이음
              float seam = band(fract(u + 0.5) - 0.5, -0.04, 0.04, wu) * (1.0 - mask);
              float fs = smoothstep(0.25, 0.6, wu / 0.08);
              c *= 1.0 - 0.12 * mix(seam, 0.08, fs);
            }
            return c;
          }
        #endif`)
      .replace('#include <color_fragment>', /* glsl */`#include <color_fragment>
        #ifdef USE_FACADE
          diffuseColor.rgb = facadeColor();
        #endif
        #ifdef USE_GROUND
          // 접지 그늘: 벽 아래 약 3m를 살짝 어둡게(AO 계산 전 임시)
          diffuseColor.rgb *= mix(1.0, 0.68 + 0.32 * smoothstep(0.0, 3.0, vH), 1.0 - vRoof);
        #endif`);
  };
  return mat;
}

export const FACADE_GROUPS = GROUPS.map((g) => g.name);
