import { api } from "./api.js";
import { loadLibrary, renderLibrary, setDirectorySearchOpen, syncDirectorySearchUI } from "./library.js";
import { initializeResizableLayout, toggleComposerCollapsed } from "./layout.js";
import {
  appendMessage,
  pollJob,
  refreshChatPinState,
  renderMessages,
  resumeActiveJobs,
  setSubmitting,
  updateJobChip,
  updateJumpLatestButton,
} from "./jobs.js";
import { selectPaper } from "./paper_detail.js";
import {
  activateProfile,
  clearProfileForm,
  deleteProfile,
  handleProfileClick,
  logoutOpenReview,
  saveProfile,
  setSettingsModalOpen,
  submitOpenReviewLogin,
} from "./settings.js";
import { bindElements, elements, restoreConversationState, state } from "./state.js";

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  initializeResizableLayout();
  restoreConversationState();
  bindEvents();
  await loadLibrary();
  renderMessages();
  updateJobChip();
  void resumeActiveJobs();
});

function bindEvents() {
  elements.libraryFilter.addEventListener("input", (event) => {
    state.filter = event.target.value.trim().toLowerCase();
    syncDirectorySearchUI();
    renderLibrary();
  });

  elements.directorySearchToggle.addEventListener("click", () => {
    setDirectorySearchOpen(!state.directorySearchOpen, { focusInput: !state.directorySearchOpen });
  });

  elements.directorySearchClose.addEventListener("click", () => {
    setDirectorySearchOpen(false, { restoreFocus: true });
  });

  elements.settingsButton.addEventListener("click", () => {
    setSettingsModalOpen(true);
  });

  elements.settingsClose.addEventListener("click", () => {
    setSettingsModalOpen(false);
  });

  elements.settingsModal.addEventListener("click", (event) => {
    if (event.target === elements.settingsModal) {
      setSettingsModalOpen(false);
    }
  });

  elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveProfile();
  });

  elements.settingsNewProfile.addEventListener("click", () => {
    clearProfileForm();
  });

  elements.settingsDeleteProfile.addEventListener("click", async () => {
    await deleteProfile();
  });

  elements.profileList.addEventListener("click", (event) => {
    const pill = event.target.closest("[data-profile-id]");
    if (!pill || !elements.profileList.contains(pill)) {
      return;
    }
    const profileId = pill.getAttribute("data-profile-id");
    handleProfileClick(profileId);
  });

  elements.openreviewAuthForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitOpenReviewLogin();
  });

  elements.openreviewLogoutButton.addEventListener("click", async () => {
    await logoutOpenReview();
  });

  elements.libraryTree.addEventListener("click", (event) => {
    const button = event.target.closest("[data-paper-id]");
    if (!button || !elements.libraryTree.contains(button)) {
      return;
    }
    void selectPaper(button.getAttribute("data-paper-id"));
  });

  elements.majorRail.addEventListener("click", (event) => {
    const button = event.target.closest("[data-major-topic]");
    if (!button || !elements.majorRail.contains(button)) {
      return;
    }
    state.activeMajorTopic = button.getAttribute("data-major-topic");
    state.activeMinorTopic = "__all__";
    renderLibrary();
  });

  elements.minorTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-minor-topic]");
    if (!button || !elements.minorTabs.contains(button)) {
      return;
    }
    state.activeMinorTopic = button.getAttribute("data-minor-topic") || "__all__";
    renderLibrary();
  });

  elements.chatFeed.addEventListener("scroll", () => {
    refreshChatPinState();
  });

  elements.jumpLatestButton.addEventListener("click", () => {
    elements.chatFeed.scrollTo({
      top: elements.chatFeed.scrollHeight,
      behavior: "smooth",
    });
    state.chatPinnedToBottom = true;
    state.chatHasUnseenUpdates = false;
    updateJumpLatestButton();
  });

  elements.composerCollapseButton.addEventListener("click", () => {
    toggleComposerCollapsed();
  });

  elements.composerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = elements.promptInput.value.trim();
    if (!prompt) {
      return;
    }

    appendMessage({
      id: `user-${Date.now()}`,
      kind: "text",
      role: "user",
      text: prompt,
    }, { forceBottom: true });

    const maxResultsValue = elements.maxResultsInput.value.trim();
    const payload = {
      prompt,
      refresh_existing: elements.refreshExistingInput.checked,
      max_results: maxResultsValue ? Number(maxResultsValue) : null,
    };

    setSubmitting(true);
    try {
      const response = await api("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      appendMessage({
        id: `job-${response.job.id}`,
        kind: "job",
        role: "assistant",
        job: response.job,
      }, { forceBottom: true });
      elements.promptInput.value = "";
      pollJob(response.job.id);
    } catch (error) {
      appendMessage({
        id: `error-${Date.now()}`,
        kind: "error",
        role: "assistant",
        text: error.message,
      }, { forceBottom: true });
    } finally {
      setSubmitting(false);
      updateJobChip();
    }
  });

  elements.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      elements.composerForm.requestSubmit();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.settingsModalOpen) {
      setSettingsModalOpen(false);
      return;
    }
    if (event.key !== "Escape" || !state.directorySearchOpen) {
      return;
    }
    setDirectorySearchOpen(false, { restoreFocus: true });
  });

  document.addEventListener("click", (event) => {
    if (!state.directorySearchOpen) {
      return;
    }
    const target = event.target;
    if (
      elements.directorySearchPanel.contains(target)
      || elements.directorySearchToggle.contains(target)
    ) {
      return;
    }
    setDirectorySearchOpen(false);
  });
}

export async function bootstrapForTests() {
  bindElements();
  initializeResizableLayout();
  restoreConversationState();
  bindEvents();
  await loadLibrary();
  renderMessages();
  updateJobChip();
  void resumeActiveJobs();
}

export { activateProfile };
