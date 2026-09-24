"use client";

import Link from "next/link";
import { useState } from "react";
import { Logo } from "@/components/Shell";
import { Badge, Boton, Card, cx, ErrorCaja, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { ESTADO_ENVIO, fmtFecha } from "@/lib/formato";
import type { EstadoEnvio } from "@/lib/types";

interface Seguimiento {
  codigo: string;
  origen: string;
  destino: string;
  estado: EstadoEnvio;
  fecha_limite_sla: string;
  eventos: { tipo_evento: string; ocurrido_en: string }[];
}

const PASOS: { clave: EstadoEnvio[]; texto: string }[] = [
  { clave: ["pendiente", "retrasado"], texto: "Recibido" },
  { clave: ["en_transito", "con_incidencia"], texto: "En camino" },
  { clave: ["entregado"], texto: "Entregado" },
];

const TEXTO_EVENTO: Record<string, string> = {
  creado: "Recibimos tu envío",
  asignado: "Tu envío salió hacia su destino",
  reasignado: "Cambiamos el vehículo para no retrasar tu entrega",
  incidencia: "Hubo una incidencia en ruta",
  retrasado: "Tu envío presenta un retraso",
  reanudado: "Tu envío retomó la ruta",
  entregado: "Entregado",
  devuelto: "Devuelto al remitente",
};

/** Página pública (sin sesión, 30 req/min por IP en el gateway). */
export default function SeguimientoPublico() {
  const [codigo, setCodigo] = useState("");
  const [datos, setDatos] = useState<Seguimiento | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  async function buscar(e: React.FormEvent) {
    e.preventDefault();
    setCargando(true);
    setError(null);
    try {
      setDatos(await api<Seguimiento>(`/api/v1/envios/seguimiento/${encodeURIComponent(codigo.trim().toUpperCase())}`));
    } catch (err) {
      setDatos(null);
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setCargando(false);
    }
  }

  const paso = datos ? PASOS.findIndex((p) => p.clave.includes(datos.estado)) : -1;

  return (
    <div className="mx-auto min-h-dvh max-w-xl px-4 py-12">
      <div className="mb-10 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Logo />
          <span className="font-display text-[19px] font-semibold">LogiTrack</span>
        </div>
        <Link href="/login" className="text-[14px] text-accent hover:underline">Panel de operaciones</Link>
      </div>
      <h1 className="font-display text-[40px] leading-tight font-bold tracking-[-0.025em]">Rastrea tu envío.</h1>
      <p className="mt-2 text-[17px] text-label-2">Escribe el código que recibiste, por ejemplo LT-8K2Q9D.</p>
      <form onSubmit={buscar} className="mt-6 flex gap-2">
        <Input value={codigo} onChange={(e) => setCodigo(e.target.value)} placeholder="LT-XXXXXX" className="h-12 font-mono text-[17px] uppercase" required />
        <Boton type="submit" cargando={cargando} className="h-12 px-6">Rastrear</Boton>
      </form>
      {error && <div className="mt-4"><ErrorCaja mensaje={error} /></div>}

      {datos && (
        <Card className="mt-8 animate-sheet">
          <div className="flex items-start justify-between">
            <div>
              <p className="font-mono text-[13px] text-label-2">{datos.codigo}</p>
              <p className="font-display mt-1 text-[22px] font-semibold">{datos.origen} → {datos.destino}</p>
            </div>
            <Badge tono={ESTADO_ENVIO[datos.estado].tono} punto>{ESTADO_ENVIO[datos.estado].texto}</Badge>
          </div>
          <div className="mt-6 flex items-center">
            {PASOS.map((p, i) => (
              <div key={p.texto} className="flex flex-1 items-center last:flex-none">
                <div className="flex flex-col items-center gap-1.5">
                  <span className={cx("grid size-7 place-items-center rounded-full text-[12px] font-semibold", i <= paso ? "bg-accent text-white" : "bg-fill text-label-3")}>{i + 1}</span>
                  <span className={cx("text-[12px]", i <= paso ? "font-medium" : "text-label-3")}>{p.texto}</span>
                </div>
                {i < PASOS.length - 1 && <div className={cx("mx-2 mb-5 h-0.5 flex-1 rounded-full", i < paso ? "bg-accent" : "bg-fill")} />}
              </div>
            ))}
          </div>
          <p className="mt-6 text-[13px] text-label-2">Entrega comprometida: <span className="font-medium text-label">{fmtFecha(datos.fecha_limite_sla)}</span></p>
          <ol className="mt-4 space-y-3 border-t border-hairline pt-4">
            {[...datos.eventos].reverse().map((ev, i) => (
              <li key={i} className="flex justify-between gap-4 text-[14px]">
                <span>{TEXTO_EVENTO[ev.tipo_evento] ?? ev.tipo_evento}</span>
                <time className="shrink-0 text-[12px] text-label-3">{fmtFecha(ev.ocurrido_en)}</time>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
