const appData = window.APP_DATA || { tasks: [], competencias: [] };
const uiState = {
  formSubtasks: [],
  editingSubtask: null,
  replicateTaskId: null,
  currentTaskCompletion: null,
};

function byId(id) {
  return document.getElementById(id);
}

function taskById(id) {
  return (appData.tasks || []).find((task) => Number(task.id) === Number(id));
}

function subtaskById(taskId, subtaskId) {
  const task = taskById(taskId);
  if (!task) return null;
  return (task.subtarefas || []).find((subtask) => Number(subtask.id) === Number(subtaskId));
}

function fieldValue(id) {
  const el = byId(id);
  return el ? el.value.trim() : '';
}

function setFieldValue(id, value) {
  const el = byId(id);
  if (el) el.value = value || '';
}

function nullableDate(value) {
  return value || null;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function withParams(changes) {
  const params = new URLSearchParams(window.location.search);
  Object.entries(changes).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  });
  return `${window.location.pathname}?${params.toString()}`;
}

function goWithParams(changes) {
  window.location.href = withParams(changes);
}

function resetTaskForm() {
  setFieldValue('edit-id', '');
  setFieldValue('f-titulo', '');
  setFieldValue('f-categoria', byId('f-categoria')?.options[0]?.value || '');
  setFieldValue('f-prioridade', 'normal');
  setFieldValue('f-status', 'pendente');
  setFieldValue('f-competencia', appData.dashMonth || (appData.competencias || [])[0] || '');
  setFieldValue('f-liberacao', '');
  setFieldValue('f-vencimento', '');
  setFieldValue('f-cliente', '');
  setFieldValue('f-responsavel', '');
  setFieldValue('f-obs', '');
  setTipo('rotina');
  uiState.formSubtasks = [];
  uiState.currentTaskCompletion = null;
  renderFormSubtasks();
  const title = byId('form-title');
  if (title) title.textContent = '＋ Nova obrigação';
}

function toggleForm() {
  const el = byId('form-wrap');
  if (!el) return;
  if (el.classList.contains('visible')) {
    closeForm();
    return;
  }
  resetTaskForm();
  el.classList.add('visible');
  byId('f-titulo')?.focus();
}

function closeForm() {
  byId('form-wrap')?.classList.remove('visible');
}

function setTipo(value) {
  setFieldValue('f-tipo', value);
  const rotina = byId('tipo-btn-rotina');
  const extra = byId('tipo-btn-extraordinaria');
  if (rotina) rotina.className = value === 'rotina' ? 'active-rotina' : '';
  if (extra) extra.className = value === 'extraordinaria' ? 'active-extraordinaria' : '';
}

function toggleStLibNA(id, checkbox) {
  const el = byId(id);
  if (!el) return;
  el.disabled = checkbox.checked;
  if (checkbox.checked) el.value = '';
}

function renderFormSubtasks() {
  const list = byId('subtask-list-form');
  if (!list) return;
  list.innerHTML = '';

  uiState.formSubtasks.forEach((subtask, index) => {
    const item = document.createElement('div');
    item.className = 'subtask-form-item';
    const lib = subtask.liberacao ? ` · Lib: ${subtask.liberacao === 'NA' ? 'N/A' : subtask.liberacao}` : '';
    const venc = subtask.vencimento ? ` · Venc: ${subtask.vencimento}` : '';
    const resp = subtask.responsavel ? ` · ${subtask.responsavel}` : '';

    // Montado com createElement/textContent em vez de innerHTML: o titulo e a
    // responsavel sao texto digitado pelo usuario. Com innerHTML, um titulo
    // como <img onerror=...> viraria HTML executavel (XSS armazenado).
    const check = document.createElement('div');
    check.className = 'st-check-preview';

    const label = document.createElement('span');
    label.textContent = `${subtask.titulo}${resp}${lib}${venc}`;

    const remove = document.createElement('button');
    remove.className = 'btn-remove-st';
    remove.type = 'button';
    remove.textContent = '×';
    remove.addEventListener('click', () => removeSubtaskFromForm(index));

    item.append(check, label, remove);
    list.appendChild(item);
  });
}

function addSubtaskToForm() {
  const titulo = fieldValue('new-st-titulo');
  if (!titulo) {
    alert('Informe a descrição da subtarefa.');
    return;
  }

  const libNa = byId('new-st-lib-na')?.checked;
  uiState.formSubtasks.push({
    titulo,
    responsavel: fieldValue('new-st-resp'),
    concluida: false,
    liberacao: libNa ? 'NA' : fieldValue('new-st-lib'),
    vencimento: nullableDate(fieldValue('new-st-venc')),
    data_conclusao: '',
  });

  setFieldValue('new-st-titulo', '');
  setFieldValue('new-st-resp', '');
  setFieldValue('new-st-lib', '');
  setFieldValue('new-st-venc', '');
  const checkbox = byId('new-st-lib-na');
  if (checkbox) checkbox.checked = false;
  const lib = byId('new-st-lib');
  if (lib) lib.disabled = false;
  renderFormSubtasks();
}

