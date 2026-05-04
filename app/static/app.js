// README 生成器 — 前端逻辑

window.onerror = function (msg, url, line) {
    document.body.insertAdjacentHTML('afterbegin',
        '<p style="color:red;padding:1rem;background:#fff3f3;border-bottom:2px solid red;z-index:9999;position:relative">' +
        'JS 错误: ' + msg + ' (第 ' + line + ' 行)</p>');
};

(function () {
    'use strict';
    console.log('[README-GEN] IIFE 开始执行');

    // 安全检查外部依赖
    if (typeof marked === 'undefined') {
        document.body.insertAdjacentHTML('afterbegin', '<p style="color:red;padding:1rem">错误：marked.js 未加载，请检查网络连接后刷新页面。</p>');
        return;
    }
    console.log('[README-GEN] marked 已加载');

    // --- 常量 ---
    const LS_KEYS = 'readme-gen-keys';
    const LS_PROVIDER = 'readme-gen-provider';
    const LS_MODEL = 'readme-gen-model';
    const LS_SETTINGS = 'readme-gen-settings';

    // --- DOM ---
    const form = document.getElementById('analyze-form');
    const folderInput = document.getElementById('folder-path');
    const providerSelect = document.getElementById('provider-select');
    const modelInput = document.getElementById('model-input');
    const modelDatalist = document.getElementById('model-datalist');
    const refreshModelsBtn = document.getElementById('refresh-models-btn');
    const generateBtn = document.getElementById('generate-btn');
    const progressSection = document.getElementById('progress-section');
    const pipelineSteps = document.getElementById('pipeline-steps');
    const streamStats = document.getElementById('stream-stats');
    const statChars = document.getElementById('stat-chars');
    const statTime = document.getElementById('stat-time');
    const statSpeed = document.getElementById('stat-speed');
    const errorSection = document.getElementById('error-section');
    const errorMessage = document.getElementById('error-message');
    const errorDismissBtn = document.getElementById('error-dismiss-btn');
    const previewSection = document.getElementById('preview-section');
    const readmePreview = document.getElementById('readme-preview');
    const readmeSource = document.getElementById('readme-source');
    const downloadBtn = document.getElementById('download-btn');
    const regenerateBtn = document.getElementById('regenerate-btn');
    const testBtn = document.getElementById('test-btn');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const settingsBtn = document.getElementById('settings-btn');
    const settingsDialog = document.getElementById('settings-dialog');
    const settingsBody = document.getElementById('settings-body');
    const settingsSaveBtn = document.getElementById('settings-save-btn');
    const settingsCloseBtn = document.getElementById('settings-close-btn');
    const settingLanguage = document.getElementById('setting-language');
    const settingMaxAnalyze = document.getElementById('setting-max-analyze');
    const settingMaxGenerate = document.getElementById('setting-max-generate');
    const settingTone = document.getElementById('setting-tone');
    const settingTemperature = document.getElementById('setting-temperature');
    const tempValue = document.getElementById('temp-value');
    const settingBadges = document.getElementById('setting-badges');
    const settingCustomSections = document.getElementById('setting-custom-sections');
    const settingExcludeSections = document.getElementById('setting-exclude-sections');
    const settingCustomPrompt = document.getElementById('setting-custom-prompt');
    const keyStatus = document.getElementById('key-status');
    const keyStatusText = document.getElementById('key-status-text');

    let currentReadme = '';
    let providersData = [];

    // --- Pipeline step management ---
    const STEP_ORDER = ['validate', 'read', 'analyze', 'generate'];
    let currentStepIndex = -1;
    let streamStartTime = 0;
    let streamCharCount = 0;
    let statsTimer = null;

    function resetSteps() {
        currentStepIndex = -1;
        streamCharCount = 0;
        streamStartTime = 0;
        clearInterval(statsTimer);
        pipelineSteps.querySelectorAll('.pipeline-step').forEach(el => {
            el.classList.remove('active', 'done', 'error');
            el.querySelector('.step-detail').textContent = '';
        });
        streamStats.style.display = 'none';
    }

    function activateStep(name) {
        const idx = STEP_ORDER.indexOf(name);
        if (idx < 0) return;
        // mark previous steps done
        for (let i = 0; i < idx; i++) {
            const el = pipelineSteps.querySelector(`[data-step="${STEP_ORDER[i]}"]`);
            if (el && !el.classList.contains('done') && !el.classList.contains('error')) {
                el.classList.remove('active');
                el.classList.add('done');
            }
        }
        const el = pipelineSteps.querySelector(`[data-step="${name}"]`);
        if (el) {
            el.classList.remove('done', 'error');
            el.classList.add('active');
        }
        currentStepIndex = idx;
    }

    function completeStep(name, detail) {
        const el = pipelineSteps.querySelector(`[data-step="${name}"]`);
        if (el) {
            el.classList.remove('active');
            el.classList.add('done');
            if (detail) el.querySelector('.step-detail').textContent = detail;
        }
    }

    function errorStep(name, detail) {
        const el = pipelineSteps.querySelector(`[data-step="${name}"]`);
        if (el) {
            el.classList.remove('active');
            el.classList.add('error');
            if (detail) el.querySelector('.step-detail').textContent = detail;
        }
    }

    function completeAllSteps() {
        STEP_ORDER.forEach(name => {
            const el = pipelineSteps.querySelector(`[data-step="${name}"]`);
            if (el && !el.classList.contains('error')) {
                el.classList.remove('active');
                el.classList.add('done');
            }
        });
        clearInterval(statsTimer);
    }

    function startStreamStats() {
        streamStartTime = Date.now();
        streamCharCount = 0;
        streamStats.style.display = '';
        updateStreamStats();
        statsTimer = setInterval(updateStreamStats, 200);
    }

    function updateStreamStats() {
        const elapsed = (Date.now() - streamStartTime) / 1000;
        const speed = elapsed > 0 ? Math.round(streamCharCount / elapsed) : 0;
        statChars.textContent = `${streamCharCount.toLocaleString()} 字符`;
        statTime.textContent = `${elapsed.toFixed(1)}s`;
        statSpeed.textContent = `${speed} 字符/秒`;
    }

    function mapProgressToStep(detail) {
        const d = detail.toLowerCase();
        // English
        if (d.includes('validat')) return 'validate';
        if (d.includes('reading') || d.includes('found') || d.includes('source file')) return 'read';
        if (d.includes('analyz') || d.includes('cached') || d.includes('structure')) return 'analyze';
        if (d.includes('generat') || d.includes('readme')) return 'generate';
        // Chinese
        if (d.includes('校验') || d.includes('路径')) return 'validate';
        if (d.includes('读取') || d.includes('文件') || d.includes('源文件')) return 'read';
        if (d.includes('分析') || d.includes('缓存')) return 'analyze';
        if (d.includes('生成')) return 'generate';
        return null;
    }

    // --- Marked 配置（兼容 v4-v15） ---
    try {
        if (typeof marked.setOptions === 'function') {
            marked.setOptions({ breaks: false, gfm: true });
        } else if (typeof marked.use === 'function') {
            marked.use({ breaks: false, gfm: true });
        }

        // 用 hljs renderer 覆盖 code 渲染
        if (typeof hljs !== 'undefined' && typeof marked.use === 'function') {
            marked.use({
                renderer: {
                    code: function (token) {
                        var text = token.text || token;
                        var lang = token.lang || '';
                        var highlighted = text;
                        if (lang && hljs.getLanguage(lang)) {
                            highlighted = hljs.highlight(text, { language: lang }).value;
                        } else if (!lang) {
                            highlighted = hljs.highlightAuto(text).value;
                        }
                        return '<pre><code class="hljs' + (lang ? ' language-' + lang : '') + '">' + highlighted + '</code></pre>';
                    }
                }
            });
        }
    } catch (e) {
        console.warn('Marked 配置失败，使用默认配置:', e);
    }
    console.log('[README-GEN] Marked 配置完成');

    // --- 安全渲染（DOMPurify 可选） ---
    function safeRender(md) {
        const html = typeof marked.parse === 'function' ? marked.parse(md) : marked(md);
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(html);
        }
        return html;
    }

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

    function loadSettings() {
        try {
            return JSON.parse(localStorage.getItem(LS_SETTINGS) || '{}');
        } catch {
            return {};
        }
    }

    function saveSettings(settings) {
        localStorage.setItem(LS_SETTINGS, JSON.stringify(settings));
    }

    function applySettingsToUI() {
        const s = loadSettings();
        settingLanguage.value = s.language || 'zh';
        settingMaxAnalyze.value = s.max_tokens_analyze || 16384;
        settingMaxGenerate.value = s.max_tokens_generate || 32768;
        settingTone.value = s.tone || 'professional';
        settingTemperature.value = s.temperature ?? 0.7;
        tempValue.textContent = s.temperature ?? 0.7;
        settingBadges.checked = s.include_badges !== false;
        settingCustomSections.value = s.custom_sections || '';
        settingExcludeSections.value = s.exclude_sections || '';
        settingCustomPrompt.value = s.custom_prompt_suffix || '';
    }

    function collectSettingsFromUI() {
        return {
            language: settingLanguage.value,
            max_tokens_analyze: parseInt(settingMaxAnalyze.value) || 16384,
            max_tokens_generate: parseInt(settingMaxGenerate.value) || 32768,
            tone: settingTone.value,
            temperature: parseFloat(settingTemperature.value) || 0.7,
            include_badges: settingBadges.checked,
            custom_sections: settingCustomSections.value.trim(),
            exclude_sections: settingExcludeSections.value.trim(),
            custom_prompt_suffix: settingCustomPrompt.value.trim(),
        };
    }

    function getEffectiveApiKeys() {
        const saved = loadSavedKeys();
        const result = {};
        providersData.forEach(p => {
            const local = saved[p.name] || {};
            if (local.api_key) {
                result[p.name] = {
                    api_key: local.api_key,
                    base_url: local.base_url || '',
                    max_tokens_analyze: local.max_tokens_analyze || 16384,
                    max_tokens_generate: local.max_tokens_generate || 32768,
                    temperature: local.temperature ?? 0.7,
                };
            }
        });
        return result;
    }

    function isProviderReady(p) {
        const saved = loadSavedKeys();
        const local = saved[p.name] || {};
        return p.is_configured || !!local.api_key || !p.env_key_hint;
    }

    // ========== 设置弹窗 ==========

    settingsBtn.addEventListener('click', () => openSettings());

    function openSettings() {
        applySettingsToUI();
        const saved = loadSavedKeys();
        settingsBody.innerHTML = '';

        providersData.forEach(p => {
            const local = saved[p.name] || {};
            const hasEnvKey = p.is_configured;
            const hasLocalKey = !!local.api_key;
            const esc = escapeHtml;

            const card = document.createElement('div');
            card.className = 'provider-key-card';
            card.innerHTML = `
                <details ${hasLocalKey || hasEnvKey ? '' : 'open'}>
                    <summary><strong>${esc(p.display_name)}</strong>
                        ${hasEnvKey ? '<span class="badge badge-env">环境变量</span>' : ''}
                        ${hasLocalKey ? '<span class="badge badge-local">本地</span>' : ''}
                    </summary>
                    <div class="form-inner">
                        <label for="key-${esc(p.name)}">API Key</label>
                        <input type="password" id="key-${esc(p.name)}" data-provider="${esc(p.name)}" data-field="api_key"
                               value="${esc(local.api_key || '')}" placeholder="${esc(p.env_key_hint || '输入 API Key')}">
                        <label for="base-${esc(p.name)}">Base URL <small>（可选）</small></label>
                        <input type="text" id="base-${esc(p.name)}" data-provider="${esc(p.name)}" data-field="base_url"
                               value="${esc(local.base_url || '')}" placeholder="${esc(p.base_url_hint || '默认')}">
                    </div>
                </details>
            `;
            settingsBody.appendChild(card);
        });

        settingsDialog.showModal();
    }

    settingsSaveBtn.addEventListener('click', () => {
        // Save global settings
        saveSettings(collectSettingsFromUI());

        // Save provider keys with max_tokens merged in
        const settings = collectSettingsFromUI();
        const keys = {};
        settingsBody.querySelectorAll('input[data-provider]').forEach(input => {
            const provider = input.dataset.provider;
            const field = input.dataset.field;
            if (!keys[provider]) keys[provider] = {};
            keys[provider][field] = input.value.trim();
        });
        Object.keys(keys).forEach(p => {
            if (!keys[p].api_key) delete keys[p];
            else {
                if (!keys[p].base_url) delete keys[p].base_url;
                keys[p].max_tokens_analyze = settings.max_tokens_analyze;
                keys[p].max_tokens_generate = settings.max_tokens_generate;
                keys[p].temperature = settings.temperature;
            }
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

        if (savedModel && selected.available_models.includes(savedModel)) {
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

            // 显示模型列表获取状态
            const modelHint = document.getElementById('model-hint');
            if (data.source === 'fetched') {
                refreshModelsBtn.title = '模型列表已从 API 获取';
                if (modelHint) modelHint.style.display = 'none';
            } else if (data.error) {
                refreshModelsBtn.title = '获取失败：' + data.error;
                if (modelHint) {
                    modelHint.style.display = '';
                    modelHint.textContent = data.error;
                }
                modelInput.placeholder = '手动输入模型名称';
            } else {
                refreshModelsBtn.title = '使用默认模型列表';
                if (modelHint) modelHint.style.display = 'none';
            }
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

    // 温度滑块实时显示
    settingTemperature.addEventListener('input', () => {
        tempValue.textContent = settingTemperature.value;
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
        errorSection.style.borderColor = '';
        errorMessage.style.color = '';
    }

    errorDismissBtn.addEventListener('click', hideError);

    // ========== 测试连接 ==========

    const testStatus = document.getElementById('test-status');
    const testStatusText = document.getElementById('test-status-text');
    let testStatusTimer = null;

    function showTestStatus(msg, isError) {
        clearTimeout(testStatusTimer);
        testStatus.style.display = '';
        testStatusText.textContent = msg;
        testStatusText.style.color = isError ? '#e74c3c' : '#27ae60';
        if (!isError) {
            testStatusTimer = setTimeout(() => {
                testStatus.style.display = 'none';
            }, 5000);
        }
    }

    function hideTestStatus() {
        clearTimeout(testStatusTimer);
        testStatus.style.display = 'none';
    }

    console.log('[README-GEN] testBtn =', testBtn);
    testBtn.addEventListener('click', async () => {
        console.log('[README-GEN] 测试连接按钮被点击');
        hideError();
        hideTestStatus();
        const provider = providerSelect.value;
        if (!provider) {
            showTestStatus('请先选择一个 AI 渠道', true);
            return;
        }

        testBtn.disabled = true;
        testBtn.textContent = '测试中...';

        const savedSettings = loadSettings();
        const body = {
            folder_path: '.',
            provider: provider,
            model: modelInput.value.trim() || null,
            api_keys: getEffectiveApiKeys(),
            language: savedSettings.language || 'zh',
        };

        try {
            const res = await fetch('/api/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (data.ok) {
                showTestStatus(data.message, false);
            } else {
                showTestStatus(`[${data.code}] ${data.message}`, true);
            }
        } catch (err) {
            showTestStatus('连接失败: ' + err.message, true);
        } finally {
            testBtn.disabled = false;
            testBtn.textContent = '测试连接';
        }
    });
    console.log('[README-GEN] 所有事件监听器已注册');

    // ========== 表单提交与 SSE ==========

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideError();
        previewSection.style.display = 'none';
        progressSection.style.display = '';
        resetSteps();
        generateBtn.setAttribute('aria-busy', 'true');
        generateBtn.disabled = true;
        currentReadme = '';
        readmePreview.innerHTML = '';
        readmeSource.value = '';

        const savedSettings = loadSettings();
        const body = {
            folder_path: folderInput.value.trim(),
            provider: providerSelect.value || null,
            model: modelInput.value.trim() || null,
            api_keys: getEffectiveApiKeys(),
            language: savedSettings.language || 'zh',
            temperature: savedSettings.temperature ?? 0.7,
            tone: savedSettings.tone || 'professional',
            custom_sections: savedSettings.custom_sections || '',
            exclude_sections: savedSettings.exclude_sections || '',
            include_badges: savedSettings.include_badges !== false,
            custom_prompt_suffix: savedSettings.custom_prompt_suffix || '',
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
            case 'progress': {
                const stepName = mapProgressToStep(data.detail);
                if (stepName) {
                    // complete the previous active step
                    if (currentStepIndex >= 0) {
                        const prevName = STEP_ORDER[currentStepIndex];
                        if (prevName !== stepName) {
                            completeStep(prevName);
                        }
                    }
                    activateStep(stepName);
                    const el = pipelineSteps.querySelector(`[data-step="${stepName}"]`);
                    if (el) el.querySelector('.step-detail').textContent = data.detail;
                }
                break;
            }

            case 'chunk':
                currentReadme += data.text;
                streamCharCount += data.text.length;
                readmePreview.innerHTML = safeRender(currentReadme);
                readmeSource.value = currentReadme;
                previewSection.style.display = '';
                // start stats on first chunk
                if (streamStartTime === 0) {
                    activateStep('generate');
                    startStreamStats();
                }
                break;

            case 'done':
                completeAllSteps();
                readmePreview.innerHTML = safeRender(currentReadme);
                readmeSource.value = currentReadme;
                break;

            case 'error': {
                // figure out which step failed
                const msg = data.message || '';
                if (currentStepIndex >= 0) {
                    errorStep(STEP_ORDER[currentStepIndex], msg.slice(0, 80));
                }
                showError(`[${data.code}] ${data.message}`);
                break;
            }
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
        form.requestSubmit();
    });

    // ========== 工具函数 ==========

    function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[c]);
    }

    // ========== 初始化 ==========
    loadProviders();
    console.log('[README-GEN] IIFE 执行完毕');
})();
