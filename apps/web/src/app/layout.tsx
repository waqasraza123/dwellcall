import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./styles.css";
import "@/features/outbound-demo/outbound-demo.css";
export const metadata: Metadata = {
  title: {
    default: "DwellCall | AI Real Estate Lead Intelligence",
    template: "%s | DwellCall",
  },
  description:
    "Find new listings. Identify the agents. Build your pipeline.",
  openGraph: {
    title: "DwellCall | AI Real Estate Lead Intelligence",
    description:
      "Find new listings. Identify the agents. Build your pipeline.",
    type: "website",
  },
  icons: {
    icon: { url: "/icon.svg", type: "image/svg+xml", sizes: "any" },
    shortcut: "/icon.svg",
  },
};
export const viewport: Viewport = {
  themeColor: "#f5f2eb",
};
export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

