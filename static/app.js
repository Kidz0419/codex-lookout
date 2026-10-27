'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { mode: 'live', filter: 'all', query: '', snapshot: null, selectedId: null, expandedTitleId: null, error: null, refreshing: false, controller: null, requestNumber: 0, lastSuccess: null };
  const phaseLabels = { model: '模型处理中', tool: '工具执行中', waiting: '等待中', idle: '已结束', unknown: '暂无法确定' };
  const confidenceLabels = { observed: '已观察', inferred: '推断', unknown: '未知' };
  const statusLabels = { running: '进行中', completed: '已完成', failed: '失败', interrupted: '已中断', unknown: '状态未知' };
  const severityNames = new Set(['ok', 'info', 'warning', 'error']);
  const numberFormatter = new Intl.NumberFormat('zh-CN');
  const timeFormatter = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const fullTimeFormatter = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function time(value, full = false) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? (full ? fullTimeFormatter : timeFormatter).format(date) : '—';
  }
  function duration(value, compact = false) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '—';
    const seconds = Math.floor(value);
    if (seconds < 60) return `${seconds} 秒`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return compact ? `${minutes} 分 ${seconds % 60} 秒` : `${minutes} 分 ${seconds % 60} 秒`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} 时 ${minutes % 60} 分`;
    return `${Math.floor(hours / 24)} 天 ${hours % 24} 时`;
  }
  function number(value) { return typeof value === 'number' && Number.isFinite(value) ? numberFormatter.format(value) : '—'; }
  function severity(task) {
    if (task.health) return { active: 'ok', watch: 'warning', error: 'error', waiting: 'info', unknown: 'info', idle: 'info' }[task.health.level] || 'info';
    return severityNames.has(task.diagnosis?.severity) ? task.diagnosis.severity : 'info';
  }
  function isAttention(task) {
    if (task.health) return ['watch', 'error'].includes(task.health.level);
    return ['warning', 'error'].includes(severity(task)) || ['unknown', 'failed'].includes(task.status) || ['long_tool', 'approval_required', 'needs_input', 'needs_attention'].includes(task.diagnosis?.code);
  }
  function healthLabel(task) { return task.health?.label || task.diagnosis?.label || statusLabels[task.status] || '状态未知'; }
  function stageLabel(task) { return task.stage?.label || phaseLabels[task.phase] || '暂无法确定'; }
  function progressSilence(task) { return task.health ? task.health.silenceSeconds : task.silenceSeconds; }
  function isEnded(task) { return ['completed', 'failed', 'interrupted'].includes(task.status); }
  function projectName(task) {
    if (!task.cwd) return '未记录项目';
    const pieces = String(task.cwd).replace(/\/$/, '').split('/');
    return pieces.slice(-2).join('/') || String(task.cwd);
  }
  function rememberSelection() {
    try { localStorage.setItem(`codex-lookout:selected:${state.mode}`, state.selectedId || ''); } catch (_) { /* Storage is optional. */ }
  }
  function readSelection() {
    try { return localStorage.getItem(`codex-lookout:selected:${state.mode}`) || null; } catch (_) { return null; }
  }
  function announce(message) { $('announcement').textContent = message; }
  function allTasks() { return Array.isArray(state.snapshot?.tasks) ? state.snapshot.tasks : []; }
  function filteredTasks() {
    return allTasks().filter((task) => {
      const statusMatch = state.filter === 'all' || (state.filter === 'running' && task.status === 'running') || (state.filter === 'attention' && isAttention(task)) || (state.filter === 'ended' && isEnded(task));
      const text = [task.title, task.cwd, task.id].filter(Boolean).join(' ').toLocaleLowerCase();
      return statusMatch && (!state.query || text.includes(state.query));
    }).sort((a, b) => {
      const rank = (task) => task.status === 'running' ? (isAttention(task) ? 0 : 1) : isAttention(task) ? 2 : isEnded(task) ? 4 : 3;
      return rank(a) - rank(b) || (Date.parse(b.turnStartedAt) || 0) - (Date.parse(a.turnStartedAt) || 0) || String(a.id).localeCompare(String(b.id));
    });
  }
  function renderCounts() {
    const tasks = allTasks();
    $('count-all').textContent = state.snapshot ? tasks.length : '—';
    $('count-running').textContent = state.snapshot ? tasks.filter((task) => task.status === 'running').length : '—';
    $('count-attention').textContent = state.snapshot ? tasks.filter(isAttention).length : '—';
    $('count-ended').textContent = state.snapshot ? tasks.filter(isEnded).length : '—';
  }
  function renderList() {
    const tasks = filteredTasks();
    if (state.snapshot && !tasks.some((task) => task.id === state.selectedId)) {
      state.selectedId = tasks[0]?.id || null;
      rememberSelection();
    }
    const focusedId = document.activeElement?.dataset?.taskId;
    const fragment = document.createDocumentFragment();
    tasks.forEach((task) => {
      const row = element('tr', `task-row${state.selectedId === task.id ? ' is-selected' : ''}`);
      row.dataset.taskId = task.id;
      const titleCell = element('td');
      const select = element('button', 'task-select');
      select.type = 'button';
      select.dataset.taskId = task.id;
      select.setAttribute('aria-pressed', String(task.id === state.selectedId));
      select.setAttribute('aria-label', `查看任务：${task.title || '未命名任务'}`);
      select.append(element('span', 'task-name', task.title || '未命名任务'), element('span', 'task-project', projectName(task)));
      select.title = task.cwd || task.title || '未命名任务';
      titleCell.append(select);
      const statusCell = element('td');
      statusCell.append(element('span', `status-label severity-${severity(task)}`, healthLabel(task)));
      const secondary = task.stage?.label || task.currentTool?.name || stageLabel(task);
      statusCell.append(element('span', 'status-secondary', secondary));
      statusCell.title = task.health?.summary || task.diagnosis?.summary || '';
      const elapsedCell = element('td', 'row-duration numeric', duration(task.elapsedSeconds, true));
      const silence = progressSilence(task);
      const silenceCell = element('td', `row-duration numeric${task.status === 'running' && silence >= 180 ? ' is-long' : ''}`, duration(silence, true));
      silenceCell.title = task.health ? (typeof silence === 'number' ? '距最近可确认的进展；错误和重试不计为进展' : '尚未观察到本轮进展') : '距最近事件记录';
      row.append(titleCell, statusCell, elapsedCell, silenceCell);
      row.addEventListener('click', () => selectTask(task.id));
      fragment.append(row);
    });
    $('task-rows').replaceChildren(fragment);
    const silenceHeader = $('task-rows').closest('table')?.querySelector('thead th:last-child');
    if (silenceHeader) silenceHeader.textContent = allTasks().some((task) => task.health) ? '距最近进展' : '距新事件';
    if (focusedId) Array.from($('task-rows').querySelectorAll('button')).find((button) => button.dataset.taskId === focusedId)?.focus({ preventScroll: true });
    $('list-empty').hidden = tasks.length > 0;
    $('clear-search').hidden = !state.query && state.filter === 'all';
    if (!state.snapshot) {
      $('empty-title').textContent = state.error ? '暂时无法读取任务' : '正在读取本机任务';
      $('empty-description').textContent = state.error ? '请确认本地监测服务仍在运行，然后点击刷新重试。' : '首次读取可能需要几秒钟。';
    } else if (state.query || state.filter !== 'all') {
      $('empty-title').textContent = '没有符合条件的任务';
      $('empty-description').textContent = '试试其他名称，或清除筛选查看全部任务。';
    } else {
      $('empty-title').textContent = '尚未发现本机任务';
      $('empty-description').textContent = '在 Codex 中开始一个任务。新的本机记录出现后会自动显示在这里。';
    }
    $('visible-count').textContent = state.snapshot ? `显示 ${tasks.length} / ${allTasks().length} 项任务` : '等待本机记录';
    $('task-scope').textContent = state.mode === 'demo' ? '合成案例 · 按状态排序' : `最近 ${state.snapshot?.taskLimit || 80} 个未归档本机任务`;
    renderDetail();
  }
  function selectTask(id) {
    if (id === state.selectedId) return;
    state.selectedId = id;
    rememberSelection();
    renderList();
    const task = allTasks().find((item) => item.id === id);
    if (task) announce(`已选择${task.title || '未命名任务'}，${healthLabel(task)}，${stageLabel(task)}`);
  }
  function renderDetail() {
    const task = allTasks().find((item) => item.id === state.selectedId);
    $('detail-content').hidden = !task;
    $('inspector-empty').hidden = Boolean(task);
    $('detail-source').textContent = state.mode === 'demo' ? '合成示例' : '本机记录';
    if (!task) return;
    $('detail-title').textContent = task.title || '未命名任务';
    const hasLongTitle = String(task.title || '').length > 60;
    const isExpanded = state.expandedTitleId === task.id;
    $('detail-title').classList.toggle('is-collapsed', hasLongTitle && !isExpanded);
    $('expand-title').hidden = !hasLongTitle;
    $('expand-title').textContent = isExpanded ? '收起完整标题' : '展开完整标题';
    $('expand-title').setAttribute('aria-expanded', String(isExpanded));
    $('detail-project').textContent = task.cwd || '未记录项目路径';
    $('diagnosis').className = `diagnosis severity-${severity(task)}`;
    $('diagnosis-label').textContent = healthLabel(task);
    $('diagnosis-confidence').textContent = task.health ? '健康状态' : confidenceLabels[task.diagnosis?.confidence] || '未知';
    $('diagnosis-summary').textContent = task.health?.summary || task.diagnosis?.summary || '当前记录不足以判断任务是否仍在运行。';
    $('diagnosis-action').textContent = task.diagnosis?.action || '回到 Codex 查看当前任务状态。';
    $('fact-phase').textContent = stageLabel(task);
    $('fact-phase').title = task.stage ? `${confidenceLabels[task.stage.evidence] || '未知'}${task.stage.observedAt ? ` · ${time(task.stage.observedAt, true)}` : ''}` : '';
    $('fact-elapsed').textContent = duration(task.elapsedSeconds);
    $('fact-silence').textContent = duration(progressSilence(task));
    $('fact-silence').previousElementSibling.textContent = task.health ? '距最近进展' : '距新事件';
    $('fact-silence').title = task.health ? (task.health.lastProgressAt ? `最近进展 ${time(task.health.lastProgressAt, true)}；错误和重试不计为进展` : '尚未观察到本轮进展') : '';
    $('fact-start').textContent = time(task.turnStartedAt, true);
    $('fact-tool-row').hidden = !task.currentTool;
    $('fact-tool-age-row').hidden = !task.currentTool;
    $('fact-tool').textContent = task.currentTool?.name || '—';
    $('fact-tool-age').textContent = duration(task.currentTool?.elapsedSeconds);
    $('fact-model').textContent = task.model || '未记录';
    $('token-output').textContent = number(task.tokens?.output);
    $('token-reasoning').textContent = number(task.tokens?.reasoning);
    $('token-total').textContent = number(task.tokens?.total);
    $('token-heading').textContent = task.tokens?.scope === 'session' ? '会话 Token 用量' : '本轮 Token 用量';
    $('token-note').textContent = `实时速度暂不可测：${task.tokens?.rateLabel || '缺少逐 token 时间戳'}。采样用量不能换算成实时输出速度。`;
    $('token-sample').textContent = task.tokens?.lastSampleAt ? `最近采样 ${time(task.tokens.lastSampleAt, true)}` : '尚未读到 Token 采样';
    $('coverage-note').textContent = task.coverage?.note || '当前任务的数据覆盖范围未知。';
    $('coverage-indicator').classList.toggle('is-partial', task.coverage?.complete !== true);
    const networkErrors = Array.isArray(task.networkErrors) ? task.networkErrors : [];
    $('network-section').hidden = networkErrors.length === 0;
    $('network-count').textContent = `${networkErrors.length} 条`;
    $('network-list').replaceChildren(...networkErrors.slice(-4).reverse().map((event) => {
      const item = element('li', 'event-warning');
      const stamp = element('time', '', time(event.at));
      if (event.at) stamp.dateTime = event.at;
      stamp.title = time(event.at, true);
      const content = element('div', 'event-content');
      content.append(element('p', 'event-label', event.label || '连接异常记录'));
      item.append(stamp, content);
      return item;
    }));
    const events = (Array.isArray(task.events) ? task.events : []).slice().sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0)).slice(0, 12);
    const fragment = document.createDocumentFragment();
    events.forEach((event) => {
      const item = element('li', /error|retry|fail/i.test(event.kind || '') ? 'event-warning' : '');
      const stamp = element('time', '', time(event.at));
      if (event.at) stamp.dateTime = event.at;
      stamp.title = time(event.at, true);
      const content = element('div', 'event-content');
      content.append(element('p', 'event-label', event.label || event.kind || '事件'));
      if (event.detail) content.append(element('p', 'event-detail', event.detail));
      if (typeof event.durationSeconds === 'number') content.append(element('p', 'event-detail', `持续 ${duration(event.durationSeconds)}`));
      item.append(stamp, content);
      fragment.append(item);
    });
    $('event-list').replaceChildren(fragment);
    $('event-count').textContent = events.length ? `${events.length} 条 · 最新在前` : '暂无记录';
    $('events-empty').hidden = events.length > 0;
    const validId = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(task.id || '');
    $('open-task').hidden = state.mode !== 'live' || !validId;
    if (state.mode === 'live' && validId) $('open-task').href = `codex://threads/${task.id}`;
    else $('open-task').removeAttribute('href');
  }
  function renderSources() {
    const sources = Array.isArray(state.snapshot?.sources) ? state.snapshot.sources : [];
    const available = sources.filter((source) => source.available).length;
    $('source-summary').textContent = state.mode === 'demo' ? '演示数据 · 非真实任务' : sources.length ? `本机数据源 ${available} / ${sources.length} 可用` : '等待数据源';
    const fragment = document.createDocumentFragment();
    sources.forEach((source) => {
      const item = element('li');
      item.append(element('strong', '', `${source.name || '数据源'} · ${source.available ? '可用' : '未读取'}`));
      if (source.note) item.append(document.createTextNode(`。${source.note}`));
      fragment.append(item);
    });
    if (!sources.length) fragment.append(element('li', '', '尚未连接到本机采集器。'));
    $('source-list').replaceChildren(fragment);
    const limitations = Array.isArray(state.snapshot?.limitations) ? state.snapshot.limitations : ['无新事件只能提示观察，不能直接证明卡死。', '缺少逐 token 时间戳时，不显示估算输出速度。'];
    $('limitations-list').replaceChildren(...limitations.map((note) => element('li', '', note)));
  }
  function renderSync() {
    const age = state.snapshot?.generatedAt ? Math.max(0, (Date.now() - Date.parse(state.snapshot.generatedAt)) / 1000) : null;
    const stale = state.snapshot && (!Number.isFinite(age) || age > 15);
    const collectorError = state.snapshot?.collectorError;
    const error = state.error || collectorError;
    $('sync-status').className = `sync-status ${error ? 'is-error' : stale ? 'is-warning' : state.snapshot ? 'is-live' : ''}`;
    $('sync-title').textContent = error ? '数据更新中断' : stale ? '快照已过期' : state.mode === 'demo' ? '演示案例' : state.snapshot ? '本机数据已连接' : '正在连接本机';
    $('sync-detail').textContent = state.snapshot ? `同步 ${time(state.snapshot.generatedAt)} · 每 3 秒刷新` : '每 3 秒自动重试';
    $('data-alert').hidden = !error && !stale;
    if (error) $('data-alert').textContent = `${error}${state.snapshot ? ' 当前保留上一次快照，任务状态可能已变化。' : ''} 将自动重试，也可点击刷新。`;
    else if (stale) $('data-alert').textContent = `最近快照已是 ${duration(age)} 前，当前任务状态可能已变化。请确认本地监测服务仍在运行。`;
  }
  async function refresh(manual = false) {
    if (state.refreshing) return;
    const requestNumber = ++state.requestNumber;
    const mode = state.mode;
    state.refreshing = true;
    $('refresh-button').disabled = true;
    $('refresh-label').textContent = '读取中';
    const controller = new AbortController();
    state.controller = controller;
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(mode === 'demo' ? '/api/demo' : '/api/snapshot', { signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(response.status === 503 ? '采集器暂未准备好。' : `本地服务返回错误（${response.status}）。`);
      const snapshot = await response.json();
      if (!snapshot || !Array.isArray(snapshot.tasks) || typeof snapshot.generatedAt !== 'string' || Boolean(snapshot.demo) !== (mode === 'demo')) throw new Error('收到的数据格式或来源不正确。');
      if (requestNumber !== state.requestNumber || state.mode !== mode) return;
      state.snapshot = snapshot;
      state.lastSuccess = Date.now();
      state.error = null;
      renderCounts();
      renderList();
      renderSources();
      if (manual) announce(`已刷新，共 ${snapshot.tasks.length} 项任务。`);
    } catch (error) {
      if (requestNumber !== state.requestNumber || state.mode !== mode) return;
      state.error = error.name === 'AbortError' ? '读取本地服务超时。' : error instanceof TypeError ? '无法连接本地监测服务。' : error.message || '读取任务失败。';
      if (!state.snapshot) renderList();
      if (manual) announce(state.error);
    } finally {
      window.clearTimeout(timeout);
      if (requestNumber === state.requestNumber) {
        state.refreshing = false;
        state.controller = null;
        $('refresh-button').disabled = false;
        $('refresh-label').textContent = '刷新';
        renderSync();
      }
    }
  }
  function switchMode(mode) {
    if (state.mode === mode) return;
    state.controller?.abort();
    state.requestNumber += 1;
    state.refreshing = false;
    state.mode = mode;
    state.snapshot = null;
    state.error = null;
    state.lastSuccess = null;
    state.selectedId = readSelection();
    $('demo-banner').hidden = mode !== 'demo';
    ['live', 'demo'].forEach((name) => {
      $(`${name}-mode`).classList.toggle('is-active', mode === name);
      $(`${name}-mode`).setAttribute('aria-pressed', String(mode === name));
    });
    renderCounts(); renderList(); renderSources(); renderSync();
    refresh();
    announce(mode === 'demo' ? '已切换至合成演示案例。' : '已切换至本机实时数据。');
  }
  function setFilter(filter) {
    state.filter = filter;
    document.querySelectorAll('[data-filter]').forEach((button) => {
      const active = button.dataset.filter === filter;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderList();
  }
  $('refresh-button').addEventListener('click', () => refresh(true));
  $('live-mode').addEventListener('click', () => switchMode('live'));
  $('demo-mode').addEventListener('click', () => switchMode('demo'));
  $('exit-demo').addEventListener('click', () => switchMode('live'));
  $('expand-title').addEventListener('click', () => {
    state.expandedTitleId = state.expandedTitleId === state.selectedId ? null : state.selectedId;
    renderDetail();
  });
  document.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => setFilter(button.dataset.filter)));
  $('search-input').addEventListener('input', (event) => { state.query = event.target.value.trim().toLocaleLowerCase(); renderList(); });
  $('clear-search').addEventListener('click', () => { $('search-input').value = ''; state.query = ''; setFilter('all'); $('search-input').focus(); });
  $('copy-id').addEventListener('click', async () => {
    const id = state.selectedId;
    if (!id) return;
    try {
      await navigator.clipboard.writeText(id);
      $('copy-id').textContent = '已复制';
      announce('任务 ID 已复制。');
      window.setTimeout(() => { $('copy-id').textContent = '复制任务 ID'; }, 1800);
    } catch (_) {
      $('copy-id').textContent = '复制失败，请重试';
      announce('浏览器未允许复制，请重试。');
      window.setTimeout(() => { $('copy-id').textContent = '复制任务 ID'; }, 2500);
    }
  });
  document.addEventListener('click', (event) => {
    if ($('source-details').open && !$('source-details').contains(event.target)) $('source-details').open = false;
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') $('source-details').open = false; });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  state.selectedId = readSelection();
  refresh();
  window.setInterval(() => { if (!document.hidden) refresh(); }, 3000);
  window.setInterval(renderSync, 1000);
})();
