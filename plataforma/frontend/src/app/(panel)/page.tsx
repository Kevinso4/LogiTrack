"use client";

import Link from "next/link";
import { FeedEventos } from "@/components/FeedEventos";
import { IconAlerta, IconCaja, IconCamion, IconChevron, IconRayo, IconServidor } from "@/components/icons";
import MapaFlota from "@/components/MapaFlota";
import { Card, cx, Encabezado, Metrica, TituloSeccion } from "@/components/ui";
import { ESTADO_ENVIO, ESTADO_VEHICULO, fmtNum } from "@/lib/formato";
import { useDatos, useEventosEnVivo } from "@/lib/hooks";
import { useSesion } from "@/lib/sesion";
import type { Envio, EstadoEnvio, EstadoServicio, EstadoVehiculo, Posicion, Vehiculo } from "@/lib/types";

interface ResumenFlota { total: number; por_estado: Record<EstadoVehiculo, number> }
interface ResumenEnvios { total: number; por_estado: Record<EstadoEnvio, number>; en_riesgo_sla: number; cumplimiento_sla_pct: number | null }
interface ResumenMant { alertas_abiertas: number; alertas_criticas: number; programas_proximos_30_dias: number; costo_mes: number }
interface EstadisticasGps { lecturas_por_segundo: number; vehiculos_reportando: number }

