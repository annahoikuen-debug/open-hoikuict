/**
 * 保育ICT 汎用ローカル自動保存 (Autosave) & クイックチップ共通ライブラリ
 */
(() => {
  const HoikuAutosave = {
    /**
     * フォームの自動保存を初期化
     * @param {Object} options
     * @param {HTMLFormElement|string} options.form フォーム要素またはセレクタ
     * @param {string} options.storageKey 保存先 localStorage キー名
     * @param {HTMLElement|string} [options.banner] 復元通知バナー要素またはセレクタ
     * @param {Array<string>} [options.fields] 保存対象のフィールド名配列（未指定時はフォーム内全要素）
     * @param {number} [options.delay=700] デバウンス遅延時間(ms)
     */
    bind(options) {
      try {
        const form = typeof options.form === "string" ? document.querySelector(options.form) : options.form;
        if (!form) return null;

        const storageKey = options.storageKey;
        if (!storageKey) return null;

        const banner = typeof options.banner === "string" ? document.querySelector(options.banner) : options.banner;
        const delay = options.delay || 700;
        let timer = null;

        const getFields = () => {
          if (options.fields && options.fields.length > 0) {
            return options.fields.map(name => form.querySelector(`[name="${name}"]`)).filter(Boolean);
          }
          return Array.from(form.querySelectorAll("input:not([type=hidden]):not([type=password]):not([type=submit]), textarea, select"));
        };

        // --- 保存処理 ---
        const save = () => {
          try {
            const data = {
              updatedAt: Date.now(),
              fields: {}
            };
            const inputs = getFields();
            inputs.forEach(el => {
              const name = el.name;
              if (!name) return;
              if (el.type === "radio") {
                const checked = form.querySelector(`[name="${name}"]:checked`);
                data.fields[name] = checked ? checked.value : "";
              } else if (el.type === "checkbox") {
                data.fields[name] = el.checked;
              } else {
                data.fields[name] = el.value;
              }
            });

            // 何らかの有意な入力がある場合のみ保存
            const hasValue = Object.values(data.fields).some(v => (typeof v === "string" ? v.trim().length > 0 : Boolean(v)));
            if (hasValue) {
              localStorage.setItem(storageKey, JSON.stringify(data));
            }
          } catch (_) {}
        };

        const triggerSave = () => {
          clearTimeout(timer);
          timer = setTimeout(save, delay);
        };

        form.addEventListener("input", triggerSave);
        form.addEventListener("change", triggerSave);

        // --- 復元処理 ---
        try {
          const raw = localStorage.getItem(storageKey);
          if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.fields) {
              let restoredCount = 0;
              Object.entries(parsed.fields).forEach(([name, val]) => {
                if (val === undefined || val === null || val === "") return;
                const el = form.querySelector(`[name="${name}"]`);
                if (!el) return;

                if (el.type === "radio") {
                  const radio = form.querySelector(`[name="${name}"][value="${val}"]`);
                  if (radio && !radio.checked) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event("change", { bubbles: true }));
                    restoredCount++;
                  }
                } else if (el.type === "checkbox") {
                  if (el.checked !== Boolean(val)) {
                    el.checked = Boolean(val);
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    restoredCount++;
                  }
                } else if (!el.value || el.value.trim().length === 0) {
                  el.value = val;
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                  restoredCount++;
                }
              });

              if (restoredCount > 0 && banner) {
                banner.classList.remove("hidden");
                const btnDiscard = banner.querySelector("[data-autosave-discard]");
                if (btnDiscard) {
                  btnDiscard.addEventListener("click", () => {
                    localStorage.removeItem(storageKey);
                    window.location.reload();
                  });
                }
              }
            }
          }
        } catch (_) {}

        // 送信時にローカル下書きをクリア
        form.addEventListener("submit", () => {
          try {
            localStorage.removeItem(storageKey);
          } catch (_) {}
        });

        return {
          save,
          clear: () => localStorage.removeItem(storageKey)
        };
      } catch (_) {
        return null;
      }
    },

    /**
     * ページ内の定型文チップを自動バインド
     */
    bindPhraseChips() {
      document.querySelectorAll("[data-phrase-target]").forEach(container => {
        const targetName = container.dataset.phraseTarget;
        const targetEl = document.querySelector(`[name="${targetName}"]`) || document.getElementById(targetName);
        if (!targetEl) return;

        container.querySelectorAll("[data-insert-phrase]").forEach(btn => {
          btn.addEventListener("click", () => {
            const text = btn.dataset.insertPhrase;
            if (!text) return;
            const cur = targetEl.value || "";
            if (!cur.trim()) {
              targetEl.value = text;
            } else if (cur.includes(text)) {
              return; // 重複挿入防止
            } else {
              targetEl.value = `${cur.trim()}\n${text}`;
            }
            targetEl.dispatchEvent(new Event("input", { bubbles: true }));
            targetEl.focus();
          });
        });
      });
    },

    /**
     * DOM読み込み完了時に自動検出してバインド
     */
    autoInit() {
      // 1. 定型フレーズチップをバインド
      this.bindPhraseChips();

      // 2. data-autosave-key を持つ要素からフォームを検出して自動初期化
      document.querySelectorAll("[data-autosave-key]").forEach(banner => {
        const key = banner.dataset.autosaveKey;
        if (!key) return;
        // バナーの直近または同一スコープのフォーム
        const form = banner.closest("form") || document.querySelector("form");
        if (form && !form.dataset.autosaveInitialized) {
          form.dataset.autosaveInitialized = "true";
          this.bind({
            form,
            storageKey: key,
            banner
          });
        }
      });
    }
  };

  window.HoikuAutosave = HoikuAutosave;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => HoikuAutosave.autoInit());
  } else {
    HoikuAutosave.autoInit();
  }
})();
