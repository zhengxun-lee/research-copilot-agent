const paths = {
  model: "M13 4H6a3 3 0 0 0-3 3v9a3 3 0 0 0 3 3h2v3l4-3h6a3 3 0 0 0 3-3v-4M18 2l1.3 3.7L23 7l-3.7 1.3L18 12l-1.3-3.7L13 7l3.7-1.3ZM7 11h4M7 15h9",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  eyeOff:
    "m3 3 18 18M10.6 5.1 12 5c6.5 0 10 7 10 7a20 20 0 0 1-3 3.8M6.1 6.1A22 22 0 0 0 2 12s3.5 7 10 7a11 11 0 0 0 5.9-1.9M9.9 9.9a3 3 0 0 0 4.2 4.2",
  plus: "M12 5v14M5 12h14",
  search: "m21 21-5-5M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15Z",
  terminal: "m5 7 5 5-5 5M13 17h6",
  library: "M4 4h4v16H4zM11 4h3v16h-3zM17 4l3-1 4 16-3 1Z",
  flask: "M9 3h6M10 3v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M8 15h8",
  activity: "M2 12h5l3-8 4 16 3-8h5",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z",
  folder: "M3 6h7l2 2h9v12H3Z",
  orbit:
    "M12 3a9 9 0 1 0 9 9M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18Zm9 0v5h-5",
  panel: "M3 4h18v16H3ZM9 4v16",
  inspect: "M3 4h18v16H3ZM15 4v16M18 8h1M18 12h1",
  sparkles:
    "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM21 2v4M19 4h4",
  send: "m5 12 7-7 7 7M12 5v15",
  refresh: "M3 11a9 9 0 1 1 2 7M3 4v7h7",
  upload: "M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6",
  layers: "m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5",
  play: "m8 4 12 8-12 8Z",
  download: "M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5",
  route: "M4 4h5v5H4ZM15 15h5v5h-5ZM9 6h8v9M6 9v9h9",
  file: "M6 3h8l4 4v14H6ZM14 3v5h4M9 13h6M9 17h4",
  check: "m5 12 4 4L19 6",
  tool: "m14 6 4 4M4 20l7-7M14 3a6 6 0 0 0-3 10 6 6 0 0 0 10-3l-4 2-5-5Z",
  message: "M3 4h18v13H8l-5 4Z",
  cpu: "M6 6h12v12H6ZM9 9h6v6H9ZM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4",
};
export function icon(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.layers}"/></svg>`;
}
export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icon(el.dataset.icon);
  });
}
