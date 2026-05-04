// README 生成器 — 前端逻辑

function prependBanner(message) {
    const banner = document.createElement('p');
    banner.style.cssText = 'color:red;padding:1rem;background:#fff3f3;border-bottom:2px solid red;z-index:9999;position:relative';
    banner.textContent = message;
    document.body.prepend(banner);
}

window.onerror = function (msg, url, line) {
    prependBanner(`JS 错误: ${msg} (第 ${line} 行)`);
};

(function () {
    'use strict';

    const keyStorage = {
        getItem(key) {
            try {
                return sessionStorage.getItem(key);
            } catch {
                return null;
            }
        },
        setItem(key, value) {
            try {
                sessionStorage.setItem(key, value);
            } catch {
                // ignore storage errors
            }
        }
    };

    const persistedStorage = {
        getItem(key) {
            try {
                return localStorage.getItem(key);
            } catch {
                return null;
            }
        },
        setItem(key, value) {
            try {
                localStorage.setItem(key, value);
            } catch {
                // ignore storage errors
            }
        }
    };

    // 安全检查外部依赖
    if (typeof marked === 'undefined') {
        prependBanner('错误：marked.js 未加载，请检查网络连接后刷新页面。');
        return;
    }

    // --- 常量 ---
    const LS_KEYS = 'readme-gen-keys';
    const LS_PROVIDER = 'readme-gen-provider';
    const LS_MODEL = 'readme-gen-model';
    const LS_SETTINGS = 'readme-gen-settings';
    const LS_THEME = 'readme-gen-theme';
    const LS_HISTORY = 'readme-gen-history';

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
    const cancelBtn = document.getElementById('cancel-btn');
    const copyBtn = document.getElementById('copy-btn');
    const themeToggle = document.getElementById('theme-toggle');
    const historySection = document.getElementById('history-section');
    const historyList = document.getElementById('history-list');
    const historyCount = document.getElementById('history-count');
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
    const settingIncludePatterns = document.getElementById('setting-include-patterns');
    const settingExcludePatterns = document.getElementById('setting-exclude-patterns');
    const settingBadgeStyle = document.getElementById('setting-badge-style');
    const settingTocDepth = document.getElementById('setting-toc-depth');
    const tocValue = document.getElementById('toc-value');
    const settingCodeExamples = document.getElementById('setting-code-examples');
    const settingLinkStyle = document.getElementById('setting-link-style');
    const settingSectionOrder = document.getElementById('setting-section-order');
    const settingAudience = document.getElementById('setting-audience');
    const feedbackInput = document.getElementById('feedback-input');
    const feedbackBtn = document.getElementById('feedback-btn');
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

    // --- 安全渲染（DOMPurify 可选） ---
    function safeRender(md) {
        const html = typeof marked.parse === 'function' ? marked.parse(md) : marked(md);
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(html);
        }
        const pre = document.createElement('pre');
        pre.textContent = md || '';
        return pre.outerHTML;
    }

    // ========== API Key 管理 ==========

    function loadSavedKeys() {
        try {
            return JSON.parse(keyStorage.getItem(LS_KEYS) || '{}');
        } catch {
            return {};
        }
    }

    function saveKeys(keys) {
        keyStorage.setItem(LS_KEYS, JSON.stringify(keys));
    }

    function loadSettings() {
        try {
            return JSON.parse(persistedStorage.getItem(LS_SETTINGS) || '{}');
        } catch {
            return {};
        }
    }

    function saveSettings(settings) {
        persistedStorage.setItem(LS_SETTINGS, JSON.stringify(settings));
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
        settingIncludePatterns.value = s.include_patterns || '';
        settingExcludePatterns.value = s.exclude_patterns || '';
        settingBadgeStyle.value = s.badge_style || 'shields';
        settingTocDepth.value = s.toc_depth ?? 2;
        tocValue.textContent = s.toc_depth ?? 2;
        settingCodeExamples.value = s.code_examples || 'normal';
        settingLinkStyle.value = s.link_style || 'inline';
        settingSectionOrder.value = s.section_order || '';
        settingAudience.value = s.audience || 'developer';
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
            include_patterns: settingIncludePatterns.value.trim(),
            exclude_patterns: settingExcludePatterns.value.trim(),
            badge_style: settingBadgeStyle.value,
            toc_depth: parseInt(settingTocDepth.value) || 2,
            code_examples: settingCodeExamples.value,
            link_style: settingLinkStyle.value,
            section_order: settingSectionOrder.value.trim(),
            audience: settingAudience.value,
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

    // 设置标签页切换
    document.querySelectorAll('.settings-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.settings-tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('stab-' + btn.dataset.stab).classList.add('active');
        });
    });

    // 渠道搜索过滤
    const providerSearch = document.getElementById('provider-search');
    providerSearch.addEventListener('input', () => {
        const q = providerSearch.value.toLowerCase();
        document.querySelectorAll('.provider-key-card').forEach(card => {
            const name = card.dataset.name || '';
            card.style.display = name.includes(q) ? '' : 'none';
        });
    });

    settingsBtn.addEventListener('click', () => openSettings());

    function openSettings() {
        applySettingsToUI();
        // 重置到第一个标签页
        document.querySelectorAll('.settings-tab').forEach((b, i) => b.classList.toggle('active', i === 0));
        document.querySelectorAll('.settings-tab-content').forEach((c, i) => c.classList.toggle('active', i === 0));
        providerSearch.value = '';

        const saved = loadSavedKeys();
        settingsBody.innerHTML = '';

        providersData.forEach(p => {
            const local = saved[p.name] || {};
            const hasEnvKey = p.is_configured;
            const hasLocalKey = !!local.api_key;
            const esc = escapeHtml;

            const card = document.createElement('div');
            card.className = 'provider-key-card';
            card.dataset.name = (p.name + ' ' + p.display_name).toLowerCase();
            card.innerHTML = `
                <details ${hasLocalKey || hasEnvKey ? 'open' : ''}>
                    <summary><strong>${esc(p.display_name)}</strong>
                        ${hasEnvKey ? '<span class="badge badge-env">环境变量</span>' : ''}
                        ${hasLocalKey ? '<span class="badge badge-local">本地</span>' : ''}
                    </summary>
                    <div class="form-inner">
                        <label for="key-${esc(p.name)}">API Key</label>
                        <input type="password" id="key-${esc(p.name)}" data-provider="${esc(p.name)}" data-field="api_key"
                               value="${esc(local.api_key || '')}" placeholder="${esc(p.env_key_hint || '输入 API Key')}">
                        <label for="base-${esc(p.name)}">Base URL</label>
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
        const savedProvider = persistedStorage.getItem(LS_PROVIDER);
        const savedModel = persistedStorage.getItem(LS_MODEL);

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
        persistedStorage.setItem(LS_PROVIDER, providerSelect.value);
    });

    modelInput.addEventListener('change', () => {
        persistedStorage.setItem(LS_MODEL, modelInput.value.trim());
    });

    modelInput.addEventListener('input', () => {
        clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(() => {
            persistedStorage.setItem(LS_MODEL, modelInput.value.trim());
        }, 500);
    });

    // 温度滑块实时显示
    settingTemperature.addEventListener('input', () => {
        tempValue.textContent = settingTemperature.value;
    });

    // 目录深度滑块实时显示
    settingTocDepth.addEventListener('input', () => {
        tocValue.textContent = settingTocDepth.value;
    });

    // ========== 反馈栏 ==========

    // 快捷反馈按钮
    document.querySelectorAll('.feedback-chips .chip').forEach(btn => {
        btn.addEventListener('click', () => {
            feedbackInput.value = btn.dataset.feedback;
            feedbackInput.focus();
        });
    });

    // 反馈提交
    feedbackBtn.addEventListener('click', () => {
        if (!feedbackInput.value.trim()) {
            feedbackInput.focus();
            return;
        }
        form.requestSubmit();
    });

    // Enter 提交, Ctrl+Enter 换行
    feedbackInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
            e.preventDefault();
            feedbackBtn.click();
        }
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

    function formatConnectionError(message, provider) {
        if (!message) return '连接失败';
        if (provider === 'ollama' && /Cannot reach Ollama/i.test(message)) {
            return `${message} 请先启动 Ollama，再重试「测试连接」。`;
        }
        if (/Base URL/i.test(message)) {
            return `${message} 请检查 Base URL 是否填写正确。`;
        }
        return message;
    }

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

    function showInfoStatus(msg) {
        clearTimeout(testStatusTimer);
        testStatus.style.display = '';
        testStatusText.textContent = msg;
        testStatusText.style.color = 'var(--pico-muted-color)';
        testStatusTimer = setTimeout(() => {
            testStatus.style.display = 'none';
        }, 2500);
    }

    function hideTestStatus() {
        clearTimeout(testStatusTimer);
        testStatus.style.display = 'none';
    }

    testBtn.addEventListener('click', async function () {
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
                showTestStatus(formatConnectionError(`[${data.code}] ${data.message}`, provider), true);
            }
        } catch (err) {
            showTestStatus('连接失败: ' + err.message, true);
        } finally {
            testBtn.disabled = false;
            testBtn.textContent = '测试连接';
        }
    });

    // ========== 表单提交与 SSE ==========

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideError();
        const feedbackText = feedbackInput.value.trim();
        const previousReadme = feedbackText ? (readmeSource.value || currentReadme) : '';
        previewSection.style.display = 'none';
        progressSection.style.display = '';
        resetSteps();
        generateBtn.setAttribute('aria-busy', 'true');
        generateBtn.disabled = true;
        currentReadme = '';
        readmePreview.innerHTML = '';
        readmeSource.value = '';

        cancelBtn.style.display = '';
        generateBtn.style.display = 'none';
        testBtn.style.display = 'none';

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
            include_patterns: savedSettings.include_patterns || '',
            exclude_patterns: savedSettings.exclude_patterns || '',
            feedback: feedbackText,
            previous_readme: previousReadme,
            badge_style: savedSettings.badge_style || 'shields',
            toc_depth: savedSettings.toc_depth ?? 2,
            code_examples: savedSettings.code_examples || 'normal',
            link_style: savedSettings.link_style || 'inline',
            section_order: savedSettings.section_order || '',
            audience: savedSettings.audience || 'developer',
        };

        currentAbortController = new AbortController();

        try {
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: currentAbortController.signal,
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
            if (err.name === 'AbortError') {
                hideError();
                showInfoStatus('生成已取消');
            } else {
                showError(`连接错误: ${err.message}`);
            }
        } finally {
            currentAbortController = null;
            generateBtn.removeAttribute('aria-busy');
            generateBtn.disabled = false;
            cancelBtn.style.display = 'none';
            generateBtn.style.display = '';
            testBtn.style.display = '';
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
                // 保存历史
                if (currentReadme) {
                    saveHistory({
                        timestamp: Date.now(),
                        folder_path: folderInput.value.trim(),
                        provider: data.provider || providerSelect.value,
                        model: data.model || modelInput.value,
                        readme: currentReadme,
                    });
                }
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

    downloadBtn.addEventListener('click', () => {
        const content = readmeSource.value || currentReadme;
        if (content) clientDownload(content);
    });

    // ========== 重新生成 ==========

    regenerateBtn.addEventListener('click', () => {
        feedbackInput.value = '';
        form.requestSubmit();
    });

    // ========== 工具函数 ==========

    function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[c]);
    }

    // ========== 深色模式 ==========

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        themeToggle.innerHTML = theme === 'dark' ? '&#9788;' : '&#9790;';
    }

    (function initTheme() {
        const saved = persistedStorage.getItem(LS_THEME);
        const theme = saved || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        applyTheme(theme);
    })();

    themeToggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        persistedStorage.setItem(LS_THEME, next);
    });

    // ========== 取消生成 ==========

    let currentAbortController = null;

    cancelBtn.addEventListener('click', () => {
        if (currentAbortController) {
            currentAbortController.abort();
            currentAbortController = null;
        }
    });

    // ========== 复制源码 ==========

    copyBtn.addEventListener('click', async () => {
        const text = readmeSource.value || currentReadme;
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            copyBtn.textContent = '已复制 ✓';
            setTimeout(() => { copyBtn.textContent = '复制源码'; }, 1500);
        } catch {
            // fallback
            readmeSource.select();
            document.execCommand('copy');
            copyBtn.textContent = '已复制 ✓';
            setTimeout(() => { copyBtn.textContent = '复制源码'; }, 1500);
        }
    });

    // ========== 客户端下载 ==========

    function clientDownload(content) {
        const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'README.md';
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    // ========== 历史记录 ==========

    function loadHistory() {
        try {
            return JSON.parse(persistedStorage.getItem(LS_HISTORY) || '[]');
        } catch { return []; }
    }

    function saveHistory(entry) {
        const history = loadHistory();
        history.unshift(entry);
        if (history.length > 10) history.length = 10;
        persistedStorage.setItem(LS_HISTORY, JSON.stringify(history));
        renderHistory();
    }

    function deleteHistory(index) {
        const history = loadHistory();
        history.splice(index, 1);
        persistedStorage.setItem(LS_HISTORY, JSON.stringify(history));
        renderHistory();
    }

    function renderHistory() {
        const history = loadHistory();
        if (history.length === 0) {
            historySection.style.display = 'none';
            return;
        }
        historySection.style.display = '';
        historyCount.textContent = `(${history.length})`;
        historyList.innerHTML = '';
        history.forEach((entry, i) => {
            const item = document.createElement('div');
            item.className = 'history-item';
            const date = new Date(entry.timestamp);
            const timeStr = date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
            item.innerHTML = `
                <span class="history-info">
                    <strong>${escapeHtml(entry.folder_path.split(/[\\/]/).pop() || entry.folder_path)}</strong>
                    <small>${timeStr} | ${escapeHtml(entry.provider)} | ${escapeHtml(entry.model)}</small>
                </span>
                <span class="history-actions">
                    <button class="small-btn" data-action="restore" data-index="${i}">恢复</button>
                    <button class="small-btn secondary" data-action="delete" data-index="${i}">删除</button>
                </span>
            `;
            historyList.appendChild(item);
        });

        historyList.querySelectorAll('[data-action="restore"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.index);
                const entry = loadHistory()[idx];
                if (entry) {
                    currentReadme = entry.readme;
                    readmePreview.innerHTML = safeRender(currentReadme);
                    readmeSource.value = currentReadme;
                    previewSection.style.display = '';
                }
            });
        });

        historyList.querySelectorAll('[data-action="delete"]').forEach(btn => {
            btn.addEventListener('click', () => {
                deleteHistory(parseInt(btn.dataset.index));
            });
        });
    }

    // ========== 初始化 ==========
    loadProviders();
    renderHistory();
})();
