// 미니맵: 빌드 때 만든 개요 이미지(북쪽 위) 위에 현재 주시점과 시야 범위를 그린다. 탭하면 그 위치로 이동.
import * as THREE from 'three';

const MAX_CSS = 150;   // 긴 변 CSS 픽셀

export class Minimap {
  // ov: manifest.overview, imgUrl: 이미지 주소, onPick(x, y): EPSG:5186 좌표로 이동 요청
  constructor(el, ov, imgUrl, onPick) {
    this.ov = ov;
    const [x0, y0, x1, y1] = ov.bounds;
    this.b = { x0, y0, x1, y1 };
    const k = MAX_CSS / Math.max(ov.width, ov.height);
    this.w = Math.round(ov.width * k);
    this.h = Math.round(ov.height * k);
    el.style.width = `${this.w}px`;
    el.style.height = `${this.h}px`;
    const img = new Image();
    img.src = imgUrl;
    img.alt = '';
    img.draggable = false;
    this.canvas = document.createElement('canvas');
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx = this.canvas.getContext('2d');
    this.ctx.scale(dpr, dpr);
    el.append(img, this.canvas);
    el.hidden = false;
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
      onPick(x0 + px * (x1 - x0), y1 - py * (y1 - y0));
    });
    this._ray = new THREE.Vector3();
  }

  _px(x, y) {
    const { x0, y0, x1, y1 } = this.b;
    return [((x - x0) / (x1 - x0)) * this.w, ((y1 - y) / (y1 - y0)) * this.h];
  }

  // 화면 네 모서리 광선이 지면(높이 0)과 만나는 점. 지평선 위를 향하면 안개 끝 거리에서 자른다
  _footprint(camera, origin, maxDist) {
    const cam = camera.position;
    const pts = [];
    for (const [nx, ny] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      const dir = this._ray.set(nx, ny, 0.5).unproject(camera).sub(cam).normalize();
      let gx, gz;
      const horiz = Math.hypot(dir.x, dir.z) || 1e-6;
      const tGround = dir.y < -1e-4 ? -cam.y / dir.y : Infinity;
      const reach = Math.min(tGround * horiz, maxDist);      // 수평 거리
      gx = cam.x + (dir.x / horiz) * reach;
      gz = cam.z + (dir.z / horiz) * reach;
      pts.push(this._px(gx + origin.x, origin.y - gz));
    }
    return pts;
  }

  draw(camera, target, origin, maxDist) {
    const c = this.ctx;
    c.clearRect(0, 0, this.w, this.h);
    const fp = this._footprint(camera, origin, maxDist);
    c.beginPath();
    fp.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y)));
    c.closePath();
    c.fillStyle = 'rgba(255, 196, 64, 0.22)';
    c.strokeStyle = 'rgba(255, 196, 64, 0.95)';
    c.lineWidth = 1.2;
    c.fill();
    c.stroke();
    const [cx, cy] = this._px(camera.position.x + origin.x, origin.y - camera.position.z);
    const [tx, ty] = this._px(target.x + origin.x, origin.y - target.z);
    c.beginPath();
    c.moveTo(cx, cy);
    c.lineTo(tx, ty);
    c.strokeStyle = 'rgba(255, 255, 255, 0.6)';
    c.stroke();
    c.beginPath();
    c.arc(tx, ty, 3.5, 0, Math.PI * 2);
    c.fillStyle = '#ff5a4f';
    c.fill();
    c.strokeStyle = '#fff';
    c.lineWidth = 1;
    c.stroke();
  }
}
