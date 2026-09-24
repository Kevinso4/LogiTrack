"use client";

import { useMemo, useState } from "react";
import { IconCerrar, IconGota, IconTermometro, IconVelocidad } from "@/components/icons";
import MapaFlota from "@/components/MapaFlota";
import { Badge, Card, cx, Encabezado, Punto } from "@/components/ui";
import { ESTADO_VEHICULO, fmtNum, hace } from "@/lib/formato";
import { useDatos } from "@/lib/hooks";
import type { Envio, Posicion, Vehiculo } from "@/lib/types";

function Indicador({ icono, etiqueta, valor, unidad, alerta }: { icono: React.ReactNode; etiqueta: string; valor: string; unidad: string; alerta?: boolean }) {
  return (
    <div className="rounded-[14px] bg-fill p-3">
      <div className={cx("flex items-center gap-1.5 text-[12px] font-medium", alerta ? "text-red" : "text-label-2")}>
        {icono}
        {etiqueta}
      </div>
      <div className={cx("font-display mt-1 text-[22px] font-semibold tabular", alerta && "text-red")}>
        {valor}
        <span className="ml-0.5 text-[13px] font-medium text-label-2">{unidad}</span>
      </div>
    </div>
  );
}

export default function Seguimiento() {
  const [sel, setSel] = useState<string | null>(null);
  const vehiculos = useDatos<Vehiculo[]>("/api/v1/vehiculos", 5000);
  const posiciones = useDatos<Posicion[]>("/api/v1/telemetria/ultimas", 3000);
  const envios = useDatos<Envio[]>("/api/v1/envios?estado=en_transito", 5000);
  const desde = useMemo(() => new Date(Date.now() - 30 * 60_000).toISOString(), [sel]); // eslint-disable-line react-hooks/exhaustive-deps
  const recorrido = useDatos<Posicion[]>(sel ? `/api/v1/telemetria/${sel}/recorrido?desde=${encodeURIComponent(desde)}` : null, 5000);

  const posPorId = new Map((posiciones.datos ?? []).map((p) => [p.vehiculo_id, p]));
  const envioPorVehiculo = new Map((envios.datos ?? []).map((e) => [e.vehiculo_id, e]));
  const v = vehiculos.datos?.find((x) => x.id === sel);
  const p = sel ? posPorId.get(sel) : undefined;
  const envio = sel ? envioPorVehiculo.get(sel) : undefined;
  const orden: Record<string, number> = { en_transito: 0, fuera_de_servicio: 1, en_mantenimiento: 2, activo: 3 };
  const lista = [...(vehiculos.datos ?? [])].sort((a, b) => orden[a.estado] - orden[b.estado] || a.placa.localeCompare(b.placa));

  return (
    <>
      <Encabezado titulo="Seguimiento" subtitulo="Posición en tiempo real reportada por los dispositivos GPS cada pocos segundos." />
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card padding={false} className="max-h-[calc(100dvh-220px)] overflow-y-auto lg:h-[calc(100dvh-200px)] lg:max-h-none">
          <ul className="divide-y divide-hairline">
            {lista.map((x) => {
              const pos = posPorId.get(x.id);
              const e = envioPorVehiculo.get(x.id);
              return (
                <li key={x.id}>
                  <button
                    onClick={() => setSel(x.id === sel ? null : x.id)}
                    className={cx("flex w-full items-center gap-3 px-4 py-3 text-left transition", x.id === sel ? "bg-accent/10" : "hover:bg-fill/60")}
                  >
                    <Punto tono={ESTADO_VEHICULO[x.estado].tono} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-[15px] font-semibold">{x.placa}</span>
                        <span className="text-[12px] text-label-3 tabular">{pos ? `${fmtNum(pos.velocidad_kmh)} km/h` : "sin señal"}</span>
                      </div>
                      <p className="truncate text-[13px] text-label-2">{e ? `${e.codigo} → ${e.destino}` : ESTADO_VEHICULO[x.estado].texto}</p>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <div className="relative">
          <MapaFlota
            vehiculos={vehiculos.datos ?? []}
            posiciones={posiciones.datos ?? []}
            envios={envios.datos ?? []}
            recorrido={recorrido.datos ?? []}
            seleccionado={sel}
            onSeleccionar={setSel}
            className="h-[60dvh] lg:h-[calc(100dvh-200px)]"
          />
          {v && (
            <div className="glass absolute right-3 bottom-8 left-3 rounded-[20px] p-4 shadow-sheet ring-1 ring-hairline animate-sheet sm:left-auto sm:w-[360px]">
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-display text-[20px] font-semibold tracking-tight">{v.placa}</p>
                  <p className="text-[13px] text-label-2">{v.conductor?.nombre ?? "Sin conductor"} · {v.marca}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tono={ESTADO_VEHICULO[v.estado].tono} punto>{ESTADO_VEHICULO[v.estado].texto}</Badge>
                  <button onClick={() => setSel(null)} aria-label="Cerrar" className="grid size-7 place-items-center rounded-full bg-fill text-label-2 hover:bg-fill-strong">
                    <IconCerrar className="size-3.5" />
                  </button>
                </div>
              </div>
              {envio && (
                <p className="mt-2 rounded-[10px] bg-accent/10 px-3 py-2 text-[13px] text-accent">
                  Envío <span className="font-mono font-semibold">{envio.codigo}</span> · {envio.origen} → {envio.destino}
                </p>
              )}
              {p ? (
                <>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <Indicador icono={<IconVelocidad className="size-3.5" />} etiqueta="Velocidad" valor={fmtNum(p.velocidad_kmh)} unidad="km/h" alerta={p.velocidad_kmh > 110} />
                    <Indicador icono={<IconGota className="size-3.5" />} etiqueta="Combustible" valor={fmtNum(p.nivel_combustible)} unidad="%" alerta={p.nivel_combustible < 10} />
                    <Indicador icono={<IconTermometro className="size-3.5" />} etiqueta="Motor" valor={fmtNum(p.temperatura_motor_c)} unidad="°C" alerta={p.temperatura_motor_c > 105} />
                  </div>
                  <div className="mt-3 flex justify-between text-[12px] text-label-2">
                    <span className="tabular">{fmtNum(p.odometro_km)} km recorridos</span>
                    <span>
                      {p.temperatura_c != null && `Carga ${fmtNum(p.temperatura_c)} °C · `}
                      {p.codigo_obd2 && <span className="font-semibold text-red">OBD2 {p.codigo_obd2} · </span>}
                      {hace(p.registrado_en)}
                    </span>
                  </div>
                </>
              ) : (
                <p className="mt-3 text-[13px] text-label-3">Este vehículo aún no ha reportado telemetría.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