function Barra<T extends string>({ valores, config }: { valores: Record<T, number>; config: Record<T, { texto: string; tono: string }> }) {
  const total = Object.values<number>(valores).reduce((a, b) => a + b, 0) || 1;
  const color: Record<string, string> = { green: "bg-green", accent: "bg-accent", orange: "bg-orange", red: "bg-red", gray: "bg-label-3", indigo: "bg-indigo", teal: "bg-teal" };
  const claves = Object.keys(config) as T[];
  return (
    <div>
      <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-fill">
        {claves.map((k) =>
          valores[k] ? <div key={k} className={cx("transition-all duration-700", color[config[k].tono])} style={{ width: `${(valores[k] / total) * 100}%` }} /> : null,
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2.5">
        {claves.map((k) => (
          <div key={k} className="flex items-center justify-between text-[13px]">
            <span className="flex items-center gap-2 text-label-2">
              <span className={cx("size-2 rounded-full", color[config[k].tono])} />
              {config[k].texto}
            </span>
            <span className="tabular font-semibold">{valores[k] ?? 0}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const NOMBRE_SERVICIO: Record<string, string> = {
  gateway: "API Gateway",
  rabbitmq: "RabbitMQ",
  redis: "Redis",
  fleet: "Fleet Service",
  tracking: "Tracking Ingestion",
  shipment: "Shipment Service",
  maintenance: "Maintenance Service",
};

export default function Resumen() {
  const { usuario } = useSesion();
  const flota = useDatos<ResumenFlota>("/api/v1/vehiculos/resumen", 5000);
  const envios = useDatos<ResumenEnvios>("/api/v1/envios/resumen", 5000);
  const mant = useDatos<ResumenMant>("/api/v1/mantenimiento/resumen", 5000);
  const gps = useDatos<EstadisticasGps>("/api/v1/telemetria/estadisticas", 5000);
  const vehiculos = useDatos<Vehiculo[]>("/api/v1/vehiculos", 5000);
  const posiciones = useDatos<Posicion[]>("/api/v1/telemetria/ultimas", 5000);
  const enTransito = useDatos<Envio[]>("/api/v1/envios?estado=en_transito", 5000);
  const servicios = useDatos<EstadoServicio[]>("/api/v1/estado/servicios", 8000);
  const { eventos, conectado } = useEventosEnVivo(40, () => {
    flota.recargar();
    envios.recargar();
    mant.recargar();
  });

  const hora = new Date().getHours();
  const saludo = hora < 12 ? "Buenos días" : hora < 19 ? "Buenas tardes" : "Buenas noches";
  const pf = flota.datos?.por_estado;
  const pe = envios.datos?.por_estado;

  return (
    <>
      <Encabezado
        titulo={`${saludo}, ${usuario?.nombre.split(" ")[0] ?? ""}`}
        subtitulo={new Intl.DateTimeFormat("es-CO", { weekday: "long", day: "numeric", month: "long" }).format(new Date())}
      />

      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Metrica
          etiqueta="Vehículos disponibles"
          icono={<IconCamion className="size-4" />}
          tono="green"
          valor={pf ? pf.activo : "—"}
          detalle={pf ? `${pf.en_transito} en tránsito · ${flota.datos!.total} en total` : " "}
        />
        <Metrica
          etiqueta="Envíos en tránsito"
          icono={<IconCaja className="size-4" />}
          tono="accent"
          valor={pe ? pe.en_transito : "—"}
          detalle={
            envios.datos ? (
              <span className={envios.datos.en_riesgo_sla ? "text-orange" : undefined}>
                {envios.datos.en_riesgo_sla} en riesgo de SLA
                {envios.datos.cumplimiento_sla_pct != null && ` · ${envios.datos.cumplimiento_sla_pct}% a tiempo`}
              </span>
            ) : " "
          }
        />
        <Metrica
          etiqueta="Alertas abiertas"
          icono={<IconAlerta className="size-4" />}
          tono={mant.datos?.alertas_criticas ? "red" : "orange"}
          valor={mant.datos?.alertas_abiertas ?? "—"}
          detalle={mant.datos ? `${mant.datos.alertas_criticas} críticas · ${mant.datos.programas_proximos_30_dias} servicios en 30 días` : " "}
        />
        <Metrica
          etiqueta="Telemetría GPS"
          icono={<IconRayo className="size-4" />}
          tono="indigo"
          valor={gps.datos ? fmtNum(gps.datos.lecturas_por_segundo) : "—"}
          detalle={gps.datos ? `lecturas/s · ${gps.datos.vehiculos_reportando} vehículos reportando` : " "}
        />
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="relative xl:col-span-2" padding={false}>
          <MapaFlota
            vehiculos={vehiculos.datos ?? []}
            posiciones={posiciones.datos ?? []}
            envios={enTransito.datos ?? []}
            className="h-[440px] rounded-[20px] ring-0"
          />
          <Link
            href="/mapa"
            className="glass absolute top-4 left-4 flex items-center gap-1 rounded-full px-3.5 py-1.5 text-[13px] font-medium shadow-card ring-1 ring-hairline hover:bg-surface"
          >
            Abrir seguimiento <IconChevron className="size-3.5" />
          </Link>
        </Card>
        <Card className="h-[440px]">
          <FeedEventos eventos={eventos} conectado={conectado} />
        </Card>
      </section>

      <section className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <TituloSeccion>Flota por estado</TituloSeccion>
          {pf && <Barra valores={pf} config={ESTADO_VEHICULO} />}
        </Card>
        <Card>
          <TituloSeccion>Envíos por estado</TituloSeccion>
          {pe && <Barra valores={pe} config={ESTADO_ENVIO} />}
        </Card>
        <Card>
          <TituloSeccion accion={<IconServidor className="size-4 text-label-3" />}>Estado de la plataforma</TituloSeccion>
          <ul className="divide-y divide-hairline">
            {(servicios.datos ?? []).map((s) => (
              <li key={s.servicio} className="flex items-center justify-between py-2 text-[13px]">
                <span className="flex items-center gap-2.5">
                  <span className={cx("size-2 rounded-full", s.ok ? "bg-green" : "bg-red")} />
                  {NOMBRE_SERVICIO[s.servicio] ?? s.servicio}
                </span>
                <span className="tabular text-label-3">
                  {s.circuito !== "cerrado" ? <span className="text-orange">circuito {s.circuito}</span> : s.latencia_ms ? `${s.latencia_ms} ms` : s.ok ? "operativo" : "caído"}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </section>
    </>
  );
}
