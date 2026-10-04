const form = document.querySelector('#upload-form');
const fileInput = document.querySelector('#file-input');
const fileLabel = document.querySelector('#file-label');
const fileHint = document.querySelector('#file-hint');
const dropZone = document.querySelector('#drop-zone');
const rows = document.querySelector('#backup-rows');
const emptyState = document.querySelector('#empty-state');
const toastRegion = document.querySelector('#toast-region');
const uploadButton = document.querySelector('#upload-button');

function showToast(message, isError = false) {
  const toast = document.createElement('div');
  toast.className = `toast${isError ? ' error' : ''}`;
  toast.textContent = message;
  toastRegion.append(toast);
  window.setTimeout(() => {
    toast.classList.add('leaving');
    window.setTimeout(() => toast.remove(), 220);
  }, 4200);
}

function formatDate(value) {
  if (!value) return 'No backups yet';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || 'The request could not be completed.');
  return body;
}

async function refreshDashboard() {
  const [status, history] = await Promise.all([
    requestJson('/api/status'),
    requestJson('/api/backups'),
  ]);
  const simulation = status.mode === 'simulation';
  document.querySelector('#mode-label').textContent = simulation ? 'Simulation mode' : 'Amazon S3 connected';
  document.querySelector('#mode-pill').classList.toggle('is-simulation', simulation);
  document.querySelector('#simulation-notice').hidden = !simulation;
  document.querySelector('#region-label').innerHTML = simulation
    ? 'REGION <b>Local simulation</b>'
    : `REGION <b>${escapeHtml(status.region || 'AWS region')}</b>`;
  document.querySelector('#backup-status').textContent = simulation ? 'Simulated' : 'Active';
  document.querySelector('#connection-status').textContent = simulation ? 'is running locally' : 'is connected';
  document.querySelector('#backup-count').textContent = status.backup_count;
  document.querySelector('#last-backup').textContent = formatDate(status.last_backup);
  document.querySelector('#history-count').textContent = history.backups.length;
  renderBackups(history.backups);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function renderBackups(backups) {
  rows.replaceChildren();
  emptyState.hidden = backups.length > 0;
  rows.hidden = backups.length === 0;
  for (const backup of backups) {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><div class="file-cell"><span class="file-icon" aria-hidden="true">▧</span><span class="file-name-wrap"><span class="file-name">${escapeHtml(backup.filename)}</span><span class="file-sub">${escapeHtml(backup.key.slice(0, 14))}…</span></span></div></td>
      <td>${formatSize(backup.size)}</td>
      <td>${escapeHtml(formatDate(backup.last_modified))}</td>
      <td><span class="backup-badge"><span class="status-dot"></span>Backed up</span></td>
      <td><div class="row-actions"><button class="action-button restore-button" type="button" data-key="${escapeHtml(backup.key)}">↓ Restore</button><button class="action-button delete delete-button" type="button" data-key="${escapeHtml(backup.key)}">× Delete</button></div></td>`;
    rows.append(row);
  }
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  fileLabel.textContent = file ? file.name : 'Choose a file';
  fileHint.textContent = file ? formatSize(file.size) : 'or drag and drop it here';
});

for (const eventName of ['dragenter', 'dragover']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add('drag-over');
  });
}
for (const eventName of ['dragleave', 'drop']) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove('drag-over');
  });
}
dropZone.addEventListener('drop', (event) => {
  if (event.dataTransfer.files.length) {
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) return showToast('Choose a file before creating a backup.', true);
  const data = new FormData(form);
  uploadButton.disabled = true;
  uploadButton.textContent = 'Backing up…';
  try {
    const result = await requestJson('/api/backups', { method: 'POST', body: data });
    showToast(result.message);
    form.reset();
    fileInput.dispatchEvent(new Event('change'));
    await refreshDashboard();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    uploadButton.disabled = false;
    uploadButton.innerHTML = '<span aria-hidden="true">＋</span> Back up file';
  }
});

rows.addEventListener('click', async (event) => {
  const restoreButton = event.target.closest('.restore-button');
  const deleteButton = event.target.closest('.delete-button');
  if (restoreButton) {
    restoreButton.disabled = true;
    try {
      const response = await fetch(`/api/backups/${encodeURIComponent(restoreButton.dataset.key)}/restore`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || 'The backup could not be restored.');
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = restoreButton.dataset.key.split('__').slice(1).join('__');
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showToast('Backup restored. Your download has started.');
    } catch (error) {
      showToast(error.message, true);
    } finally {
      restoreButton.disabled = false;
    }
  }
  if (deleteButton) {
    const filename = deleteButton.closest('tr').querySelector('.file-name').textContent;
    if (!window.confirm(`Delete the backup “${filename}”? This cannot be undone.`)) return;
    deleteButton.disabled = true;
    try {
      const result = await requestJson(`/api/backups/${encodeURIComponent(deleteButton.dataset.key)}`, { method: 'DELETE' });
      showToast(result.message);
      await refreshDashboard();
    } catch (error) {
      showToast(error.message, true);
      deleteButton.disabled = false;
    }
  }
});

document.querySelector('#refresh-button').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await refreshDashboard();
    showToast('Backup history is up to date.');
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

refreshDashboard().catch((error) => showToast(error.message, true));