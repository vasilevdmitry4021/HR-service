import type { Metadata } from "next";
import { IBM_Plex_Sans, Bricolage_Grotesque } from "next/font/google";

import { AppToaster } from "@/components/AppToaster";
import { AuthHydration } from "@/components/AuthHydration";

import "./globals.css";

const ibmPlexSans = IBM_Plex_Sans({ 
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
});

const bricolageGrotesque = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "HR Service",
  description: "Поиск кандидатов",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className={`${ibmPlexSans.variable} ${bricolageGrotesque.variable} font-sans antialiased`}>
        <AuthHydration>{children}</AuthHydration>
        <AppToaster />
      </body>
    </html>
  );
}
