// Subtle state feedback and one-time feature-card entrances.
export function mountEffects() {
  const setting = document.getElementById("motionEnabled");
  try {
    setting.checked = localStorage.getItem("research-motion") !== "off";
  } catch {}
  const apply = () => {
    document.body.classList.toggle("motion-disabled", !setting.checked);
    try {
      localStorage.setItem("research-motion", setting.checked ? "on" : "off");
    } catch {}
  };
  setting.addEventListener("change", apply);
  apply();
  if (typeof IntersectionObserver === "function") {
    const cards = [...document.querySelectorAll(".feature-grid .surface-card")];
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("feature-enter");
        observer.unobserve(entry.target);
      }
    }, { threshold: 0.15 });
    cards.forEach((card, index) => {
      card.style.setProperty("--feature-delay", `${index * 90}ms`);
      observer.observe(card);
    });
  }
}
