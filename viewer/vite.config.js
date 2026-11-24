import { defineConfig } from 'vite';

// 타일은 scripts/tile.py가 data/processed/tiles/<지역>/ 에 만든다. 그 폴더를 정적 파일로 그대로 제공한다.
export default defineConfig({
  publicDir: '../data/processed/tiles',
  base: './',
  server: { port: 5173 },
  preview: { port: 4173 },
});
