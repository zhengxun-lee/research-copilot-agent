// The workspace uses a single light palette, including existing installations.
document.documentElement.dataset.theme = "light";
try {
  localStorage.removeItem("research-console-theme");
} catch {}
