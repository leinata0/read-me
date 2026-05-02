// README 生成器 — 前端逻辑

(function () {
    'use strict';

    // --- 常量 ---
    const LS_KEYS = 'readme-gen-keys';
    const LS_PROVIDER = 'readme-gen-provider';
    const LS_MODEL = 'readme-gen-model';

    // --- DOM ---
    const form = document.getElementById('analyze-form');
    const folderInput = document.getElementById('folder-path');
    const providerSelect = document.getElementById('provider-select');
    const modelInput = document.getElementById('model-input');
    const modelDatalist = document.getElementById('model-datalist');
    const refreshModelsBtn = document.getElementById('refresh-models-btn');
    const generateBtn = document.getElementById('generate-btn');
    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const errorSection = document.getElementById('error-section');
    const errorMessage = document.getElementById('error-message');
    const errorDismissBtn = document.getElementById('error-dismiss-btn');
    const previewSection = document.getElementById('preview-section');
    const readmePreview = document.getElementById('readme-preview');
    const readmeSource = document.getElementById('readme-source');
    const downloadBtn = document.getElementById('download-btn');
    const regenerateBtn = document.getElementById('regenerate-btn');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const settingsBtn = document.getElementById('settings-btn');
    const settingsDialog = document.getElementById('settings-dialog');
    const settingsBody = document.getElementById('settings-body');
    const settingsSaveBtn = document.getElementById('settings-save-btn');
    const settingsCloseBtn = document.getElementById('settings-close-btn');
    const keyStatus = document.getElementById('key-status');
    const keyStatusText = document.getElementById('key-status-text');

    let currentReadme = '';
    let providersData = [];

    // --- Marked 配置 ---
    marked.setOptions({
        highlight: function (code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return hljs.highlightAuto(code).value;
        },
        breaks: false,
        gfm: true,
    });

    // ========== API Key 管理 ==========

    function loadSavedKeys() {
        try {
            return JSON.parse(localStorage.getItem(LS_KEYS) || '{}');
        } catch {
            return {};
        }
    }

    function saveKeys(keys) {
        localStorage.setItem(LS_KEYS, JSON.stringify(keys));
    }

    function getEffectiveApiKeys() {
        const saved = loadSavedKeys();
        const result = {};
        providersData.forEach(p => {
            const local = saved[p.name] || {};
            if (local.api_key) {
                result[p.name] = { api_key: local.api_key, base_url: local.base_url || '' };
            }
        });
        return result;
    }

    function isProviderReady(p) {
        const saved = loadSavedKeys();
        const local = saved[p.name] || {};
        return p.is_configured || !!local.api_key;
    }

    // ========== 设置弹窗 ==========

    settingsBtn.addEventListener('click', () => openSettings());

    function openSettings() {
        const saved = loadSavedKeys();
        settingsBody.innerHTML = '';

        providersData.forEach(p => {
            const local = saved[p.name] || {};
            const hasEnvKey = p.is_configured;
            const hasLocalKey = !!local.api_key;

            const card = document.createElement('div');
            card.className = 'provider-key-card';
            card.innerHTML = `
                <details ${hasLocalKey || hasEnvKey ? '' : 'open'}>
                    <summary><strong>${p.display_name}</strong>
                        ${hasEnvKey ? '<span class="badge badge-env">环境变量</span>' : ''}
                        ${hasLocalKey ? '<span class="badge badge-local">本地</span>' : ''}
                    </summary>
                    <div class="form-inner">
                        <label for="key-${p.name}">API Key</label>
                        <input type="password" id="key-${p.name}" data-provider="${p.name}" data-field="api_key"
                               value="${local.api_key || ''}" placeholder="${p.env_key_hint || '输入 API Key'}">
                        <label for="base-${p.name}">Base URL <small>（可选）</small></label>
                        <input type="text" id="base-${p.name}" data-provider="${p.name}" data-field="base_url"
                               value="${local.base_url || ''}" placeholder="${p.base_url_hint || '默认'}">
                    </div>
                </details>
            `;
            settingsBody.appendChild(card);
        });

        settingsDialog.showModal();
    }

    settingsSaveBtn.addEventListener('click', () => {
        const keys = {};
        settingsBody.querySelectorAll('input[data-provider]').forEach(input => {
            const provider = input.dataset.provider;
            const field = input.dataset.field;
            if (!keys[provider]) keys[provider] = {};
            keys[provider][field] = input.value.trim();
        });
        Object.keys(keys).forEach(p => {
            if (!keys[p].api_key) delete keys[p];
            else if (!keys[p].base_url) delete keys[p].base_url;
        });
        saveKeys(keys);
        settingsDialog.close();
        renderProviderSelect();
    });

    settingsCloseBtn.addEventListener('click', () => settingsDialog.close());

    // ========== 渠道与模型加载 ==========

    async function loadProviders() {
        try {
            const res = await fetch('/api/providers');
            providersData = await res.json();
            renderProviderSelect();
        } catch {
            providerSelect.innerHTML = '<option value="">渠道加载失败</option>';
        }
    }

    function renderProviderSelect() {
        providerSelect.innerHTML = '';
        const savedProvider = localStorage.getItem(LS_PROVIDER);
        const savedModel = localStorage.getItem(LS_MODEL);

        providersData.forEach(p => {
            const ready = isProviderReady(p);
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = ready ? p.display_name : `${p.display_name}（点击齿轮配置）`;
            opt.disabled = !ready;
            if (p.name === savedProvider && ready) {
                opt.selected = true;
            }
            providerSelect.appendChild(opt);
        });

        if (!providerSelect.value && providersData.length) {
            const first = providersData.find(p => isProviderReady(p));
            if (first) providerSelect.value = first.name;
        }

        updateModelSelect(savedModel);
        updateKeyStatus();
    }

    function updateModelSelect(savedModel) {
        const selected = providersData.find(p => p.name === providerSelect.value);
        modelDatalist.innerHTML = '';

        if (!selected) {
            modelInput.value = '';
            modelInput.placeholder = '默认';
            refreshModelsBtn.style.display = 'none';
            return;
        }

        selected.available_models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            modelDatalist.appendChild(opt);
        });

        if (savedModel) {
            modelInput.value = savedModel;
        } else {
            modelInput.value = selected.available_models[0] || '';
        }

        modelInput.placeholder = '输入或选择模型';
        refreshModelsBtn.style.display = isProviderReady(selected) ? '' : 'none';
    }

    // ========== 动态获取模型列表 ==========

    let _refreshTimer = null;

    refreshModelsBtn.addEventListener('click', async () => {
        const providerName = providerSelect.value;
        if (!providerName) return;

        const saved = loadSavedKeys();
        const local = saved[providerName] || {};
        const p = providersData.find(p => p.name === providerName);
        if (!p) return;

        const apiKey = local.api_key || '';
        if (!apiKey && !p.is_configured) return;

        refreshModelsBtn.disabled = true;
        refreshModelsBtn.innerHTML = '...';

        try {
            const res = await fetch(`/api/providers/${providerName}/models`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: apiKey, base_url: local.base_url || '' }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                console.warn('获取模型列表失败:', err.detail);
                return;
            }

            const data = await res.json();
            modelDatalist.innerHTML = '';
            data.models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                modelDatalist.appendChild(opt);
            });

            if (!modelInput.value && data.models.length > 0) {
                modelInput.value = data.models[0];
            }

            refreshModelsBtn.title = data.source === 'fetched'
                ? '模型列表已从 API 获取'
                : '使用默认模型列表（获取失败）';
        } catch (err) {
            console.warn('获取模型列表失败:', err.message);
        } finally {
            refreshModelsBtn.disabled = false;
            refreshModelsBtn.innerHTML = '&#8635;';
        }
    });

    // ========== Key 状态 ==========

    function updateKeyStatus() {
        const p = providersData.find(p => p.name === providerSelect.value);
        if (!p) { keyStatus.style.display = 'none'; return; }

        const saved = loadSavedKeys();
        const local = saved[p.name] || {};
        const source = local.api_key ? '本地' : (p.is_configured ? '环境变量' : '');

        if (source) {
            keyStatus.style.display = '';
            keyStatusText.innerHTML = `&#10003; API Key：<strong>${source}</strong>${local.base_url ? ' | Base URL: ' + escapeHtml(local.base_url) : ''}`;
            keyStatusText.style.color = '#27ae60';
        } else {
            keyStatus.style.display = '';
            keyStatusText.innerHTML = '&#10007; 未配置 API Key，点击齿轮图标进行设置';
            keyStatusText.style.color = '#e74c3c';
        }
    }

    providerSelect.addEventListener('change', () => {
        updateModelSelect();
        updateKeyStatus();
        localStorage.setItem(LS_PROVIDER, providerSelect.value);
    });

    modelInput.addEventListener('change', () => {
        localStorage.setItem(LS_MODEL, modelInput.value.trim());
    });

    modelInput.addEventListener('input', () => {
        clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(() => {
            localStorage.setItem(LS_MODEL, modelInput.value.trim());
        }, 500);
    });

    // ========== 标签页切换 ==========

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
        });
    });

    // ========== 错误处理 ==========

    function showError(msg) {
        errorMessage.textContent = msg;
        errorSection.style.display = '';
        progressSection.style.display = 'none';
    }

    function hideError() {
        errorSection.style.display = 'none';
    }

    errorDismissBtn.addEventListener('click', hideError);

    // ========== 表单提交与 SSE ==========

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideError();
        previewSection.style.display = 'none';
        progressSection.style.display = '';
        progressBar.removeAttribute('value');
        progressText.innerHTML = '<small>启动中...</small>';
        generateBtn.setAttribute('aria-busy', 'true');
        generateBtn.disabled = true;
        currentReadme = '';
        readmePreview.innerHTML = '';
        readmeSource.value = '';

        const body = {
            folder_path: folderInput.value.trim(),
            provider: providerSelect.value || null,
            model: modelInput.value.trim() || null,
            api_keys: getEffectiveApiKeys(),
        };

        try {
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                showError(err.detail || `服务器错误: ${res.status}`);
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                let eventType = '';
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6);
                        try {
                            const data = JSON.parse(dataStr);
                            handleSSEEvent(eventType, data);
                        } catch {
                            // 忽略格式异常
                        }
                        eventType = '';
                    }
                }
            }
        } catch (err) {
            showError(`连接错误: ${err.message}`);
        } finally {
            generateBtn.removeAttribute('aria-busy');
            generateBtn.disabled = false;
            progressSection.style.display = 'none';
        }
    });

    function handleSSEEvent(type, data) {
        switch (type) {
            case 'progress':
                progressText.innerHTML = `<small>${escapeHtml(data.detail)}</small>`;
                break;

            case 'chunk':
                currentReadme += data.text;
                readmePreview.innerHTML = marked.parse(currentReadme);
                readmeSource.value = currentReadme;
                previewSection.style.display = '';
                progressBar.value = 90;
                break;

            case 'done':
                progressBar.value = 100;
                progressText.innerHTML = '<small>生成完成！</small>';
                readmePreview.innerHTML = marked.parse(currentReadme);
                readmeSource.value = currentReadme;
                break;

            case 'error':
                showError(`[${data.code}] ${data.message}`);
                break;
        }
    }

    // ========== 下载 ==========

    downloadBtn.addEventListener('click', async () => {
        const content = readmeSource.value || currentReadme;
        if (!content) return;

        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });
            if (!res.ok) throw new Error('下载失败');
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'README.md';
            a.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            showError(`下载错误: ${err.message}`);
        }
    });

    // ========== 重新生成 ==========

    regenerateBtn.addEventListener('click', () => {
        form.dispatchEvent(new Event('submit'));
    });

    // ========== 工具函数 ==========

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ========== 初始化 ==========
    loadProviders();
})();