function removeSubtaskFromForm(index) {
  uiState.formSubtasks.splice(index, 1);
  renderFormSubtasks();
}

function collectTaskPayload() {
  const titulo = fieldValue('f-titulo');
  if (!titulo) {
    alert('Informe o título da obrigação.');
    return null;
  }

  const status = fieldValue('f-status');
  return {
    titulo,
    categoria: fieldValue('f-categoria'),
    tipo: fieldValue('f-tipo') || 'rotina',
    prioridade: fieldValue('f-prioridade') || 'normal',
    status,
    competencia: fieldValue('f-competencia') || appData.dashMonth || '',
    liberacao: nullableDate(fieldValue('f-liberacao')),
    vencimento: nullableDate(fieldValue('f-vencimento')),
    data_conclusao: status === 'concluida' ? (uiState.currentTaskCompletion || todayIso()) : null,
    cliente: fieldValue('f-cliente'),
    responsavel: fieldValue('f-responsavel'),
    obs: fieldValue('f-obs'),
    subtarefas: uiState.formSubtasks.map((subtask) => ({
      titulo: subtask.titulo,
      responsavel: subtask.responsavel || '',
      concluida: Boolean(subtask.concluida),
      liberacao: subtask.liberacao || '',
      vencimento: nullableDate(subtask.vencimento || ''),
      data_conclusao: subtask.data_conclusao || '',
    })),
  };
}

async function saveTask() {
  const payload = collectTaskPayload();
  if (!payload) return;

  const id = fieldValue('edit-id');
  const method = id ? 'PUT' : 'POST';
  const url = id ? `/api/tasks/${id}` : '/api/tasks';
  const result = await apiCall(url, method, payload);
  if (result) {
    flash('✓ Salvo');
    reload();
  }
}

function editTask(id) {
  const task = taskById(id);
  if (!task) return;

  setFieldValue('edit-id', task.id);
  setFieldValue('f-titulo', task.titulo);
  setFieldValue('f-categoria', task.categoria);
  setFieldValue('f-prioridade', task.prioridade);
  setFieldValue('f-status', task.status);
  setFieldValue('f-competencia', task.competencia);
  setFieldValue('f-liberacao', task.liberacao);
  setFieldValue('f-vencimento', task.vencimento);
  setFieldValue('f-cliente', task.cliente);
  setFieldValue('f-responsavel', task.responsavel);
  setFieldValue('f-obs', task.obs);
  setTipo(task.tipo);
  uiState.currentTaskCompletion = task.data_conclusao || null;
  uiState.formSubtasks = (task.subtarefas || []).map((subtask) => ({ ...subtask }));
  renderFormSubtasks();

  const title = byId('form-title');
  if (title) title.textContent = '✏️ Editar obrigação';
  byId('form-wrap')?.classList.add('visible');
  window.scrollTo({ top: byId('form-wrap').offsetTop - 12, behavior: 'smooth' });
}

async function deleteTask(id) {
  if (!confirm('Remover esta obrigação?')) return;
  const result = await apiCall(`/api/tasks/${id}`, 'DELETE');
  if (result) {
    flash('Obrigação removida');
    reload();
  }
}

async function changeStatus(id, status) {
  const result = await apiCall(`/api/tasks/${id}/status`, 'POST', { status });
  if (result) {
    flash('Status atualizado');
    reload();
  }
}

async function setTaskConclusion(id, value) {
  const result = await apiCall(`/api/tasks/${id}/conclusao`, 'POST', { value: value || null });
  if (result) {
    flash('Conclusão atualizada');
    reload();
  }
}

const OPEN_PANELS_KEY = 'gc-open-subtask-panels';

function getOpenPanels() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(OPEN_PANELS_KEY) || '[]').map(Number));
  } catch (e) {
    return new Set();
  }
}

function saveOpenPanels(ids) {
  try {
    sessionStorage.setItem(OPEN_PANELS_KEY, JSON.stringify([...ids]));
  } catch (e) { /* sessionStorage indisponível */ }
}

function setPanelOpen(taskId, open) {
  const ids = getOpenPanels();
  if (open) {
    ids.add(Number(taskId));
  } else {
    ids.delete(Number(taskId));
  }
  saveOpenPanels(ids);
}

function restoreOpenSubtaskPanels() {
  const stillOpen = new Set();
  getOpenPanels().forEach((id) => {
    const panel = byId(`subtasks-${id}`);
    if (panel) {
      panel.classList.add('open');
      stillOpen.add(Number(id));
    }
  });
  saveOpenPanels(stillOpen);
}

