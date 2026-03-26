(function () {
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) {
            return parts.pop().split(';').shift();
        }
        return '';
    }

    function setStatus(element, message, tone = 'idle') {
        if (!element) return;
        element.textContent = message;
        element.className = 'inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium';

        const toneClasses = {
            idle: 'bg-slate-100 text-slate-600',
            loading: 'bg-amber-50 text-amber-700',
            success: 'bg-emerald-50 text-emerald-700',
            error: 'bg-rose-50 text-rose-700',
        };

        element.className += ` ${toneClasses[tone] || toneClasses.idle}`;
    }

    function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('Не удалось прочитать файл.'));
            reader.readAsDataURL(file);
        });
    }

    function setButtonBusy(button, busy) {
        if (!button) return;
        button.disabled = busy;
        button.classList.toggle('opacity-60', busy);
        button.classList.toggle('cursor-not-allowed', busy);
    }

    async function postTryOn(endpoint, payload) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json().catch(() => ({ ok: false, error: 'Сервер вернул некорректный ответ.' }));
        if (!response.ok || !data.ok) {
            const error = new Error(data.error || 'Не удалось выполнить AI-примерку.');
            error.response = data;
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function updateQuotaBadge(element, quota, totalLimit) {
        if (!element) return;
        const totalRemaining = Number.isFinite(Number(quota?.total_remaining))
            ? Number(quota.total_remaining)
            : Number.isFinite(Number(quota?.remaining_generations))
                ? Number(quota.remaining_generations)
                : 0;
        const monthlyRemaining = Number.isFinite(Number(quota?.monthly_remaining))
            ? Number(quota.monthly_remaining)
            : totalRemaining;
        const extraAvailable = Number.isFinite(Number(quota?.extra_available))
            ? Number(quota.extra_available)
            : 0;
        const numericTotal = Number.isFinite(Number(totalLimit)) ? Number(totalLimit) : null;

        if (numericTotal !== null) {
            element.textContent = `Осталось бесплатных генераций: ${totalRemaining} из ${numericTotal} + дополнительных: ${extraAvailable}`;
        } else {
            element.textContent = `Осталось ${totalRemaining}: включено ${monthlyRemaining} · доп. ${extraAvailable}`;
        }
    }

    function setFrameAspectRatio(frameElement, ratio) {
        if (!frameElement || !Number.isFinite(ratio) || ratio <= 0) return;
        frameElement.style.setProperty('--preview-ratio', String(ratio));
    }

    function resolveFrameRatioFromImage(dataUrl) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => {
                if (!image.naturalWidth || !image.naturalHeight) {
                    reject(new Error('Не удалось определить размер изображения.'));
                    return;
                }
                resolve(image.naturalWidth / image.naturalHeight);
            };
            image.onerror = () => reject(new Error('Не удалось определить размер изображения.'));
            image.src = dataUrl;
        });
    }

    window.RucodelTryOn = {
        create(config) {
            const photoInput = document.getElementById(config.photoInputId);
            const userPhoto = document.getElementById(config.userPhotoId);
            const aiPhoto = document.getElementById(config.aiPhotoId);
            const statusEl = document.getElementById(config.statusId);
            const buttonEl = document.getElementById(config.buttonId);
            const downloadEl = document.getElementById(config.downloadLinkId);
            const warningEl = document.getElementById(config.warningId);
            const quotaEl = config.quotaId ? document.getElementById(config.quotaId) : null;
            const userFrame = userPhoto?.closest('[data-tryon-frame]') || null;
            const aiFrame = aiPhoto?.closest('[data-tryon-frame]') || null;
            const initialResultPlaceholder = config.initialResultPlaceholder || aiPhoto?.getAttribute('src') || '';

            let userImageDataUrl = config.initialUserImage || null;
            let quota = {
                monthly_limit: Number(config.monthlyLimit || 0),
                monthly_remaining: Number(config.monthlyRemaining ?? config.remainingGenerations ?? 0),
                extra_available: Number(config.extraRemaining || 0),
                total_remaining: Number(config.remainingGenerations || 0),
            };
            const monthlyLimit = Number(config.monthlyLimit || 0);
            const isAuthenticated = Boolean(config.isAuthenticated);
            const canGenerate = config.canGenerate === undefined ? isAuthenticated : Boolean(config.canGenerate);
            const disabledReason = config.disabledReason || 'Генерация временно недоступна.';
            const loginUrl = config.loginUrl || '/login/';

            function syncQuotaUi() {
                updateQuotaBadge(quotaEl, quota, monthlyLimit);
                if (!buttonEl) return;

                const shouldDisable = !canGenerate || Number(quota.total_remaining || 0) <= 0;
                buttonEl.disabled = shouldDisable;
                buttonEl.classList.toggle('opacity-60', shouldDisable);
                buttonEl.classList.toggle('cursor-not-allowed', shouldDisable);
            }

            function resetResultPreview() {
                if (aiPhoto) {
                    aiPhoto.src = initialResultPlaceholder;
                }
                if (downloadEl) {
                    downloadEl.classList.add('hidden');
                    downloadEl.href = '#';
                }
            }

            async function syncPreviewFrames(dataUrl) {
                try {
                    const ratio = await resolveFrameRatioFromImage(dataUrl);
                    setFrameAspectRatio(userFrame, ratio);
                    setFrameAspectRatio(aiFrame, ratio);
                } catch (error) {
                    console.warn(error);
                }
            }

            function applyUserImage(dataUrl) {
                userImageDataUrl = dataUrl;
                if (userPhoto) userPhoto.src = dataUrl;
                syncPreviewFrames(dataUrl);
                resetResultPreview();
                if (typeof config.onUserImageChange === 'function') {
                    config.onUserImageChange(dataUrl);
                }
            }

            if (userImageDataUrl) {
                applyUserImage(userImageDataUrl);
            } else {
                resetResultPreview();
            }

            if (!isAuthenticated) {
                setStatus(statusEl, 'AI-примерка доступна только после входа в аккаунт.', 'idle');
            } else if (!canGenerate) {
                setStatus(statusEl, disabledReason, 'idle');
            } else if (Number(quota.total_remaining || 0) <= 0) {
                setStatus(statusEl, 'Включённый лимит закончился. Купите доп. генерацию на отдельной странице.', 'error');
            } else if (!userImageDataUrl) {
                setStatus(statusEl, 'Загрузите фото, затем запустите примерку.', 'idle');
            } else {
                setStatus(statusEl, 'Фото загружено. Можно запускать AI-примерку.', 'idle');
            }

            syncQuotaUi();

            if (photoInput) {
                photoInput.addEventListener('change', async (event) => {
                    const file = event.target.files && event.target.files[0];
                    if (!file) return;
                    try {
                        const dataUrl = await fileToDataUrl(file);
                        applyUserImage(dataUrl);
                        if (warningEl) warningEl.textContent = '';
                        if (canGenerate && Number(quota.total_remaining || 0) > 0) {
                            setStatus(statusEl, 'Фото загружено. Можно запускать AI-примерку.', 'idle');
                        }
                    } catch (error) {
                        setStatus(statusEl, error.message || 'Не удалось загрузить фото.', 'error');
                    }
                });
            }

            async function generate() {
                if (!isAuthenticated) {
                    window.location.href = loginUrl;
                    return;
                }

                if (!canGenerate) {
                    setStatus(statusEl, disabledReason, 'error');
                    return;
                }

                if (Number(quota.total_remaining || 0) <= 0) {
                    setStatus(statusEl, 'Включённый лимит закончился. Купите доп. генерацию на отдельной странице.', 'error');
                    return;
                }

                if (!userImageDataUrl) {
                    setStatus(statusEl, 'Сначала загрузите фото пользователя.', 'error');
                    return;
                }

                setButtonBusy(buttonEl, true);
                setStatus(statusEl, 'Генерируем примерку на сервере…', 'loading');
                if (warningEl) warningEl.textContent = '';

                try {
                    const accessoryImage = await config.getAccessoryImage();
                    if (!accessoryImage) {
                        throw new Error('Не удалось получить изображение изделия из конструктора.');
                    }

                    const payload = {
                        category: config.category,
                        user_image: userImageDataUrl,
                        accessory_image: accessoryImage,
                        summary: config.getSummary ? config.getSummary() : '',
                        selections: config.getSelections ? config.getSelections() : {},
                    };

                    const data = await postTryOn(config.endpoint || '/api/tryon/', payload);

                    if (aiPhoto) aiPhoto.src = data.result_image;
                    if (downloadEl) {
                        downloadEl.href = data.result_image;
                        downloadEl.classList.remove('hidden');
                    }

                    if (warningEl && Array.isArray(data.warnings) && data.warnings.length) {
                        warningEl.textContent = data.warnings.join(' ');
                    } else if (warningEl && !data.used_ai) {
                        warningEl.textContent = 'AI недоступен, поэтому показан серверный fallback-рендер.';
                    }

                    if (data.quota) {
                        quota = data.quota;
                        syncQuotaUi();
                    } else if (typeof data.remaining_generations === 'number') {
                        quota.total_remaining = data.remaining_generations;
                        syncQuotaUi();
                    }

                    let providerLabel = data.provider === 'openai' ? 'AI-рендер завершён' : 'Готово (fallback)';
                    if (data.generation?.consumed_extra_credit) {
                        providerLabel += ' · списана 1 доп. генерация';
                    }
                    setStatus(statusEl, providerLabel, 'success');

                    if (typeof config.onResult === 'function') {
                        config.onResult(data);
                    }
                } catch (error) {
                    if (error.status === 401 && error.response?.login_url) {
                        window.location.href = error.response.login_url;
                        return;
                    }
                    if (error.response?.quota) {
                        quota = error.response.quota;
                        syncQuotaUi();
                    } else if (typeof error.response?.remaining_generations === 'number') {
                        quota.total_remaining = error.response.remaining_generations;
                        syncQuotaUi();
                    }
                    setStatus(statusEl, error.message || 'Не удалось выполнить примерку.', 'error');
                } finally {
                    setButtonBusy(buttonEl, false);
                    syncQuotaUi();
                }
            }

            if (buttonEl) {
                buttonEl.addEventListener('click', generate);
            }

            return {
                setUserImage: applyUserImage,
                getUserImage() {
                    return userImageDataUrl;
                },
                resetResultPreview,
                generate,
            };
        },
    };
})();
