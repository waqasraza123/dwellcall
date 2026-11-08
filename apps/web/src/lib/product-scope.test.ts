import { afterEach, expect, it, vi } from "vitest";
import { platformExtensionsEnabled } from "./product-scope";
afterEach(() => vi.unstubAllEnvs());
it("defaults to the focused outbound product and requires an explicit extension opt-in", () => {
  vi.stubEnv("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED", undefined);
  expect(platformExtensionsEnabled()).toBe(false);
  vi.stubEnv("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED", "false");
  expect(platformExtensionsEnabled()).toBe(false);
  vi.stubEnv("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED", "true");
  expect(platformExtensionsEnabled()).toBe(true);
  vi.stubEnv("DWELLCALL_PLATFORM_EXTENSIONS_ENABLED", "yes");
  expect(() => platformExtensionsEnabled()).toThrow("true or false");
});