function restoreScrollPosition() {
  let saved = null;
  try {
    saved = sessionStorage.getItem('gc-scroll-y');
    sessionStorage.removeItem('gc-scroll-y');
  } catch (e) { /* sessionStorage indisponível */ }
  if (saved !== null) window.scrollTo(0, Number(saved));
}

function setPendingFlash(message) {
  try {
    sessionStorage.setItem('gc-pending-flash', message);
  } catch (e) { /* sessionStorage indisponível */ }
}

function showPendingFlash() {
  let message = null;
  try {
    message = sessionStorage.getItem('gc-pending-flash');
    sessionStorage.removeItem('gc-pending-flash');
  } catch (e) { /* sessionStorage indisponível */ }
  if (message) flash(message);
}

function toggleSubtasks(id) {
  const panel = byId(`subtasks-${id}`);
  if (!panel) return;
  panel.classList.toggle('open');
  setPanelOpen(id, panel.classList.contains('open'));
}

async function toggleSubtask(taskId, subtaskId) {
  const result = await apiCall(`/api/tasks/${taskId}/subtasks/${subtaskId}/toggle`, 'POST');
  if (result) {
    setPanelOpen(taskId, true);
    flash('Subtarefa atualizada');
    reload();
  }
}

async function addInlineSubtask(taskId) {
  const titulo = fieldValue(`inline-st-title-${taskId}`);
  if (!titulo) {
    alert('Informe a descrição da subtarefa.');
    return;
  }

  const result = await apiCall(`/api/tasks/${taskId}/subtasks`, 'POST', {
    titulo,
    responsavel: fieldValue(`inline-st-resp-${taskId}`),
    concluida: false,
    liberacao: '',
    vencimento: nullableDate(fieldValue(`inline-st-venc-${taskId}`)),
    data_conclusao: '',
  });
  if (result) {
    setPanelOpen(taskId, true);
    flash('Subtarefa adicionada');
    reload();
  }
}

function openEditSt(taskId, subtaskId) {
  const subtask = subtaskById(taskId, subtaskId);
  if (!subtask) return;
  uiState.editingSubtask = { taskId, subtaskId };

  setFieldValue('edit-st-titulo', subtask.titulo);
  setFieldValue('edit-st-resp', subtask.responsavel);
  setFieldValue('edit-st-lib', subtask.liberacao === 'NA' ? '' : subtask.liberacao);
  setFieldValue('edit-st-venc', subtask.vencimento);
  const checkbox = byId('edit-st-lib-na');
  if (checkbox) checkbox.checked = subtask.liberacao === 'NA';
  toggleStLibNA('edit-st-lib', checkbox || { checked: false });

  byId('edit-st-modal')?.classList.add('open');
}

function closeEditSt() {
  byId('edit-st-modal')?.classList.remove('open');
  uiState.editingSubtask = null;
}

async function confirmEditSt() {
  if (!uiState.editingSubtask) return;
  const { taskId, subtaskId } = uiState.editingSubtask;
  const subtask = subtaskById(taskId, subtaskId);
  if (!subtask) return;

  const titulo = fieldValue('edit-st-titulo');
  if (!titulo) {
    alert('Informe a descrição da subtarefa.');
    return;
  }

  const payload = {
    titulo,
    responsavel: fieldValue('edit-st-resp'),
    concluida: Boolean(subtask.concluida),
    liberacao: byId('edit-st-lib-na')?.checked ? 'NA' : fieldValue('edit-st-lib'),
    vencimento: nullableDate(fieldValue('edit-st-venc')),
    data_conclusao: subtask.data_conclusao || '',
  };
  const result = await apiCall(`/api/tasks/${taskId}/subtasks/${subtaskId}`, 'PUT', payload);
  if (result) {
    closeEditSt();
    setPanelOpen(taskId, true);
    flash('Subtarefa salva');
    reload();
  }
}

async function setSubtaskConclusion(taskId, subtaskId, value) {
  const subtask = subtaskById(taskId, subtaskId);
  if (!subtask) return;
  const payload = {
    titulo: subtask.titulo,
    responsavel: subtask.responsavel || '',
    concluida: Boolean(value),
    liberacao: subtask.liberacao || '',
    vencimento: nullableDate(subtask.vencimento || ''),
    data_conclusao: value || '',
  };
  const result = await apiCall(`/api/tasks/${taskId}/subtasks/${subtaskId}`, 'PUT', payload);
  if (result) {
    setPanelOpen(taskId, true);
    flash('Conclusão atualizada');
    reload();
  }
}

