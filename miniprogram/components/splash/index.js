Component({
  data: { hiding: false, shards: [], tiles: [] },
  lifetimes: {
    attached() {
      // 爆裂碎片
      const shards = [];
      const N = 12;
      for (let i = 0; i < N; i++) {
        const a = (i / N) * Math.PI * 2 + (Math.random() - 0.5) * 0.5;
        const dist = 220 + Math.random() * 160;
        shards.push({ i, tx: Math.round(Math.cos(a) * dist), ty: Math.round(Math.sin(a) * dist), rot: Math.round((Math.random() - 0.5) * 540) });
      }
      // 曲面屏散布的人脸（噪声↔清晰 morph + 浮动）
      const tiles = [];
      const T = 9; // 周围照片减量 ~20%
      for (let i = 0; i < T; i++) {
        const a = (i / T) * Math.PI * 2;
        tiles.push({
          i,
          src: `/assets/faces/face-${(i % 6) + 1}.jpg`,
          x: Math.round(Math.cos(a) * 340),
          y: Math.round(Math.sin(a) * 480),
          rot: Math.round(Math.cos(a) * 12),
          s: (0.46 + Math.abs(Math.sin(a)) * 0.16).toFixed(2),
          d: (Math.random() * 3.2).toFixed(2),
        });
      }
      this.setData({ shards, tiles });
      // 周围照片随机切换（项目人脸轮换）
      this._sw = setInterval(() => {
        const n = this.data.tiles.length; if (!n) return;
        const idx = Math.floor(Math.random() * n);
        const f = Math.floor(Math.random() * 6) + 1;
        this.setData({ ['tiles[' + idx + '].src']: `/assets/faces/face-${f}.jpg` });
      }, 1300);
      // 玻璃破碎音效：用户提供 /assets/glass-break.mp3；缺失则静默
      try { this._audio = wx.createInnerAudioContext(); this._audio.src = '/assets/glass-break.mp3'; } catch (e) {}
      this._t0 = setTimeout(() => { try { this._audio && this._audio.play(); } catch (e) {} }, 2750);
      this._t1 = setTimeout(() => this.setData({ hiding: true }), 4300);
      this._t2 = setTimeout(() => this.triggerEvent('done'), 4700);
    },
    detached() {
      clearTimeout(this._t0); clearTimeout(this._t1); clearTimeout(this._t2); clearInterval(this._sw);
      try { this._audio && this._audio.destroy(); } catch (e) {}
    },
  },
  methods: {
    skip() {
      clearTimeout(this._t0); clearTimeout(this._t1); clearTimeout(this._t2); clearInterval(this._sw);
      try { this._audio && this._audio.stop(); } catch (e) {}
      this.setData({ hiding: true });
      setTimeout(() => this.triggerEvent('done'), 320);
    },
  },
});
