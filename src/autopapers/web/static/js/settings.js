import { api } from "./api.js";
import { renderStats, syncDirectorySearchUI } from "./library.js";
import { updateJobChip, showToast } from "./jobs.js";
import { elements, escapeHtml, state } from "./state.js";

export function renderAppChrome() {
  elements.modelChip.textContent = state.app?.model || "Unknown model";
  renderSettingsButtonState();
  if (!state.app?.api_key_configured) {
    elements.statusBanner.classList.remove("hidden");
    elements.statusBanner.textContent = "当前未配置 API Key。点击 Settings 按钮进行配置。";
  } else {
    elements.statusBanner.classList.add("hidden");
    elements.statusBanner.textContent = "";
  }
  updateJobChip();
  renderStats();
  syncDirectorySearchUI();
}

export function renderSettingsButtonState() {
  const apiKeyConfigured = Boolean(state.app?.api_key_configured);
  const openreviewStatus = state.app?.openreview || {};
  const orAuthenticated = Boolean(openreviewStatus.authenticated);
  elements.settingsButton.classList.remove("chip-active", "chip-warning", "chip-disabled");
  if (!apiKeyConfigured) {
    elements.settingsButton.classList.add("chip-warning");
  } else if (orAuthenticated) {
    elements.settingsButton.classList.add("chip-active");
  }
  elements.settingsButton.disabled = false;
  renderOpenReviewAuthState();
}

export function renderOpenReviewAuthState() {
  const status = state.app?.openreview || {};
  const authenticated = Boolean(status.authenticated);
  const available = status.available !== false;
  if (!available) {
    elements.openreviewAuthStatusCopy.textContent = "当前环境未安装 OpenReview 客户端。";
    elements.openreviewLogoutButton.disabled = true;
    return;
  }
  elements.openreviewAuthStatusCopy.textContent = authenticated
    ? `当前已登录：${status.username || "unknown"}。登录 token 已保存在本地。`
    : "登录后会把 token 保存到本地，仅当前机器使用。";
  elements.openreviewLogoutButton.disabled = !authenticated || state.openreviewAuthSubmitting;
  elements.openreviewLoginSubmit.disabled = state.openreviewAuthSubmitting;
}

export function setSettingsModalOpen(isOpen) {
  state.settingsModalOpen = Boolean(isOpen);
  elements.settingsModal.classList.toggle("hidden", !state.settingsModalOpen);
  elements.settingsModal.setAttribute("aria-hidden", state.settingsModalOpen ? "false" : "true");
  if (state.settingsModalOpen) {
    void loadSettingsForm();
    window.setTimeout(() => {
      elements.settingsApiKey?.focus();
    }, 0);
  }
}

export async function loadSettingsForm() {
  try {
    const payload = await api("/api/settings");
    state.profileData = payload;
    renderProfileList();
    state.app = state.app || {};
    state.app.openreview = payload.openreview;
    renderOpenReviewAuthState();
    const activeId = payload.active_profile;
    if (activeId && payload.profiles[activeId]) {
      loadProfileIntoForm(activeId, payload.profiles[activeId]);
    } else {
      clearProfileForm();
    }
  } catch (error) {
    showToast(`加载设置失败：${error.message}`, "warning");
  }
}

export function renderProfileList() {
  const data = state.profileData || {};
  const profiles = data.profiles || {};
  const activeId = data.active_profile || "";
  const editingId = elements.settingsProfileId.value || "";
  if (!Object.keys(profiles).length) {
    elements.profileList.innerHTML = `<span class="muted">尚未保存任何 API 配置。</span>`;
    return;
  }
  elements.profileList.innerHTML = Object.entries(profiles).map(([id, profile]) => {
    const classes = ["profile-pill"];
    if (id === activeId) classes.push("active");
    if (id === editingId) classes.push("editing");
    return `<button class="${classes.join(" ")}" type="button" data-profile-id="${escapeHtml(id)}"><span class="profile-pill-dot"></span><span class="profile-pill-name">${escapeHtml(profile.name || profile.model || "Unnamed")}</span></button>`;
  }).join("");
}

export function loadProfileIntoForm(id, profile) {
  elements.settingsProfileId.value = id;
  elements.settingsProfileName.value = profile.name || "";
  elements.settingsApiKey.value = "";
  elements.settingsApiKey.placeholder = profile.api_key_masked
    ? `${profile.api_key_masked}（留空保持不变）`
    : "API Key";
  elements.settingsModel.value = profile.model || "";
  elements.settingsApiUrl.value = profile.api_url || "";
  elements.settingsProxy.value = profile.network_proxy_url || "";
  renderProfileList();
}

export function clearProfileForm() {
  elements.settingsProfileId.value = "";
  elements.settingsProfileName.value = "";
  elements.settingsApiKey.value = "";
  elements.settingsApiKey.placeholder = "API Key";
  elements.settingsModel.value = "";
  elements.settingsApiUrl.value = "";
  elements.settingsProxy.value = "";
  renderProfileList();
}

