// Popup script: handle UI interactions

let extractedData = null;

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const target = tab.dataset.tab;
    document.getElementById('clip-tab').style.display = target === 'clip' ? '' : 'none';
    document.getElementById('settings-tab').style.display = target === 'settings' ? '' : 'none';
  });
});

// Settings button shortcut
document.getElementById('settings-btn').addEventListener('click', () => {
  document.querySelector('[data-tab="settings"]').click();
});

// Load saved settings
chrome.storage.sync.get(['pagefly_url', 'pagefly_token'], (data) => {
  if (data.pagefly_url) document.getElementById('api-url').value = data.pagefly_url;
  if (data.pagefly_token) document.getElementById('api-token').value = data.pagefly_token;
  updateUploadButton();
});

function getConfig() {
  return {
    url: document.getElementById('api-url').value.trim().replace(/\/$/, ''),
    token: document.getElementById('api-token').value.trim(),
  };
}

function isConfigured() {
  const config = getConfig();
  return config.url && config.token;
}

function updateUploadButton() {
  const btn = document.getElementById('upload-btn');
  if (!isConfigured()) {
    btn.disabled = true;
    btn.textContent = 'Configure API first';
  } else if (!extractedData || extractedData.error) {
    btn.disabled = true;
    btn.textContent = 'No content extracted';
  } else {
    btn.disabled = false;
    btn.textContent = 'Upload to PageFly';
  }
}

// Save settings
document.getElementById('save-btn').addEventListener('click', () => {
  const config = getConfig();
  chrome.storage.sync.set({
    pagefly_url: config.url,
    pagefly_token: config.token,
  }, () => {
    const el = document.getElementById('test-result');
    el.className = 'test-result ok';
    el.textContent = 'Settings saved!';
    updateUploadButton();
    setTimeout(() => { el.textContent = ''; el.className = ''; }, 2000);
  });
});

// Test connection
document.getElementById('test-btn').addEventListener('click', async () => {
  const config = getConfig();
  const el = document.getElementById('test-result');

  if (!config.url || !config.token) {
    el.className = 'test-result fail';
    el.textContent = 'Please fill in both URL and token';
    return;
  }

  el.className = 'test-result';
  el.textContent = 'Testing...';

  try {
    const resp = await fetch(`${config.url}/api/stats`, {
      headers: { 'Authorization': `Bearer ${config.token}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      el.className = 'test-result ok';
      el.textContent = `Connected! ${data.documents} docs, ${data.wiki_articles} wiki articles`;
    } else {
      el.className = 'test-result fail';
      el.textContent = `Error: ${resp.status} ${resp.statusText}`;
    }
  } catch (e) {
    el.className = 'test-result fail';
    el.textContent = `Connection failed: ${e.message}`;
  }
});

// Extract page content
function doExtract() {
  const loading = document.getElementById('loading');
  const preview = document.getElementById('preview-content');
  const actions = document.getElementById('clip-actions');
  loading.style.display = 'flex';
  actions.style.display = 'none';

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    chrome.tabs.sendMessage(tabs[0].id, { action: 'extract' }, (response) => {
      loading.style.display = 'none';

      if (chrome.runtime.lastError || !response) {
        preview.innerHTML = '<div class="status error">Could not extract page. Try refreshing the page first.</div>';
        actions.style.display = 'flex';
        updateUploadButton();
        return;
      }

      extractedData = response;

      if (response.error) {
        preview.innerHTML = `<div class="status error">${response.error}</div>`;
      } else {
        const wordCount = response.markdown.split(/\s+/).length;
        preview.innerHTML = `
          <div class="preview-title">${escapeHtml(response.title)}</div>
          <div class="preview-meta">${escapeHtml(response.url)} · ${wordCount} words</div>
          <div class="preview-body">${escapeHtml(response.markdown)}</div>
        `;
      }

      actions.style.display = 'flex';
      updateUploadButton();
    });
  });
}

// Re-extract
document.getElementById('re-extract').addEventListener('click', doExtract);

// Upload
document.getElementById('upload-btn').addEventListener('click', async () => {
  if (!extractedData || !extractedData.markdown || !isConfigured()) return;

  const btn = document.getElementById('upload-btn');
  btn.disabled = true;
  btn.textContent = 'Uploading...';

  const config = getConfig();
  const filename = slugify(extractedData.title) + '.md';

  try {
    // Create a File-like blob and upload via multipart form
    const blob = new Blob([extractedData.markdown], { type: 'text/markdown' });
    const formData = new FormData();
    formData.append('file', blob, filename);

    const resp = await fetch(`${config.url}/api/ingest`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${config.token}` },
      body: formData,
    });

    if (resp.ok) {
      const data = await resp.json();
      btn.textContent = 'Uploaded!';
      btn.style.background = '#16A34A';

      const preview = document.getElementById('preview-content');
      preview.innerHTML = `
        <div class="status success">
          Clipped to PageFly!<br>
          Doc ID: ${data.doc_id || 'processing...'}
        </div>
      ` + preview.innerHTML;
    } else {
      const err = await resp.text();
      btn.textContent = 'Upload failed';
      btn.style.background = '#DC2626';
      console.error('Upload error:', err);
    }
  } catch (e) {
    btn.textContent = 'Upload failed';
    btn.style.background = '#DC2626';
    console.error('Upload error:', e);
  }

  setTimeout(() => {
    btn.textContent = 'Upload to PageFly';
    btn.style.background = '';
    btn.disabled = false;
  }, 3000);
});

function slugify(text) {
  return text.toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .slice(0, 60);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

// Auto-extract on popup open
doExtract();
