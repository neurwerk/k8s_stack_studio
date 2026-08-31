import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { OidcProvider } from "@/components/oidc-provider";
import { AuthGuard } from "@/components/auth-guard";
import { Sidebar } from "@/components/sidebar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Stack Studio",
  description: "Dashboard for managing AI infrastructure",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script src="/env.js" />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <OidcProvider>
          <AuthGuard>
            <div className="flex h-screen">
              <Sidebar />
              <main className="min-w-0 flex-1 overflow-auto">{children}</main>
            </div>
          </AuthGuard>
        </OidcProvider>
      </body>
    </html>
  );
}
