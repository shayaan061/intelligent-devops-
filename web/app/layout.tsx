import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Nav } from "@/components/Nav";
import { LiveProvider } from "@/lib/live";
import "./globals.css";

export const metadata: Metadata = {
  title: "DevOps Incident Console",
  description: "Live monitoring, incident analysis, approvals and system health for the Intelligent DevOps Monitoring & Incident Response System",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <LiveProvider>
          <Nav />
          <main className="mx-auto max-w-7xl px-4 py-5">{children}</main>
        </LiveProvider>
      </body>
    </html>
  );
}
