/**
 * 前端端到端验收：用 jsdom 载入真实页面（frontend/index.html + js/api.js），
 * 对接真实后端跑完整流程，验证 index 结构、步骤条与真实 step1 数据的联动。
 *
 * 本沙箱无法启动 Chrome/Edge（调试端口被禁），故用 jsdom + fetch/EventSource 垫片
 * 驱动同一份前端代码。SSE 垫片会真连后端的 /api/dataset-ext/stream，顺带验证事件格式。
 *
 * 用法：
 *   node tools/e2e_frontend.mjs --url http://127.0.0.1:8787/ --mode live
 *   node tools/e2e_frontend.mjs --url http://127.0.0.1:8787/ --mode demo
 * 前置：jsdom 需可用（见 README「开发工具」；用 ATF_JSDOM 指定路径）。
 */
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

const args = process.argv.slice(2);
const arg = (k, d) => {
  const i = args.indexOf('--' + k);
  return i >= 0 && args[i + 1] ? args[i + 1] : d;
};
const URL_ = arg('url', 'http://127.0.0.1:8787/');
const MODE = arg('mode', 'live');
const JSDOM_PATH = process.env.ATF_JSDOM
  || join(process.env.TEMP || '/tmp', 'atf-jsdom', 'node_modules', 'jsdom', 'lib', 'api.js');

let PASS = 0, FAIL = 0;
const ok = (name, cond, detail = '') => {
  if (cond) { PASS++; console.log(`  [PASS] ${name}${detail ? ' · ' + detail : ''}`); }
  else { FAIL++; console.log(`  [FAIL] ${name}${detail ? ' · ' + detail : ''}`); }
  return !!cond;
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

const { JSDOM } = await import(pathToFileURL(JSDOM_PATH).href);

/* ---- fetch 垫片：live 走真后端；demo 让 /api/* 全部失败（模拟后端未启动）---- */
function installShims(win, baseUrl, mode) {
  const realFetch = globalThis.fetch;
  win.fetch = (input, init) => {
    const url = new URL(String(input), baseUrl).href;
    if (mode === 'demo' && url.includes('/api/')) {
      return Promise.reject(new TypeError('Failed to fetch (demo 模式模拟后端不可用)'));
    }
    return realFetch(url, init);
  };
  /* EventSource 垫片：真连后端 SSE，解析 event/data 分帧（顺带验证后端事件格式） */
  win.EventSource = class {
    constructor(url) {
      this.url = new URL(url, baseUrl).href;
      this.onerror = null;
      this._l = {};
      this._closed = false;
      this._pump();
    }
    addEventListener(t, fn) { (this._l[t] = this._l[t] || []).push(fn); }
    close() { this._closed = true; }
    _emit(t, data) { (this._l[t] || []).forEach(f => { try { f({ type: t, data: JSON.stringify(data) }); } catch (e) { win.__errs.push(String(e)); } }); }
    async _pump() {
      try {
        const r = await win.fetch(this.url);
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done || this._closed) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
            let ev = 'message', data = '';
            chunk.split('\n').forEach(l => {
              if (l.startsWith('event:')) ev = l.slice(6).trim();
              else if (l.startsWith('data:')) data += l.slice(5).trim();
            });
            if (data) { try { this._emit(ev, JSON.parse(data)); } catch (e) { /* ignore */ } }
          }
        }
      } catch (e) { if (this.onerror) this.onerror(e); }
    }
  };
}

