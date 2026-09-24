"use client";

import { describirEvento, hace } from "@/lib/formato";
import type { EventoDominio } from "@/lib/types";
import { Punto, Vacio } from "./ui";

export function FeedEventos({ eventos, conectado }: { eventos: EventoDominio[]; conectado: boolean }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-[17px] font-semibold tracking-tight">Actividad en vivo</h2>
        <span className="flex items-center gap-1.5 text-[12px] font-medium text-label-2">
          <span className={conectado ? "size-2 rounded-full bg-green text-green animate-pulso" : "size-2 rounded-full bg-label-3"} />
          {conectado ? "RabbitMQ" : "Reconectando"}
        </span>
      </div>
      {eventos.length === 0 ? (
        <Vacio titulo="Sin eventos todavía" texto="Crea un envío o espera a que la telemetría dispare una alerta." />
      ) : (
        <ol className="-mx-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {eventos.map((e) => {
            const d = describirEvento(e.tipo, e.datos);
            return (
              <li key={e.event_id} className="flex gap-3 rounded-xl px-2 py-2 transition hover:bg-fill animate-aparecer">
                <div className="pt-1.5">
                  <Punto tono={d.tono} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="truncate text-[14px] font-medium">{d.titulo}</p>
                    <time className="shrink-0 text-[11px] text-label-3 tabular">{hace(e.ocurrido_en)}</time>
                  </div>
                  {d.detalle && <p className="truncate text-[13px] text-label-2">{d.detalle}</p>}
                  <p className="mt-0.5 font-mono text-[10.5px] text-label-3">
                    {e.tipo} · {e.origen}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
