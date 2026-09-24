"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Shell";
import { Boton, ErrorCaja, Input } from "@/components/ui";
import { useSesion } from "@/lib/sesion";

const DEMO = [
  { usuario: "operador", clave: "operador123", rol: "Operador logístico" },
  { usuario: "gestor", clave: "gestor123", rol: "Gestor de flota" },
  { usuario: "admin", clave: "admin123", rol: "Administrador" },
];

export default function Login() {
  const { entrar, usuario } = useSesion();
  const router = useRouter();
  const [u, setU] = useState("");
  const [clave, setClave] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    if (usuario) router.replace("/");
  }, [usuario, router]);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      await entrar(u.trim(), clave);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden px-4 py-10">
      {/* Fondo con degradado suave */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(10,132,255,0.22),transparent)] blur-2xl" />
        <div className="absolute right-[-10%] bottom-[-20%] h-[420px] w-[620px] rounded-full bg-[radial-gradient(closest-side,rgba(94,92,230,0.18),transparent)] blur-2xl" />
      </div>

      <div className="w-full max-w-[380px] animate-aparecer">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo className="size-16 rounded-[18px]" />
          <h1 className="font-display mt-5 text-[32px] font-bold tracking-[-0.022em]">LogiTrack</h1>
          <p className="mt-1 text-[15px] text-label-2">Inicia sesión en el panel de operaciones</p>
        </div>

        <form onSubmit={enviar} className="space-y-3">
          <div className="overflow-hidden rounded-[14px] bg-surface shadow-card ring-1 ring-hairline">
            <Input
              aria-label="Usuario"
              placeholder="Usuario"
              autoComplete="username"
              value={u}
              onChange={(e) => setU(e.target.value)}
              className="h-12 rounded-none bg-transparent focus:ring-0"
              required
            />
            <div className="mx-3 h-px bg-hairline" />
            <Input
              aria-label="Contraseña"
              placeholder="Contraseña"
              type="password"
              autoComplete="current-password"
              value={clave}
              onChange={(e) => setClave(e.target.value)}
              className="h-12 rounded-none bg-transparent focus:ring-0"
              required
            />
          </div>
          {error && <ErrorCaja mensaje={error} />}
          <Boton type="submit" cargando={enviando} className="h-11 w-full text-[15px]">
            Continuar
          </Boton>
        </form>

        <div className="mt-8">
          <p className="mb-2 text-center text-[12px] font-medium tracking-wide text-label-3 uppercase">Cuentas de demostración</p>
          <div className="grid gap-2">
            {DEMO.map((d) => (
              <button
                key={d.usuario}
                onClick={() => {
                  setU(d.usuario);
                  setClave(d.clave);
                }}
                className="flex items-center justify-between rounded-[12px] bg-surface/70 px-4 py-2.5 text-left ring-1 ring-hairline transition hover:bg-surface"
              >
                <span className="text-[14px] font-medium">{d.rol}</span>
                <span className="font-mono text-[12px] text-label-2">
                  {d.usuario} / {d.clave}
                </span>
              </button>
            ))}
          </div>
          <p className="mt-6 text-center text-[13px] text-label-2">
            ¿Eres cliente?{" "}
            <Link href="/seguimiento" className="text-accent hover:underline">
              Rastrea tu envío
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