async function main() {
  const dom = await JSDOM.fromURL(URL_, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    beforeParse: win => installShims(win, URL_, MODE),
  });
  const win = dom.window, doc = win.document;
  const $ = sel => doc.querySelector(sel);
  const text = sel => ($(sel) || {}).textContent;

  const waitFor = async (label, fn, ms) => {
    const t0 = Date.now();
    for (;;) {
      try { const v = fn(); if (v) return v; } catch (e) { /* 未就绪 */ }
      if (Date.now() - t0 > ms) throw new Error(`等待超时：${label}`);
      await sleep(150);
    }
  };

  console.log(`\n== 页面加载（${MODE}）==`);
  await waitFor('前端初始化', () => win.__api && win.__demo && win.API, 20000);
  await waitFor('数据源探测完成', () => win.__api.mode !== 'unknown', 20000);
  ok(`数据源模式 = ${MODE}`, win.__api.mode === MODE, 'mode=' + win.__api.mode);

  const sb0 = win.__api.stepBar();
  ok('步骤条 4 步渲染', Object.keys(sb0).length === 4, JSON.stringify(sb0));
  ok('步骤条 2/3/4 为占位「待命」',
    sb0[2] === '待命' && sb0[3] === '待命' && sb0[4] === '待命', JSON.stringify(sb0));
  ok('顶部步骤条 DOM 落在 r7 预留条内', !!$('#r7 .mp-step-bar') || !!$('header.r7 .mp-step-bar'));
  ok('index 七区域齐全（r1–r6 面板 + r7 步骤条预留条）',
    ['r1', 'r2', 'r3', 'r4', 'r5', 'r6'].every(id => !!doc.getElementById(id)) && !!$('header.r7'));
  ok('index 原结构未被破坏（.page/.grid/.rcol/6 面板）',
    !!$('.page .grid') && !!$('.rcol') && doc.querySelectorAll('.grid .panel').length === 6,
    'panels=' + doc.querySelectorAll('.grid .panel').length);
  ok('能力矩阵列数 = 13', doc.querySelectorAll('#matrix .mx-cap').length === 13,
    'caps=' + doc.querySelectorAll('#matrix .mx-cap').length);
  const binAccept = (doc.getElementById('file-bin') || {}).accept;
  ok('二进制槽位只接受 .zip', binAccept === '.zip', 'accept=' + binAccept);
  const cfgAccept = (doc.getElementById('file-cfg') || {}).accept || '';
  ok('配置槽位接受 yaml/json', /\.yaml/.test(cfgAccept) && /\.json/.test(cfgAccept), 'accept=' + cfgAccept);
  const slots = win.__api.slots();
  ok('二进制回退名与示例包一致', slots[0].fallback.name === 'shopping-agent-v2.zip',
    JSON.stringify(slots[0].fallback));
  ok('二进制槽位提示 .zip', /\.zip/.test(slots[0].hint), slots[0].hint);
  const cssText = await (await fetch(new URL('css/pipeline-bar.css', URL_).href)).text();
  ok('完成态不再用整块底色（去掉彩色 pill）',
    /\.mp-step\.is-completed\s*\{\s*background:\s*none/.test(cssText)
    && !/is-completed\s*\{\s*background:\s*var\(--success-soft\)/.test(cssText));
  ok('状态用底部细线指示（is-current::after）',
    /\.mp-step\.is-current\.is-completed::after/.test(cssText));
  const inlineCss = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');
  const g0 = win.__api.genSizing();
  ok('生成台默认吃满右侧剩余宽度（CSS calc，只给树留最小值 + 分隔条）',
    new RegExp('\\.gen-console\\s*\\{[^}]*width:\\s*min\\(calc\\(100% - ' + g0.reserve + 'px\\),'
      + g0.cap + 'px\\)').test(inlineCss),
    `reserve=${g0.reserve} cap=${g0.cap}（CSS 常量与 JS 常量一致，防漂移）`);
  ok('不再有写死的固定宽度（旧的 120px / 200px 都没了）',
    !/\.gen-console\s*\{[^}]*width:\s*(120|200)px/.test(inlineCss));
  ok('默认态不写内联宽度、标记为未手动（宽度交给 CSS 自适应）',
    g0.inline === '' && g0.manual === false, JSON.stringify({ inline: g0.inline, manual: g0.manual }));
  ok('生成台宽度可用分隔条拖拽（分隔条 + 抓手线 + col-resize）',
    g0.splitter
    && /\.r3-split\s*\{[^}]*cursor:\s*col-resize/.test(inlineCss)
    && /\.r3-split\s+i\s*\{[^}]*width:\s*2px/.test(inlineCss));
  ok('生成台标题为两行结构（标签行 + 数量行）',
    /\.gen-console\s+\.gh\s+\.n\s*\{[^}]*display:\s*block/.test(inlineCss));

  console.log('\n== 生成台宽度可调（默认吃满）==');
  const splitEl = doc.getElementById('r3-split');
  const drag = clientX => {
    splitEl.dispatchEvent(new win.MouseEvent('mousedown', { clientX, bubbles: true }));
    win.dispatchEvent(new win.MouseEvent('mousemove', { clientX, bubbles: true }));
    win.dispatchEvent(new win.MouseEvent('mouseup', {}));
  };
  drag(100000);                                   // 往右拖到底 → 最窄
  const gMin = win.__api.genSizing();
  ok('往右拖到底 → 夹到下界 140px，并记忆到 localStorage',
    gMin.inline === '140px' && gMin.stored === '140' && gMin.manual === true, JSON.stringify(gMin));
  drag(-100000);                                  // 往左拖到底 → 最宽（上限）
  const gMax = win.__api.genSizing();
  ok('往左拖到底 → 夹到上限（= 默认吃满宽度），不会超出',
    gMax.inline === g0.max + 'px' && gMax.stored === String(g0.max), JSON.stringify(gMax));
  splitEl.dispatchEvent(new win.MouseEvent('dblclick', { bubbles: true }));
  const gReset = win.__api.genSizing();
  ok('双击分隔条 → 清掉内联宽度与记忆，回到「吃满」默认',
    gReset.inline === '' && gReset.stored === null && gReset.manual === false, JSON.stringify(gReset));
  ok('回到默认后宽度交给 CSS（树仍至少保留 treeMin）',
    gReset.treeMin === 160 && gReset.reserve === gReset.treeMin + gReset.splitW,
    `treeMin=${gReset.treeMin} reserve=${gReset.reserve}`);
  await waitFor('顶部徽标就绪', () =>
    !/检测中/.test(((doc.getElementById('mp-bar-meta-text') || {}).textContent || '')), 20000);
  const metaText = ((doc.getElementById('mp-bar-meta-text') || {}).textContent || '').trim();
  const metaTitle = (doc.getElementById('mp-bar-meta') || {}).title || '';
  ok('顶部徽标只显示引擎（不再堆三件事）',
    MODE === 'live' ? (metaText === 'mock' || /^LLM /.test(metaText)) : metaText === '演示模式',
    'text=' + metaText);
  ok('后端连接状态与场景挪进 tooltip（信息没丢，只是降级为悬停可见）',
    MODE === 'live'
      ? (/数据集生成引擎/.test(metaTitle) && /后端：已连接/.test(metaTitle) && /场景：/.test(metaTitle))
      : /未连接后端/.test(metaTitle),
    metaTitle.split('\n')[0].slice(0, 44));
  ok('可见文本里不再有冗长的旧串',
    !/后端已连接/.test(metaText) && !/场景/.test(metaText) && !/引擎/.test(metaText), metaText);
  const rp = win.__api.runParams();
  ok('r2 场景下拉：真实态 14 个场景 / 演示态 1 个',
    MODE === 'live' ? rp.options === 14 : rp.options === 1, 'options=' + rp.options);
  ok('r2 任务数/变体数默认 4 / 2', rp.tasks === 4 && rp.variants === 2,
    `tasks=${rp.tasks} variants=${rp.variants}`);
  ok(MODE === 'live' ? '真实态场景可选（不再是写死的 scenes[0]）' : '演示态运行参数整体禁用',
    MODE === 'live' ? rp.sceneDisabled === false : rp.sceneDisabled === true,
    'disabled=' + rp.sceneDisabled);
  if (MODE === 'live') {
    await waitFor('场景规模就绪', () => /格/.test(win.__api.sceneMeta()), 20000);
    ok('场景维度规模由真实矩阵算出', /类别 · \d+ 维度 · \d+ 格/.test(win.__api.sceneMeta()),
      win.__api.sceneMeta());
  }

  console.log('\n== r1 智能体接入 ==');
  if (MODE === 'live') {
    /* 经真实前端路径注入：zip 文件名 + 配置文件内容（走 readConfigText → agentPayload） */
    const TEST_YAML = ['name: shopping-agent-v2',
      'api: http://127.0.0.1:9/v1',
      'key: sk-test-abcdefghijklmnop',
      'model: gpt-4o-mini',
      'missing_capabilities: [图像识别]', ''].join('\n');
    win.setFile('bin', 'shopping-agent-v2.zip', '1.8 KB', null);
    win.setFile('cfg', 'shopping-agent.yaml', '1.8 KB', { text: async () => TEST_YAML });
  }
  win.document.getElementById('btn-connect').click();
  await waitFor('进入 connecting', () => win.__demo.phase === 'connecting', 10000);
  await waitFor('接入完成', () => win.__demo.phase === 'ready', 60000);
  ok('接入完成 → phase=ready', win.__demo.phase === 'ready');
  ok('r1 状态 = Agent Ready', text('#r1-status') === 'Agent Ready', text('#r1-status'));
  const logLines = doc.querySelectorAll('#console-body .log-line:not(.ok-line)').length;
  const consoleText = [...doc.querySelectorAll('#console-body .log-line')]
    .map(e => e.textContent).join('\n');
  if (MODE === 'live') {
    ok('接入 console 输出 6 条识别日志', logLines === 6, 'log-line=' + logLines);
    const rl = (($('.ok-line') || {}).textContent || '').trim();
    ok('console 出现 Agent Ready 行', /shopping-agent-v2/.test(rl), rl.slice(0, 70));
    ok('Agent Ready 行带上配置里的 model', /gpt-4o-mini/.test(rl), rl.slice(0, 70));
    const prof = win.__api.agentProfile() || {};
    ok('后端解析出配置里的 api / model',
      prof.endpoint === 'http://127.0.0.1:9/v1' && prof.model === 'gpt-4o-mini',
      `endpoint=${prof.endpoint} model=${prof.model}`);
    ok('API Key 只回显掩码', prof.api_key_masked === 'sk-t****mnop' && prof.has_api_key === true,
      String(prof.api_key_masked));
    ok('完整 key 未出现在页面/响应里',
      consoleText.indexOf('sk-test-abcdefghijklmnop') < 0
      && JSON.stringify(prof).indexOf('sk-test-abcdefghijklmnop') < 0);
    ok('zip 只记元数据、不落盘',
      prof.binary === 'shopping-agent-v2.zip' && prof.binary_stored === false,
      `binary=${prof.binary} stored=${prof.binary_stored}`);
    const connLine = (consoleText.split('\n').find(t => /模型联通性/.test(t)) || '').trim();
    ok('联通性用配置里的 api 真探（非“未声明 api”）',
      /模型联通性识别中…（/.test(connLine) && !/未声明 api/.test(connLine), connLine.slice(0, 95));
    ok('探测结论与 profile.connectivity 一致',
      (prof.connectivity || {}).detail && connLine.indexOf(String(prof.connectivity.detail).slice(0, 20)) > -1,
      `ok=${(prof.connectivity || {}).ok}`);
  } else {
    ok('演示态接入 console 有日志', logLines >= 6, 'log-line=' + logLines);
  }

  console.log('\n== step1 提交并跑完 ==');
  win.document.getElementById('task-input').value = '测试该智能体完成电商购物任务的能力，覆盖商品属性、筛选条件、交易属性等维度。';
  const t0 = Date.now();
  win.document.getElementById('btn-run').click();
  await waitFor('step1 完成', () => win.__demo.phase === 'done', 240000);
  const cost = ((Date.now() - t0) / 1000).toFixed(1);
  ok('流程走到 done', win.__demo.phase === 'done', cost + 's');
  await sleep(2500);   // 等 r5 滚动结算收敛

  const V = JSON.parse(JSON.stringify(win.__api.view()));
  const treeRows = doc.querySelectorAll('#tree .trow').length;
  const cells = win.__api.matrixCells();
  const lit = win.__api.litCells();
  const r5v = win.__demo.r5vals();
  const r6rows = doc.querySelectorAll('#r6-table tr').length - 1;
  const r4count = text('#r4-count'), r3count = text('#r3-count');
  const genCount = doc.querySelectorAll('#gen-body .q').length;
  const sb = win.__api.stepBar();

  if (MODE === 'live') {
    ok('顶部 step1=完成，2/3/4 仍「待命」',
      sb[1] === '完成' && sb[2] === '待命' && sb[3] === '待命' && sb[4] === '待命', JSON.stringify(sb));
    const num1 = (doc.querySelector('.mp-step[data-step="1"] .mp-step-num') || {}).textContent;
    const num2 = (doc.querySelector('.mp-step[data-step="2"] .mp-step-num') || {}).textContent;
    const cls1 = doc.querySelector('.mp-step[data-step="1"]').className;
    ok('完成后 step1 圆圈显示 ✓（不再是步骤号）', num1 === '✓', 'step1=' + num1);
    ok('未执行步骤仍显示步骤号', num2 === '2', 'step2=' + num2);
    ok('完成态只用 class 表达（is-completed + is-current）',
      /is-completed/.test(cls1) && /is-current/.test(cls1) && !/is-active|is-error/.test(cls1), cls1);
    ok('任务输入被后端 brief 使用（textarea 保留原值）', win.document.getElementById('task-input').value.length > 8);
    ok('树行数 = 场景+5类别+14维度 = 20', treeRows === 20, 'rows=' + treeRows);
    ok('矩阵格数 = 14 × 13 = 182', cells === 182, 'cells=' + cells);
    ok('点亮格数 = 后端 covered', lit === V.matrix.covered, `lit=${lit} covered=${V.matrix.covered}`);
    ok('r4 计数分母 = 182', /\/182$/.test(r4count), r4count);
    const activeDims = V.matrix.rows.filter(r => r.active).length;
    ok('r3 路径计数 = 已覆盖维度/总维度',
      r3count === `路径 ${activeDims}/14`, `${r3count}（已覆盖 ${activeDims}/14）`);
    ok('r3 状态文案与已覆盖维度一致',
      text('#r3-status') === `已覆盖 ${activeDims}/14`, text('#r3-status'));
    const doneRows = doc.querySelectorAll('#tree .trow.done[data-role="dim"]').length;
    ok('树中已完成的维度行数 = 已覆盖维度数',
      doneRows === activeDims, `done=${doneRows} active=${activeDims}`);
    ok('r4 计数为 覆盖格 lit/182', r4count === `覆盖格 ${lit}/182`, r4count);
    const exp = V.metrics.map(m => m.type === 'frac' ? `${m.value[0]}/${m.value[1]}`
      : m.type === 'pct' ? m.value + '%' : m.type === 'dec' ? Number(m.value).toFixed(3) : String(m.value));
    ok('r5 六项与后端 metrics 一致', exp.every((v, i) => String(r5v[i]).trim() === v),
      `页面=${r5v.join('|')} 后端=${exp.join('|')}`);
    ok('r5 矩阵覆盖与矩阵点亮数自洽', String(r5v[3]).trim() === `${lit}/182`, r5v[3]);
    ok('r6 行数 = 后端 params 行数', r6rows === V.params.length, `rows=${r6rows} params=${V.params.length}`);
    ok('r3 泛化 query = 任务+变体', genCount === V.queries.length, `console=${genCount} queries=${V.queries.length}`);
    const ghN = (doc.querySelector('.gen-console .gh .n') || {}).textContent || '';
    ok('query console 标题两行：标签 + 真实条数',
      /已泛化query/.test(text('.gen-console .gh')) && ghN === V.queries.length + ' 条',
      `label="${text('.gen-console .gh').replace(ghN, '').trim()}" n="${ghN}"`);
    const mi = V.matrix.caps13.findIndex(c => c.cap === V.matrix.missing[0]);
    ok('智能体不支持的能力列全行不点亮', V.matrix.rows.every(r => (r.tiers[mi] || 0) === 0),
      'missing=' + V.matrix.missing.join(','));
    ok('r6 关联维度均命中真实维度', V.params.every(p => V.tree.dims.some(d => d.name === p.dim)));
    ok('树锚点数量 = 14', doc.querySelectorAll('#tree .trow .ptag').length === 14,
      'ptag=' + doc.querySelectorAll('#tree .trow .ptag').length);
    const tags = win.__api.sourceTags();
    ok('step1 的 LLM 来源 = 前端上传的智能体配置（前端传什么就用什么）',
      V.engine === 'llm+mock' && /agent-config/.test(String(V.llm_source || '')),
      `engine=${V.engine} source=${V.llm_source} model=${V.llm_model}`);
    ok('上传的端点不可达 → 该步降级，四个区域标「部分 mock」（不冒充实测）',
      V.data_source === 'mixed' && ['r3', 'r4', 'r5', 'r6'].every(k => tags[k] === '部分 mock'),
      JSON.stringify(tags));
    ok('降级在运行日志里显式标注 [降级]（可观测，不静默）',
      (V.logs || []).some(l => /\[降级\]/.test(String(l.text || ''))),
      ((V.logs || []).filter(l => /降级/.test(String(l.text || ''))).length) + ' 条');
    ok('运行后顶部徽标反映本次引擎（LLM 降级 → 部分 mock）',
      text('#mp-bar-meta-text') === '部分 mock', text('#mp-bar-meta-text'));
    const tips = win.__api.srcTips();
    ok('r3/r4 tooltip 写清「哪部分是真结构、哪部分是本次生成」',
      /场景泛化矩阵/.test(tips.r3) && /covered_dimensions/.test(tips.r3)
      && /29 个 L2/.test(tips.r4) && /能力缺口/.test(tips.r4),
      JSON.stringify(tips).slice(0, 90));
    ok('生成台 query 悬停可见全文（title = 完整指令）',
      win.__api.genSizing().qTitle === (((V.queries || [])[0] || {}).text || ''),
      'title=' + win.__api.genSizing().qTitle.slice(0, 36));
    const ghosts = win.__api.ghosts();
    ok('幽灵文字来自真实事件（不再是固定装饰文案）',
      ghosts.length > 0 && !ghosts.some(g => /App 名称识别/.test(g))
      && ghosts.some(g => /已覆盖|任务 |校验 |进行中/.test(g)),
      ghosts.slice(0, 4).join(' | '));
  } else {
    ok('演示态树行数 = 演示结构', treeRows > 0, 'rows=' + treeRows);
    ok('演示态矩阵格数 = 7 × 13 = 91', cells === 91, 'cells=' + cells);
    ok('演示态 r5 结算为演示值', r5v[0] === '10' && r5v[3] === '59/182', r5v.join('|'));
    ok('演示态 step1 = 完成', sb[1] === '完成', JSON.stringify(sb));
    ok('演示态 r6 明细 6 行', r6rows === 6, 'rows=' + r6rows);
    const ghD = (doc.querySelector('.gen-console .gh .n') || {}).textContent || '';
    ok('演示态生成台标题数量行 = 100 条', ghD === '100 条', ghD);
  }

  if (MODE === 'live') {
    console.log('\n== 换场景重跑（验证场景选择真的生效）==');
    const sel2 = doc.getElementById('run-scene');
    sel2.value = '本地生活';
    sel2.dispatchEvent(new win.Event('change'));
    await sleep(1500);
    const rp2 = win.__api.runParams();
    ok('切换场景后选中「本地生活」', rp2.scene === '本地生活', rp2.scene);
    const t2 = Date.now();
    win.document.getElementById('btn-run').click();
    await waitFor('第二次运行完成', () => {
      const v = win.__api.view();
      return win.__demo.phase === 'done' && v && v.tree && v.tree.scene === '本地生活';
    }, 240000);
    const V2 = JSON.parse(JSON.stringify(win.__api.view()));
    const cells2 = win.__api.matrixCells();
    ok('第二次运行确实用了新场景', V2.tree.scene === '本地生活', V2.tree.scene);
    ok('新场景矩阵格数 = 该场景维度数 × 13',
      cells2 === V2.tree.dims.length * 13, `cells=${cells2} dims=${V2.tree.dims.length}`);
    ok('新场景点亮数自洽（lit = covered）',
      win.__api.litCells() === V2.matrix.covered,
      `lit=${win.__api.litCells()} covered=${V2.matrix.covered}`);
    ok('换场景后仍无 JS 错误', ((win.__errs || []).length === 0), `耗时 ${((Date.now() - t2) / 1000).toFixed(1)}s`);
  }

  console.log('\n== 错误检查 ==');
  const errs = (win.__errs || []).filter(e => !/favicon|Failed to load resource|Not implemented|Could not parse CSS/.test(String(e)));
  ok('无未捕获 JS 错误', errs.length === 0, errs.slice(0, 3).join(' | '));

  dom.window.close();
  console.log('\n' + '='.repeat(56));
  console.log(`  前端 ${MODE} 验收: ${PASS} passed, ${FAIL} failed`);
  console.log('='.repeat(56));
  return FAIL ? 1 : 0;
}

main().then(c => process.exit(c)).catch(e => { console.error('\n[e2e] 失败:', e.message); process.exit(1); });
