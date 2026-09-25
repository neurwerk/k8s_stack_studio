import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { OidcProvider } from "@/components/oidc-provider";
import { AuthGuard } from "@/components/auth-guard";
import { Sidebar } from "@/components/sidebar";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "neurwerk studio",
  description: "Dashboard for managing AI infrastructure",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="neurwerk" suppressHydrationWarning>
      <head>
        <script src="/env.js" />
      </head>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased`}
      >
        <OidcProvider>
          <AuthGuard>
            <div className="flex h-dvh min-h-0">
              <Sidebar />
              <main id="main-content" className="min-w-0 flex-1 overflow-auto bg-background">{children}</main>
            </div>
          </AuthGuard>
        </OidcProvider>
      </body>
    </html>
  );
}
