export function platformExtensionsEnabled(): boolean {
  const value = process.env.DWELLCALL_PLATFORM_EXTENSIONS_ENABLED;
  if (value !== undefined && value !== "" && value !== "true" && value !== "false") {
    throw new Error("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED must be true or false.");
  }
  return value === "true";
}
