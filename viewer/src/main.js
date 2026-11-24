import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CONFIG } from './config.js';
import { TileManager } from './tiles.js';
import { createSky } from './sky.js';

const HORIZON = 0xd9e2ea;   // 안개 = 지평선 색
const ZENITH = 0x6f9fd8;

const statsEl = document.getElementById('stats');

async function main() {
  const res = await fetch(`${CONFIG.tilesBase}${CONFIG.region}/manifest.json`);
  if (!res.ok) throw new Error(`manifest를 읽지 못했습니다 (${res.status}). scripts/tile.py로 타일을 먼저 만드세요.`);
  const manifest = await res.json();

  // 장면 원점 = 시작 위치. three.js 좌표: X = 동, Y = 위, Z = -북
  const origin = { x: manifest.start.x, y: manifest.start.y };
  const [bx0, by0, bx1, by1] = manifest.bounds;
  const H = CONFIG.regionHalfSize;
  const area = {
    xmin: Math.max(origin.x - H, bx0), xmax: Math.min(origin.x + H, bx1),
    ymin: Math.max(origin.y - H, by0), ymax: Math.min(origin.y + H, by1),
  };

  const renderer = new THREE.WebGLRenderer({ antialias: CONFIG.antialias, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, CONFIG.pixelRatioMax));
  renderer.setSize(window.innerWidth, window.innerHeight);
  document.body.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(HORIZON, CONFIG.fog.near, CONFIG.fog.far);

  const c = CONFIG.camera;
  const camera = new THREE.PerspectiveCamera(c.fov, window.innerWidth / window.innerHeight, c.near, c.far);
  const el = THREE.MathUtils.degToRad(c.elevationDeg);
  camera.position.set(0, c.distance * Math.sin(el), c.distance * Math.cos(el));   // 남쪽에서 북쪽을 본다

  const sky = createSky(HORIZON, ZENITH, c.far * 0.9);
  scene.add(sky);

  // 면 음영: 고정된 해 방향 + 하늘/지면 반구광. 그림자는 아직 없음
  scene.add(new THREE.HemisphereLight(0xeaf1fb, 0x6f6c64, 1.1));
  const sun = new THREE.DirectionalLight(0xfff4e0, 2.6);
  sun.position.set(-0.5, 0.8, 0.35).normalize();        // 남서쪽 위
  scene.add(sun);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(40000, 40000),
    new THREE.MeshLambertMaterial({ color: 0xa9aaa0 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.05;
  scene.add(ground);

  const material = new THREE.MeshLambertMaterial({ color: 0xece7de });
  const tiles = new TileManager(scene, manifest, material, origin);

  const controls = new OrbitControls(camera, renderer.domElement);
  const polar = Math.PI / 2 - el;
  controls.minPolarAngle = controls.maxPolarAngle = polar;      // 각도 고정
  controls.enableZoom = false;                                   // 높이 고정
  controls.enableDamping = true;
  controls.screenSpacePanning = false;                           // 지면과 평행하게 이동
  controls.panSpeed = 1.0;
  controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.ROTATE, RIGHT: THREE.MOUSE.ROTATE };
  controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
  controls.target.set(0, 0, 0);
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

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // 프레임 수: 0.5초마다 갱신
  let frames = 0, lastT = performance.now(), fps = 0, frameMs = 0, lastTile = 0;
  let info = { triangles: 0, calls: 0 };

  renderer.setAnimationLoop((now) => {
    controls.update();
    clampTarget();
    sky.position.copy(camera.position);
    if (now - lastTile > 150) {
      lastTile = now;
      tiles.update(origin.x + controls.target.x, origin.y - controls.target.z);
    }
    renderer.render(scene, camera);
    info = { triangles: renderer.info.render.triangles, calls: renderer.info.render.calls };
    frames++;
    if (now - lastT >= 500) {
      fps = (frames * 1000) / (now - lastT);
      frameMs = (now - lastT) / frames;
      frames = 0; lastT = now;
      const s = tiles.stats();
      statsEl.textContent =
        `FPS ${fps.toFixed(1)} (${frameMs.toFixed(1)} ms)\n` +
        `삼각형 ${info.triangles.toLocaleString()}  draw call ${info.calls}\n` +
        `타일 LOD0/1/2 ${s.byLod.join('/')}  대기 ${s.pending}\n` +
        `받은 데이터 ${(s.loadedBytes / 1024 / 1024).toFixed(2)} MB${s.errors ? `  오류 ${s.errors}` : ''}\n` +
        `주시점 ${(origin.x + controls.target.x).toFixed(0)}, ${(origin.y - controls.target.z).toFixed(0)}  ` +
        `${renderer.getPixelRatio().toFixed(2)}x`;
      window.__viewerStats = { fps, frameMs, ...info, ...s };   // 자동 점검용
    }
  });
}

main().catch((e) => {
  statsEl.textContent = `오류: ${e.message}`;
  console.error(e);
});
