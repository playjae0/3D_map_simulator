import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CONFIG, SETTINGS, saveSettings } from './config.js';
import { TileManager, TileSource } from './tiles.js';
import { createSky } from './sky.js';
import { createBuildingMaterial } from './material.js';
import { distFor, heightForDist, polarFor, elevationFor } from './rig.js';
import { Minimap } from './minimap.js';
import { AreaLabels } from './labels.js';

const HORIZON = 0xd9e2ea;   // 안개 = 지평선 색
const ZENITH = 0x6f9fd8;

const statsEl = document.getElementById('stats');

function makeRenderer() {
  const r = new THREE.WebGLRenderer({ antialias: SETTINGS.aa, powerPreference: 'high-performance' });
  r.setPixelRatio(Math.min(window.devicePixelRatio, SETTINGS.dpr));
  r.setSize(window.innerWidth, window.innerHeight);
  return r;
}

async function main() {
  const source = new TileSource(CONFIG.tileMode, CONFIG.tilesBase, CONFIG.region);
  const manifest = await source.loadIndex();

  // 장면 원점 = 시작 위치. three.js 좌표: X = 동, Y = 위, Z = -북
  const origin = { x: manifest.start.x, y: manifest.start.y };
  const [bx0, by0, bx1, by1] = manifest.bounds;
  const H = CONFIG.regionHalfSize;                 // null이면 데이터 범위 전체
  const area = H == null ? { xmin: bx0, xmax: bx1, ymin: by0, ymax: by1 } : {
    xmin: Math.max(origin.x - H, bx0), xmax: Math.min(origin.x + H, bx1),
    ymin: Math.max(origin.y - H, by0), ymax: Math.min(origin.y + H, by1),
  };

  let renderer = makeRenderer();
  document.body.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(HORIZON, 900, CONFIG.fog.farMin);

  const c = CONFIG.camera;
  const camera = new THREE.PerspectiveCamera(c.fov, window.innerWidth / window.innerHeight, c.near, c.far);
  {
    const d0 = distFor(c.hStart), el0 = (elevationFor(c.hStart) * Math.PI) / 180;
    camera.position.set(0, d0 * Math.sin(el0), d0 * Math.cos(el0));   // 남쪽에서 북쪽을 본다
  }

  const sky = createSky(HORIZON, ZENITH, c.far * 0.9);
  scene.add(sky);

  // 면 음영: 고정된 해 방향 + 하늘/지면 반구광. 그림자는 아직 없음
  scene.add(new THREE.HemisphereLight(0xeaf1fb, 0x6f6c64, 1.1));
  const sun = new THREE.DirectionalLight(0xfff4e0, 2.6);
  sun.position.set(-0.5, 0.8, 0.35).normalize();        // 남서쪽 위
  scene.add(sun);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(80000, 80000),
    new THREE.MeshLambertMaterial({ color: 0xa9aaa0 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.05;
  scene.add(ground);

  let material = createBuildingMaterial(SETTINGS);
  const tiles = new TileManager(scene, manifest, material, origin, source);

  // 조작: 한 손가락·왼쪽 드래그 이동, 두 손가락 핀치·휠 줌, 두 손가락 드래그·오른쪽 드래그 회전
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableZoom = true;
  controls.minDistance = distFor(c.hMin);
  controls.maxDistance = distFor(c.hMax);
  controls.zoomSpeed = 1.2;
  controls.enableDamping = true;
  controls.screenSpacePanning = false;                           // 지면과 평행하게 이동
  controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
  controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
  controls.target.set(0, 0, 0);
  // 앙각은 사용자가 바꾸지 못하고 줌(거리)으로만 정해진다: 매 프레임 거리 → 높이 → 앙각을 다시 고정
  const pinPolar = () => {
    const h = heightForDist(camera.position.distanceTo(controls.target));
    controls.minPolarAngle = controls.maxPolarAngle = polarFor(h);
    return h;
  };
  pinPolar();
  controls.update();

  // 이동 영역 제한: 주시점을 영역 안으로 되돌리고 카메라도 같이 옮긴다
  const clampTarget = () => {
    const t = controls.target;
    const x = THREE.MathUtils.clamp(t.x, area.xmin - origin.x, area.xmax - origin.x);
    const z = THREE.MathUtils.clamp(t.z, -(area.ymax - origin.y), -(area.ymin - origin.y));
    const dx = x - t.x, dz = z - t.z;
    if (dx || dz || t.y) { t.set(x, 0, z); camera.position.x += dx; camera.position.z += dz; }
  };
  controls.addEventListener('change', clampTarget);

  // 미니맵 탭: 주시점을 그 위치로 옮긴다(카메라 방향·줌 유지)
  const moveTo = (x, y) => {
    const t = controls.target;
    const dx = x - origin.x - t.x, dz = -(y - origin.y) - t.z;
    t.x += dx; t.z += dz;
    camera.position.x += dx; camera.position.z += dz;
    clampTarget();
    controls.update();
  };
  const minimap = manifest.overview
    ? new Minimap(document.getElementById('minimap'), manifest.overview,
      `${CONFIG.tilesBase}${CONFIG.region}/${manifest.overview.file}`, moveTo)
    : null;
  const labels = new AreaLabels(document.getElementById('labels'), manifest.labels || [], origin);

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // 프레임 수: 0.5초마다 갱신
  let frames = 0, lastT = performance.now(), lastTile = 0, lastMap = 0;
  let camH = c.hStart, fogFar = CONFIG.fog.farMin;

  const loop = (now) => {
    camH = pinPolar();
    controls.update();
    clampTarget();
    const dist = camera.position.distanceTo(controls.target);
    // 안개와 불러올 거리: 줌아웃할수록 멀리
    fogFar = Math.max(CONFIG.fog.farMin, CONFIG.fog.farPerDist * dist);
    scene.fog.far = fogFar;
    scene.fog.near = fogFar * CONFIG.fog.nearRatio;
    sky.position.copy(camera.position);
    if (now - lastTile > 150) {
      lastTile = now;
      tiles.update(camera, controls.target, fogFar + 200);
    }
    // 라벨: 카메라 높이가 기준의 80%부터 서서히 나타난다
    const lh = CONFIG.labels.minHeight;
    labels.update(camera, THREE.MathUtils.clamp((camH - 0.8 * lh) / (0.2 * lh), 0, 1), fogFar);
    if (minimap && now - lastMap > 100) { lastMap = now; minimap.draw(camera, controls.target, origin, fogFar); }
    renderer.render(scene, camera);
    const info = { triangles: renderer.info.render.triangles, calls: renderer.info.render.calls };
    frames++;
    if (now - lastT >= 500) {
      const fps = (frames * 1000) / (now - lastT);
      const frameMs = (now - lastT) / frames;
      frames = 0; lastT = now;
      const s = tiles.stats();
      statsEl.textContent =
        `FPS ${fps.toFixed(1)} (${frameMs.toFixed(1)} ms)\n` +
        `삼각형 ${info.triangles.toLocaleString()}  draw call ${info.calls}\n` +
        `타일 LOD0/1/2 ${s.byLod.join('/')}  대기 ${s.pending}\n` +
        `받은 데이터 ${(s.netBytes / 1024 / 1024).toFixed(2)} MB (타일 ${(s.loadedBytes / 1024 / 1024).toFixed(2)} MB)${s.errors ? `  오류 ${s.errors}` : ''}\n` +
        `높이 ${camH.toFixed(0)} m  앙각 ${elevationFor(camH).toFixed(0)}°\n` +
        `픽셀 ${renderer.getPixelRatio().toFixed(2)}x  AA ${SETTINGS.aa ? '켬' : '끔'}  ` +
        `외장 ${SETTINGS.facade ? '켬' : '끔'}  그늘 ${SETTINGS.ground ? '켬' : '끔'}`;
      window.__viewerStats = {
        fps, frameMs, ...info, ...s, settings: { ...SETTINGS },
        height: camH, elevation: elevationFor(camH), labels: labels.count || 0,
        target: { x: origin.x + controls.target.x, y: origin.y - controls.target.z },
      };   // 자동 점검용
    }
  };
  renderer.setAnimationLoop(loop);

  // 설정 적용. 안티에일리어싱은 WebGL 컨텍스트를 새로 만들어야 바뀐다
  const apply = (key) => {
    if (key === 'dpr') {
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, SETTINGS.dpr));
      renderer.setSize(window.innerWidth, window.innerHeight);
    } else if (key === 'aa') {
      const old = renderer;
      old.setAnimationLoop(null);
      renderer = makeRenderer();
      old.domElement.replaceWith(renderer.domElement);
      controls.disconnect();
      controls.connect(renderer.domElement);
      old.dispose();
      old.forceContextLoss();
      renderer.setAnimationLoop(loop);
    } else {
      const old = material;
      material = createBuildingMaterial(SETTINGS);
      tiles.setMaterial(material);
      old.dispose();
    }
    saveSettings();
  };
  setupPanel(apply);

  // 자동 점검(헤드리스 스크린샷)용 손잡이. 화면 기능에는 쓰지 않는다
  window.__viewer = { camera, controls, origin, moveTo };
}

function setupPanel(apply) {
  const panel = document.getElementById('panel');
  document.getElementById('panel-toggle').addEventListener('click', () => { panel.hidden = !panel.hidden; });
  const dpr = panel.querySelector('[name=dpr]');
  const known = [...dpr.options].map((o) => Number(o.value));
  if (!known.includes(SETTINGS.dpr)) dpr.add(new Option(`${SETTINGS.dpr}`, `${SETTINGS.dpr}`));
  dpr.value = `${SETTINGS.dpr}`;
  dpr.addEventListener('change', () => { SETTINGS.dpr = Number(dpr.value); apply('dpr'); });
  for (const key of ['aa', 'facade', 'ground']) {
    const box = panel.querySelector(`[name=${key}]`);
    box.checked = SETTINGS[key];
    box.addEventListener('change', () => { SETTINGS[key] = box.checked; apply(key); });
  }
  document.getElementById('device-dpr').textContent = `기기 ${window.devicePixelRatio.toFixed(2)}`;
}

main().catch((e) => {
  statsEl.textContent = `오류: ${e.message}`;
  console.error(e);
});
