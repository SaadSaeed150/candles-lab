import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "TradeLab — Trading Dashboard",
  description: "Paper trading, backtesting, and strategy analysis platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased">
        <AuthProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="ml-60 flex-1 p-6">{children}</main>
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
