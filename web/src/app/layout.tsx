import type { Metadata, Viewport } from "next";
import { Inter, Bricolage_Grotesque } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { ThemeScript } from "@/components/ThemeToggle";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-bricolage",
  weight: ["600", "700"],
});

export const metadata: Metadata = {
  title: "Job Alerts",
  description: "Daily SDE-II role tracker across your watchlist",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f6f8" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1115" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${bricolage.variable}`}
          suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-dvh bg-canvas text-ink">
        <div className="mx-auto flex min-h-dvh w-full max-w-6xl">
          <Nav />
          {/* pb leaves room for the mobile tab bar, which is fixed. */}
          <main className="min-w-0 flex-1 px-4 pt-6 pb-28 sm:px-7 sm:pt-9 md:pb-12">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
