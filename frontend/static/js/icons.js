// Line icons, drawn on a 24-unit grid with a 1.75 stroke in the current text colour.

import { s } from "./dom.js";

const PATHS = {
  play: "M7 5.5v13l11-6.5z",
  pause: "M8 5v14M16 5v14",
  back: "M18 6l-8 6 8 6M6 6v12",
  forward: "M6 6l8 6-8 6M18 6v12",
  start: "M19 6l-7 6 7 6M12 6l-7 6 7 6",
  end: "M5 6l7 6-7 6M12 6l7 6-7 6",
  eye: "M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6z",
  ear: "M7 10a5 5 0 0 1 10 0c0 3-3 4-3 7a3 3 0 0 1-5.5 1.6M10 10.5a2 2 0 0 1 4 0",
  flag: "M6 21V4M6 4h11l-2.5 4L17 12H6",
  thought: "M7 16.5a4 4 0 0 1-.6-7.9A5.5 5.5 0 0 1 17 7.5a4.5 4.5 0 0 1 .5 9zM8 20.5h.01M5 22.5h.01",
  speech: "M4 5.5h16v10H10l-4.5 3.5v-3.5H4z",
  map: "M3 6.5l6-2.5 6 2.5 6-2.5v13.5l-6 2.5-6-2.5-6 2.5zM9 4v13.5M15 6.5V20",
  chart: "M4 20V4M4 20h16M8 16l3.5-5 3 3 4.5-7",
  person: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6",
  people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c.8-3.5 3.3-5.3 6.5-5.3s5.7 1.8 6.5 5.3M16 4.3a3.5 3.5 0 0 1 0 6.4M18 14.9c1.8.7 3 2.4 3.5 5.1",
  scale: "M12 4v16M6 20h12M5 8h14M5 8l-2.5 6h5zM19 8l-2.5 6h5z",
  commit: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM12 2v6.5M12 15.5V22",
  book: "M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5zM4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5",
  board: "M4 4h16v16H4zM8 9h8M8 13h8M8 17h5",
  link: "M10 14l4-4M9 7l1.5-1.5a4 4 0 0 1 5.7 5.7L14.5 13M15 17l-1.5 1.5a4 4 0 0 1-5.7-5.7L9.5 11",
  table: "M3.5 5h17v14h-17zM3.5 10h17M3.5 14.5h17M9.5 10v9",
  lines: "M4 18l5-6 4 3 7-9",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  close: "M6 6l12 12M18 6L6 18",
  chevron: "M9 6l6 6-6 6",
  chevronLeft: "M15 6l-6 6 6 6",
  down: "M6 9l6 6 6-6",
  alert: "M12 3.5l9.5 16.5h-19zM12 10v4.5M12 17.5h.01",
  check: "M5 12.5l4.5 4.5L19 7.5",
  cross: "M7 7l10 10M17 7L7 17",
  clock: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 7.5V12l3 2",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6",
  dice: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM8.5 8.5h.01M15.5 15.5h.01M12 12h.01",
  coin: "M12 3.5c4.7 0 8.5 1.6 8.5 3.5S16.7 10.5 12 10.5 3.5 8.9 3.5 7 7.3 3.5 12 3.5zM3.5 7v5c0 1.9 3.8 3.5 8.5 3.5s8.5-1.6 8.5-3.5V7M3.5 12v5c0 1.9 3.8 3.5 8.5 3.5s8.5-1.6 8.5-3.5v-5",
  star: "M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z",
  home: "M4 11l8-7 8 7M6 9.5V20h12V9.5",
};

export function icon(name, size = 18, label = null) {
  return s(
    "svg",
    {
      class: `icon icon-${name}`,
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      role: label ? "img" : null,
      "aria-label": label,
      "aria-hidden": label ? null : "true",
    },
    s("path", { d: PATHS[name] }),
  );
}
