// 粒子背景：仅在屏幕左右两侧边带绘制，正弦波浪 + 缓慢上浮，绝不压在中间文字下
Component({
  lifetimes: {
    ready() { this._stop = false; this._init(); },
    detached() { this._stop = true; },
  },
  pageLifetimes: {
    show() { if (this._inited && this._stop) { this._stop = false; this._loop(); } },
    hide() { this._stop = true; },
  },
  methods: {
    _init() {
      this.createSelectorQuery().in(this).select('#pcv').fields({ node: true, size: true }).exec((res) => {
        if (!res || !res[0] || !res[0].node) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext('2d');
        const info = (wx.getWindowInfo && wx.getWindowInfo()) || wx.getSystemInfoSync();
        const dpr = info.pixelRatio || 2;
        const W = res[0].width || info.windowWidth;
        const H = res[0].height || info.windowHeight;
        canvas.width = W * dpr; canvas.height = H * dpr; ctx.scale(dpr, dpr);

        const bandW = W * 0.18;
        const bands = [{ a: 0, b: bandW }, { a: W - bandW, b: W }];
        const perBand = 11;
        const ns = [];
        for (const bd of bands) {
          for (let i = 0; i < perBand; i++) {
            ns.push({
              bx: bd.a + Math.random() * (bd.b - bd.a),
              left: bd.a < W / 2,
              y: Math.random() * H,
              r: Math.random() * 2 + 1.2,
              ph: Math.random() * 6.28,
              amp: 8 + Math.random() * 18,
              vy: 0.12 + Math.random() * 0.22,
              blue: Math.random() < 0.4,
            });
          }
        }
        this._ctx = ctx; this._canvas = canvas; this._W = W; this._H = H; this._ns = ns; this._t = 0; this._inited = true;
        this._loop();
      });
    },
    _loop() {
      if (this._stop || !this._ctx) return;
      const ctx = this._ctx, W = this._W, H = this._H, ns = this._ns;
      this._t += 0.016;
      ctx.clearRect(0, 0, W, H);
      // 位置更新 + 节点
      for (const n of ns) {
        n.y -= n.vy; if (n.y < -14) n.y = H + 14;
        n.x = n.bx + Math.sin(this._t * 0.9 + n.ph + n.y * 0.012) * n.amp;
        ctx.beginPath();
        ctx.fillStyle = n.blue ? 'rgba(14,165,233,0.06)' : 'rgba(3,105,161,0.07)';
        ctx.arc(n.x, n.y, n.r * 3.4, 0, 6.2832); ctx.fill();
        ctx.beginPath();
        ctx.fillStyle = n.blue ? 'rgba(14,165,233,0.5)' : 'rgba(3,105,161,0.55)';
        ctx.arc(n.x, n.y, n.r, 0, 6.2832); ctx.fill();
      }
      // 同侧相邻连线（淡）
      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          const a = ns[i], b = ns[j];
          if (a.left !== b.left) continue;
          const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
          if (d2 < 22500) {
            const o = (1 - Math.sqrt(d2) / 150) * 0.28;
            ctx.strokeStyle = 'rgba(3,105,161,' + (o * 0.8).toFixed(3) + ')';
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
      }
      this._canvas.requestAnimationFrame(() => this._loop());
    },
  },
});
