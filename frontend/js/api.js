/* ============================================================
   agent-test-flow · 前端传输层
   后端可用 → 走真实 step1（数据集生成）；不可用 → index.html 自动回退演示动画。
   这一层只负责「取数」，不碰任何 DOM 结构。
   ============================================================ */
(function () {
  'use strict';

  /* 供自动化验收读取的未捕获错误收集器 */
  window.__errs = window.__errs || [];
  window.addEventListener('error', e => window.__errs.push(String((e && e.message) || e)));
  window.addEventListener('unhandledrejection', e =>
    window.__errs.push('unhandledrejection: ' + String((e && e.reason) || e)));

  const S = { mode: 'unknown', health: null, matrix: null, error: '' };

  async function jget(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
    return r.json();
  }
  async function jpost(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
    return r.json();
  }
  const terminal = s => ['completed', 'failed', 'cancelled'].indexOf(s) >= 0;

  const API = {
    state: S,
    get live() { return S.mode === 'live'; },

    /* 探测后端；失败即视为演示模式 */
    async probe() {
      try {
        const h = await jget('api/health');
        if (!h || !h.ok) throw new Error('health 未就绪');
        S.health = h; S.mode = 'live'; S.error = '';
        return true;
      } catch (e) {
        S.mode = 'demo'; S.error = String((e && e.message) || e);
        return false;
      }
    },

    async matrix() {
      if (!S.matrix) S.matrix = await jget('api/scene-matrix');
      return S.matrix;
    },

    /* 场景预览：还没有 run 也能拿到该场景的树 + 矩阵结构（同一个聚合函数产出） */
    scenePreview(scene, agentId) {
      return jget('api/scene-preview?scene=' + encodeURIComponent(scene || '')
        + '&agent_id=' + encodeURIComponent(agentId || ''));
    },

    /* r1 智能体接入 */
    agentConnect(payload) { return jpost('api/agent/connect', payload); },
    agentStatus(id) { return jget('api/agent/status?id=' + encodeURIComponent(id)); },

    /* step1 数据集生成 */
    createDataset(payload) { return jpost('api/dataset-ext/runs', payload); },
    summary(id) { return jget('api/dataset-ext/run/summary?id=' + encodeURIComponent(id)); },
    raw(id) { return jget('api/dataset-ext/run?id=' + encodeURIComponent(id)); },
    cancel(id) { return jpost('api/dataset-ext/runs/cancel', { id: id }); },

    /* 订阅 step1 进度：SSE 作触发源 + 1.2s 轮询兜底（SSE 断线也能跑完） */
    stream(id, onView) {
      let closed = false, es = null, timer = null, inflight = false, last = 0;
      const stop = () => {
        if (closed) return;
        closed = true;
        if (es) { try { es.close(); } catch (e) { /* ignore */ } es = null; }
        if (timer) { clearInterval(timer); timer = null; }
      };
      const tick = async (force) => {
        if (closed || inflight) return;
        const now = Date.now();
        if (!force && now - last < 250) return;
        last = now; inflight = true;
        try {
          const v = await API.summary(id);
          if (v && v.ok) { onView(v); if (terminal(v.status)) stop(); }
        } catch (e) { /* 网络抖动：交给轮询兜底 */ }
        finally { inflight = false; }
      };
      try {
        es = new EventSource('api/dataset-ext/stream?id=' + encodeURIComponent(id));
        ['snapshot', 'status', 'step', 'progress', 'log'].forEach(ev => {
          es.addEventListener(ev, () => tick(false));
        });
        es.onerror = () => { /* EventSource 自行重连，轮询同时兜底 */ };
      } catch (e) { es = null; }
      timer = setInterval(() => tick(true), 1200);
      tick(true);
      return { stop: stop };
    }
  };

  window.API = API;
})();
