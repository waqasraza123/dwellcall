import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./styles.css";
import "@/features/outbound-demo/outbound-demo.css";
export const metadata: Metadata = {
  title: {
    default: "DwellCall | Outbound AI Voice Agent",
    template: "%s | DwellCall",
  },
  description:
    "Requested property follow-up calls, natural AI conversations and clear qualification summaries.",
  openGraph: {
    title: "DwellCall | Outbound AI Voice Agent",
    description:
      "Requested property follow-up calls, natural AI conversations and clear qualification summaries.",
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

