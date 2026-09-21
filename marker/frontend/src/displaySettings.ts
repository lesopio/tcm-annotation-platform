export type DisplaySettings = {
  theme: "paper" | "light" | "dark";
  density: "comfortable" | "compact";
  motion: "standard" | "reduced";
};

const STORAGE_KEY = "bencao_display_settings";
const defaults: DisplaySettings = { theme: "paper", density: "comfortable", motion: "standard" };

export function loadDisplaySettings(): DisplaySettings {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return {
      theme: ["paper", "light", "dark"].includes(value.theme) ? value.theme : defaults.theme,
      density: ["comfortable", "compact"].includes(value.density) ? value.density : defaults.density,
      motion: ["standard", "reduced"].includes(value.motion) ? value.motion : defaults.motion,
    };
  } catch {
    return defaults;
  }
}

export function applyDisplaySettings(value: DisplaySettings): void {
  document.documentElement.dataset.theme = value.theme;
  document.documentElement.dataset.density = value.density;
  document.documentElement.dataset.motion = value.motion;
}

export function saveDisplaySettings(value: DisplaySettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  applyDisplaySettings(value);
}