async function deleteSubtask(taskId, subtaskId) {
  if (!confirm('Remover esta subtarefa?')) return;
  const result = await apiCall(`/api/tasks/${taskId}/subtasks/${subtaskId}`, 'DELETE');
  if (result) {
    setPanelOpen(taskId, true);
    flash('Subtarefa removida');
    reload();
  }
}

function openReplicate(taskId) {
  const task = taskById(taskId);
  if (!task) return;
  uiState.replicateTaskId = taskId;
  const desc = byId('replicate-desc');
  if (desc) desc.textContent = `Criar uma cópia de "${task.titulo}" em outra competência.`;

  const comp = byId('replicate-comp');
  const list = appData.competencias || [];
  const currentIndex = list.indexOf(task.competencia);
  if (comp && currentIndex >= 0) comp.value = list[(currentIndex + 1) % list.length];
  byId('replicate-modal')?.classList.add('open');
}

function closeReplicate() {
  byId('replicate-modal')?.classList.remove('open');
  uiState.replicateTaskId = null;
}

async function confirmReplicate() {
  if (!uiState.replicateTaskId) return;
  const result = await apiCall(`/api/tasks/${uiState.replicateTaskId}/replicate`, 'POST', {
    nova_competencia: fieldValue('replicate-comp'),
  });
  if (result) {
    closeReplicate();
    flash('Obrigação replicada');
    reload();
  }
}

function openUsersModal() {
  byId('users-modal')?.classList.add('open');
}

function closeUsersModal() {
  byId('users-modal')?.classList.remove('open');
}

function toggleCatSelect() {
  const wrap = byId('nu-cat-wrap');
  const perfil = byId('nu-perfil');
  if (!wrap || !perfil) return;
  wrap.style.display = perfil.value === 'equipe' ? 'block' : 'none';
}

async function addUser() {
  const id = fieldValue('nu-nome');
  const nome = fieldValue('nu-fullname');
  const senha = fieldValue('nu-senha');
  const perfil = fieldValue('nu-perfil');
  if (!id || !nome || !senha) {
    alert('Preencha usuário, nome completo e senha.');
    return;
  }

  const result = await apiCall('/api/users', 'POST', {
    id,
    nome,
    senha,
    perfil,
    categoria: perfil === 'gerente' ? null : fieldValue('nu-categoria'),
  });
  if (result) {
    flash('Usuário adicionado');
    reload();
  }
}

async function deleteUser(userId) {
  if (!confirm('Remover este usuário?')) return;
  const result = await apiCall(`/api/users/${encodeURIComponent(userId)}`, 'DELETE');
  if (result) {
    flash('Usuário removido');
    reload();
  }
}

function setCategoryTab(value) {
  // Ao trocar de aba os responsaveis disponiveis mudam, entao o filtro por
  // pessoa e zerado para nao sobrar um nome que nao existe na nova lista.
  goWithParams({ cat_tab: value, categoria: 'todas', responsavel: '', solicitante: '' });
}

function setStatusFilter(value) {
  goWithParams({ status_filter: value });
}

function applyFilters() {
  // Valor vazio faz withParams() remover o parametro da URL, entao "Todos"
  // simplesmente some do endereco em vez de virar ?responsavel=.
  goWithParams({
    categoria: fieldValue('fil-categoria'),
    tipo: fieldValue('fil-tipo'),
    prioridade: fieldValue('fil-prioridade'),
    responsavel: fieldValue('fil-responsavel'),
    solicitante: fieldValue('fil-solicitante'),
    busca: fieldValue('fil-busca'),
  });
}

function clearPeopleFilters() {
  goWithParams({ responsavel: '', solicitante: '' });
}

function handleSearchKey(event) {
  if (event.key === 'Enter') applyFilters();
}

function changeMonth(delta) {
  const list = appData.competencias || [];
  if (!list.length) return;
  const current = appData.dashMonth || list[0];
  const index = list.indexOf(current);
  const next = list[(index + delta + list.length) % list.length];
  goWithParams({ dash_month: next, dash_all: 'false' });
}

function toggleDashAll() {
  goWithParams({ dash_all: appData.dashAll ? 'false' : 'true' });
}

function toggleGroup(header) {
  const body = header?.nextElementSibling;
  const icon = header?.querySelector('.group-toggle');
  if (!body) return;
  body.classList.toggle('collapsed');
  if (icon) icon.textContent = body.classList.contains('collapsed') ? '▶' : '▼';
}

document.addEventListener('DOMContentLoaded', () => {
  toggleCatSelect();
  restoreOpenSubtaskPanels();
  restoreScrollPosition();
  showPendingFlash();

  ['users-modal', 'replicate-modal', 'edit-st-modal'].forEach((id) => {
    const modal = byId(id);
    if (!modal) return;
    modal.addEventListener('click', (event) => {
      if (event.target !== modal) return;
      modal.classList.remove('open');
    });
  });
});