export async function handleProfileClick(profileId) {
  const data = state.profileData || {};
  const profiles = data.profiles || {};
  const profile = profiles[profileId];
  if (!profile) {
    return;
  }
  const activeId = data.active_profile || "";
  if (profileId === activeId) {
    loadProfileIntoForm(profileId, profile);
    return;
  }
  await activateProfile(profileId);
}

export async function activateProfile(profileId) {
  if (state.settingsSubmitting) {
    return;
  }
  const data = state.profileData || {};
  const profile = (data.profiles || {})[profileId];
  if (!profile) {
    return;
  }
  state.settingsSubmitting = true;
  elements.settingsSave.disabled = true;
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "activate", profile_id: profileId }),
    });
    state.profileData = result.profiles_data;
    state.app = result.app;
    const activeProfile = result.profiles_data?.profiles?.[profileId];
    if (activeProfile) {
      loadProfileIntoForm(profileId, activeProfile);
    } else {
      renderProfileList();
    }
    renderAppChrome();
    showToast(`已切换到「${profile.name || profile.model || "Unnamed"}」。`, "info");
  } catch (error) {
    showToast(`切换失败：${error.message}`, "warning");
  } finally {
    state.settingsSubmitting = false;
    elements.settingsSave.disabled = false;
  }
}

export async function saveProfile() {
  if (state.settingsSubmitting) {
    return;
  }
  const editingId = elements.settingsProfileId.value || "";
  const currentProfile = editingId ? (state.profileData?.profiles || {})[editingId] : null;
  const hasStoredApiKey = Boolean(currentProfile?.api_key_masked);
  const name = elements.settingsProfileName.value.trim();
  const apiKey = elements.settingsApiKey.value;
  const model = elements.settingsModel.value.trim();
  const apiUrl = elements.settingsApiUrl.value.trim();
  const proxy = elements.settingsProxy.value.trim();
  if (!apiKey && !hasStoredApiKey && !model && !apiUrl) {
    showToast("请至少填写 API Key 或 Model。", "warning");
    return;
  }
  state.settingsSubmitting = true;
  elements.settingsSave.disabled = true;
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save",
        profile_id: elements.settingsProfileId.value || null,
        profile: { name, api_key: apiKey, model, api_url: apiUrl, network_proxy_url: proxy },
      }),
    });
    state.profileData = result.profiles_data;
    state.app = result.app;
    renderProfileList();
    if (result.saved_id && result.profiles_data.profiles[result.saved_id]) {
      loadProfileIntoForm(result.saved_id, result.profiles_data.profiles[result.saved_id]);
    }
    renderAppChrome();
    showToast("配置已保存并激活。", "info");
  } catch (error) {
    showToast(`保存失败：${error.message}`, "warning");
  } finally {
    state.settingsSubmitting = false;
    elements.settingsSave.disabled = false;
  }
}

export async function deleteProfile() {
  const profileId = elements.settingsProfileId.value;
  if (!profileId) {
    showToast("请先选择一个配置。", "warning");
    return;
  }
  const name = elements.settingsProfileName.value || "该配置";
  if (!window.confirm(`确定删除「${name}」？`)) {
    return;
  }
  if (state.settingsSubmitting) {
    return;
  }
  state.settingsSubmitting = true;
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete", profile_id: profileId }),
    });
    state.profileData = result.profiles_data;
    state.app = result.app;
    const newActiveId = result.profiles_data.active_profile;
    if (newActiveId && result.profiles_data.profiles[newActiveId]) {
      loadProfileIntoForm(newActiveId, result.profiles_data.profiles[newActiveId]);
    } else {
      clearProfileForm();
    }
    renderAppChrome();
    showToast("配置已删除。", "info");
  } catch (error) {
    showToast(`删除失败：${error.message}`, "warning");
  } finally {
    state.settingsSubmitting = false;
  }
}

export async function submitOpenReviewLogin() {
  if (state.openreviewAuthSubmitting) {
    return;
  }
  const username = elements.openreviewUsernameInput.value.trim();
  const password = elements.openreviewPasswordInput.value;
  if (!username || !password) {
    showToast("请输入 OpenReview 用户名和密码。", "warning");
    return;
  }
  state.openreviewAuthSubmitting = true;
  renderOpenReviewAuthState();
  try {
    const payload = await api("/api/openreview/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    state.app = payload.app;
    elements.openreviewPasswordInput.value = "";
    elements.openreviewUsernameInput.value = "";
    renderAppChrome();
    showToast("OpenReview 登录成功。", "info");
  } catch (error) {
    showToast(error.message, "warning");
  } finally {
    state.openreviewAuthSubmitting = false;
    renderOpenReviewAuthState();
  }
}

export async function logoutOpenReview() {
  if (state.openreviewAuthSubmitting) {
    return;
  }
  state.openreviewAuthSubmitting = true;
  renderOpenReviewAuthState();
  try {
    const payload = await api("/api/openreview/logout", { method: "POST" });
    state.app = payload.app;
    elements.openreviewPasswordInput.value = "";
    renderAppChrome();
    showToast("OpenReview 已退出登录。", "info");
  } catch (error) {
    showToast(error.message, "warning");
  } finally {
    state.openreviewAuthSubmitting = false;
    renderOpenReviewAuthState();
  }
}
