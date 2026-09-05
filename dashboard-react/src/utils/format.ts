export function trunc(s: string | null | undefined, n: number): string {
  const flat = String(s ?? "").replace(/\s+/g, " ").trim();
  return flat.length > n ? flat.slice(0, n) + "…" : flat;
}

export function pathOf(url: string): string {
  try {
    const u = new URL(url);
    return (u.pathname === "/" ? "/" : u.pathname) + u.search;
  } catch {
    return url;
  }
}

export function fmtTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
