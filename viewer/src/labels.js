// 법정동(리) 이름 라벨: 줌아웃해서 카메라 높이가 기준 이상일 때 표시. 겹치면 건물이 많은 동을 남긴다.
import * as THREE from 'three';

export class AreaLabels {
  constructor(el, labels, origin) {
    this.el = el;
    this.items = labels.map((l) => {
      const div = document.createElement('div');
      div.className = 'area-label';
      div.textContent = l.name;
      div.style.display = 'none';
      el.appendChild(div);
      return { ...l, div, pos: new THREE.Vector3(l.x - origin.x, 0, -(l.y - origin.y)), w: 0, shown: false };
    });
    this._v = new THREE.Vector3();
  }

  // opacity: 0~1(줌 높이에 따른 투명도), maxDist: 이보다 먼 라벨은 숨김(안개 안쪽만)
  update(camera, opacity, maxDist) {
    if (opacity <= 0) {
      if (this.visible !== false) { for (const it of this.items) this._set(it, false); this.visible = false; }
      this.count = 0;
      return;
    }
    this.visible = true;
    this.el.style.opacity = opacity.toFixed(2);
    const W = window.innerWidth, H = window.innerHeight;
    const placed = [];
    for (const it of this.items) {                 // items는 건물 수 내림차순
      const d = it.pos.distanceTo(camera.position);
      const p = this._v.copy(it.pos).project(camera);
      if (d > maxDist || p.z > 1 || p.x < -1.1 || p.x > 1.1 || p.y < -1.1 || p.y > 1.1) { this._set(it, false); continue; }
      const sx = (p.x * 0.5 + 0.5) * W, sy = (-p.y * 0.5 + 0.5) * H;
      if (!it.w) it.w = it.name.length * 13 + 12;    // 대략 폭(글자 13px)
      const r = { x0: sx - it.w / 2, x1: sx + it.w / 2, y0: sy - 11, y1: sy + 11 };
      if (placed.some((q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0)) { this._set(it, false); continue; }
      placed.push(r);
      it.div.style.transform = `translate(${Math.round(r.x0)}px, ${Math.round(r.y0)}px)`;
      this._set(it, true);
    }
    this.count = placed.length;
  }

  _set(it, on) {
    if (it.shown === on) return;
    it.shown = on;
    it.div.style.display = on ? '' : 'none';
  }
}
