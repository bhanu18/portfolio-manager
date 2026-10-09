/** Restore the full in-app destination after sign-in, including filters. */
export function authReturnTo(state: unknown): string {
  const from = (state as { from?: { pathname?: unknown; search?: unknown; hash?: unknown } } | null)
    ?.from;
  if (
    typeof from?.pathname !== "string" ||
    !from.pathname.startsWith("/") ||
    from.pathname.startsWith("//") ||
    from.pathname.includes("\\")
  )
    return "/overview";
  return (
    from.pathname +
    (typeof from.search === "string" ? from.search : "") +
    (typeof from.hash === "string" ? from.hash : "")
  );
}
