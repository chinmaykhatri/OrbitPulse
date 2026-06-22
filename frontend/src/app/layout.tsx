import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OrbitPulse — Autonomous Space Traffic Decision Engine",
  description: "Real-time collision prediction, autonomous maneuver planning, and multi-operator negotiation for 25,000+ tracked objects in low Earth orbit.",
  keywords: ["space traffic management", "conjunction assessment", "orbital mechanics", "collision avoidance", "SGP4", "satellite tracking"],
  openGraph: {
    title: "OrbitPulse — Space Traffic Decision Engine",
    description: "Real orbital data. Real physics. Real collision predictions.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
