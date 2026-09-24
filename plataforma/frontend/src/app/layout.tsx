import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ProveedorAvisos } from "@/components/ui";
import { ProveedorSesion } from "@/lib/sesion";
import "./globals.css";

// En macOS/iOS se usa la fuente del sistema (SF Pro); Inter es el respaldo en Windows y Android.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "LogiTrack",
  description: "Plataforma de gestión de logística y flotas de transporte",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={inter.variable}>
      <body>
        <ProveedorSesion>
          <ProveedorAvisos>{children}</ProveedorAvisos>
        </ProveedorSesion>
      </body>
    </html>
  );
}
