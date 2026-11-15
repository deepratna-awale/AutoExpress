// Choices saved before the rename (keys starting "autoexpress-") carry over to the new keys.
export function migrateLegacyStorage() {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith("autoexpress-")) continue;
      const renamed = "emotica-" + key.slice("autoexpress-".length);
      const value = localStorage.getItem(key);
      if (value !== null && localStorage.getItem(renamed) === null) localStorage.setItem(renamed, value);
    }
  } catch {
    // Storage can be blocked or unavailable (static rendering); nothing to carry over then.
  }
}

if (typeof window !== "undefined") migrateLegacyStorage();
