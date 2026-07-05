// 点击粒子反馈：固定全屏 canvas(不挡点击)，外部调用 burst(x,y) 在点击处迸发粒子
Component({
  lifetimes: {
    ready() { this._stop = false; this._init(); },
    detached() { this._stop = true; },
  },
  methods: {
    _init() {
      this.createSelectorQuery().in(this).select('#fxcv').fields({ node: true, size: true }).exec((res) => {
        if (!res || !res[0] || !res[0].node) return;
        const c = res[0].node;
        const ctx = c.getContext('2d');
        const info = (wx.getWindowInfo && wx.getWindowInfo()) || wx.getSystemInfoSync();
        const dpr = info.pixelRatio || 2;
        const W = res[0].width || info.windowWidth;
        const H = res[0].height || info.windowHeight;
        c.width = W * dpr; c.height = H * dpr; ctx.scale(dpr, dpr);
        this._ctx = ctx; this._c = c; this._W = W; this._H = H; this._ps = []; this._running = false;
      });
    },
    burst(x, y) {
      if (!this._ctx) return;
      const n = 12;
      for (let i = 0; i < n; i++) {
        const a = (i / n) * 6.2832 + Math.random() * 0.4;
        const sp = 1.6 + Math.random() * 2.8;
        this._ps.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 0.6, life: 1, r: 2 + Math.random() * 3, blue: Math.random() < 0.5 });
      }
      // 中心一圈扩散环
      this._ring = { x, y, r: 6, life: 1 };
      if (!this._running) { this._running = true; this._loop(); }
    },
    _loop() {
      if (this._stop || !this._ctx) return;
      const ctx = this._ctx, W = this._W, H = this._H, ps = this._ps;
      ctx.clearRect(0, 0, W, H);
      if (this._ring && this._ring.life > 0) {
        const g = this._ring;
        g.r += 6; g.life -= 0.06;
        ctx.globalAlpha = Math.max(0, g.life) * 0.6;
        ctx.strokeStyle = '#0ea5e9'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(g.x, g.y, g.r, 0, 6.2832); ctx.stroke();
      }
      for (let i = ps.length - 1; i >= 0; i--) {
        const p = ps[i];
        p.x += p.vx; p.y += p.vy; p.vy += 0.12; p.vx *= 0.98; p.life -= 0.035;
        if (p.life <= 0) { ps.splice(i, 1); continue; }
        ctx.globalAlpha = Math.max(0, p.life);
        ctx.fillStyle = p.blue ? '#0ea5e9' : '#0369a1';
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * p.life, 0, 6.2832); ctx.fill();
      }
      ctx.globalAlpha = 1;
      const alive = ps.length > 0 || (this._ring && this._ring.life > 0);
      if (alive) { this._c.requestAnimationFrame(() => this._loop()); }
      else { this._running = false; ctx.clearRect(0, 0, W, H); }
    },
  },
});
