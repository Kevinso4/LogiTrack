"use client";

import { useState } from "react";
import { IconAlerta, IconCheck, IconLlave, IconMas } from "@/components/icons";
import {
  Badge,
  Boton,
  Campo,
  Card,
  Encabezado,
  ErrorCaja,
  Hoja,
  Input,
  Interruptor,
  Metrica,
  Segmentado,
  Select,
  useAvisos,
  Vacio,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ESTADO_VEHICULO, fmtCOP, fmtDia, fmtFecha, fmtNum, hace, PRIORIDAD } from "@/lib/formato";
import { useDatos, useEventosEnVivo } from "@/lib/hooks";
import type { Alerta, Intervencion, Programa, Regla, Vehiculo } from "@/lib/types";

type Vista = "alertas" | "programas" | "intervenciones" | "reglas";

const METRICA: Record<string, string> = {
  temperatura_motor: "Temperatura de motor",
  nivel_combustible: "Nivel de combustible",
  velocidad: "Velocidad",
  temperatura_carga: "Temperatura de carga",
  codigo_obd2: "Código OBD2",
};
const OPERADOR: Record<string, string> = { mayor: ">", menor: "<", presente: "presente" };

function FormIntervencion({
  vehiculos,
  programas,
  inicial,
  onListo,
}: {
  vehiculos: Vehiculo[];
  programas: Programa[];
  inicial?: { vehiculo_id?: string; programa_id?: string };
  onListo: () => void;
}) {
  const avisar = useAvisos();
  const [f, setF] = useState({
    vehiculo_id: inicial?.vehiculo_id ?? vehiculos[0]?.id ?? "",
    programa_id: inicial?.programa_id ?? "",
    descripcion: "Cambio de aceite, filtros y revisión del sistema de refrigeración",
    costo: "850000",
    taller: "Taller Diesel del Sinú",
    km_al_servicio: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const progsVehiculo = programas.filter((p) => p.vehiculo_id === f.vehiculo_id);
  const kmSugerido = progsVehiculo[0]?.km_actual;

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      await api("/api/v1/mantenimiento/intervenciones", {
        method: "POST",
        json: {
          vehiculo_id: f.vehiculo_id,
          programa_id: f.programa_id || null,
          descripcion: f.descripcion,
          costo: Number(f.costo),
          taller: f.taller,
          km_al_servicio: Math.round(Number(f.km_al_servicio || kmSugerido || 0)),
        },
      });
      avisar("Intervención registrada · vehículo devuelto a operación");
      onListo();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="space-y-4">
      <Campo etiqueta="Vehículo">
        <Select value={f.vehiculo_id} onChange={(e) => setF({ ...f, vehiculo_id: e.target.value, programa_id: "" })}>
          {vehiculos.map((v) => <option key={v.id} value={v.id}>{v.placa} · {ESTADO_VEHICULO[v.estado].texto}</option>)}
        </Select>
      </Campo>
      <Campo etiqueta="Programa que cumple (opcional)">
        <Select value={f.programa_id} onChange={(e) => setF({ ...f, programa_id: e.target.value })}>
          <option value="">Correctivo (no programado)</option>
          {progsVehiculo.map((p) => <option key={p.id} value={p.id}>{p.tipo} · {fmtDia(p.fecha_prevista)}</option>)}
        </Select>
      </Campo>
      <Campo etiqueta="Descripción del trabajo">
        <Input value={f.descripcion} onChange={(e) => setF({ ...f, descripcion: e.target.value })} required minLength={3} />
      </Campo>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Costo (COP)"><Input type="number" min="0" value={f.costo} onChange={(e) => setF({ ...f, costo: e.target.value })} required /></Campo>
        <Campo etiqueta="Kilometraje" ayuda={kmSugerido ? `Actual: ${fmtNum(kmSugerido)} km` : undefined}>
          <Input type="number" min="0" placeholder={kmSugerido ? String(Math.round(kmSugerido)) : "0"} value={f.km_al_servicio} onChange={(e) => setF({ ...f, km_al_servicio: e.target.value })} />
        </Campo>
      </div>
      <Campo etiqueta="Taller"><Input value={f.taller} onChange={(e) => setF({ ...f, taller: e.target.value })} required minLength={2} /></Campo>
      <p className="text-[12px] text-label-3">Al guardar se cierran las alertas abiertas del vehículo y se publica maintenance.completed: Fleet lo devuelve a «Disponible».</p>
      {error && <ErrorCaja mensaje={error} />}
      <Boton type="submit" cargando={enviando} className="h-11 w-full">Registrar intervención</Boton>
    </form>
  );
}

export default function Mantenimiento() {
  const avisar = useAvisos();
  const [vista, setVista] = useState<Vista>("alertas");
  const [soloAbiertas, setSoloAbiertas] = useState(true);
  const [form, setForm] = useState<null | { vehiculo_id?: string; programa_id?: string }>(null);
  const vehiculos = useDatos<Vehiculo[]>("/api/v1/vehiculos", 10000);
  const alertas = useDatos<Alerta[]>(`/api/v1/mantenimiento/alertas${soloAbiertas ? "?estado=abierta" : ""}`, 5000);
  const programas = useDatos<Programa[]>("/api/v1/mantenimiento/proximos?dias=90", 10000);
  const intervenciones = useDatos<Intervencion[]>("/api/v1/mantenimiento/intervenciones", 10000);
  const reglas = useDatos<Regla[]>("/api/v1/mantenimiento/reglas");
  const resumen = useDatos<{ alertas_abiertas: number; alertas_criticas: number; programas_proximos_30_dias: number; costo_mes: number }>("/api/v1/mantenimiento/resumen", 5000);
  useEventosEnVivo(5, (e) => {
    if (e.tipo.startsWith("maintenance.")) {
      alertas.recargar();
      resumen.recargar();
      programas.recargar();
    }
  });

  const placa = (id: string) => vehiculos.datos?.find((v) => v.id === id)?.placa ?? id.slice(0, 8);
  const vehiculo = (id: string) => vehiculos.datos?.find((v) => v.id === id);

  async function cerrarAlerta(id: string) {
    try {
      await api(`/api/v1/mantenimiento/alertas/${id}/cerrar`, { method: "POST" });
      avisar("Alerta descartada");
      alertas.recargar();
      resumen.recargar();
    } catch (err) {
      avisar(err instanceof Error ? err.message : "Error", "error");
    }
  }

  async function editarRegla(r: Regla, cambios: Partial<Regla>) {
    try {
      await api(`/api/v1/mantenimiento/reglas/${r.id}`, { method: "PATCH", json: cambios });
      reglas.recargar();
    } catch (err) {
      avisar(err instanceof Error ? err.message : "Error", "error");
    }
  }

  const r = resumen.datos;
  return (
    <>
      <Encabezado titulo="Mantenimiento" subtitulo="Reglas sobre la telemetría, alertas predictivas y programa preventivo.">
        <Boton onClick={() => setForm({})}><IconMas /> Registrar intervención</Boton>
      </Encabezado>

      <section className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Metrica etiqueta="Alertas abiertas" tono="orange" icono={<IconAlerta className="size-4" />} valor={r?.alertas_abiertas ?? "—"} />
        <Metrica etiqueta="Críticas" tono="red" icono={<IconAlerta className="size-4" />} valor={r?.alertas_criticas ?? "—"} detalle="Sacan el vehículo de servicio" />
        <Metrica etiqueta="Servicios en 30 días" tono="teal" icono={<IconLlave className="size-4" />} valor={r?.programas_proximos_30_dias ?? "—"} />
        <Metrica etiqueta="Costo del mes" tono="indigo" icono={<IconCheck className="size-4" />} valor={r ? fmtCOP(r.costo_mes) : "—"} />
      </section>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmentado
          opciones={[
            { valor: "alertas" as Vista, texto: "Alertas" },
            { valor: "programas" as Vista, texto: "Próximos servicios" },
            { valor: "intervenciones" as Vista, texto: "Historial" },
            { valor: "reglas" as Vista, texto: "Reglas" },
          ]}
          valor={vista}
          onChange={setVista}
        />
        {vista === "alertas" && (
          <Segmentado opciones={[{ valor: "si", texto: "Abiertas" }, { valor: "no", texto: "Todas" }]} valor={soloAbiertas ? "si" : "no"} onChange={(v) => setSoloAbiertas(v === "si")} />
        )}
      </div>

      <Card padding={false} className="overflow-hidden">
        {vista === "alertas" &&
          (alertas.datos?.length ? (
            <ul className="divide-y divide-hairline">
              {alertas.datos.map((a) => {
                const pr = PRIORIDAD[a.prioridad];
                const v = vehiculo(a.vehiculo_id);
                return (
                  <li key={a.id} className="flex flex-wrap items-center gap-4 px-5 py-3.5 animate-aparecer">
                    <div className={`grid size-10 place-items-center rounded-full ${a.estado === "cerrada" ? "bg-fill text-label-3" : pr.tono === "red" ? "bg-red/12 text-red" : "bg-orange/14 text-orange"}`}>
                      <IconAlerta className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[15px] font-medium">{a.mensaje}</p>
                      <p className="text-[13px] text-label-2">
                        <span className="font-semibold text-label">{placa(a.vehiculo_id)}</span>
                        {v && ` · ${ESTADO_VEHICULO[v.estado].texto}`} · {hace(a.creada_en)}
                      </p>
                    </div>
                    <Badge tono={a.estado === "abierta" ? pr.tono : "gray"}>{a.estado === "abierta" ? pr.texto : "Cerrada"}</Badge>
                    {a.estado === "abierta" && (
                      <div className="flex gap-2">
                        <Boton variante="plano" onClick={() => cerrarAlerta(a.id)}>Descartar</Boton>
                        <Boton variante="secundario" onClick={() => setForm({ vehiculo_id: a.vehiculo_id })}>Atender</Boton>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <Vacio icono={<IconCheck className="size-10" />} titulo="Todo en orden" texto="No hay alertas abiertas. El simulador inyecta anomalías de vez en cuando." />
          ))}

        {vista === "programas" &&
          (programas.datos?.length ? (
            <ul className="divide-y divide-hairline">
              {programas.datos.map((p) => {
                const pct = p.km_previsto && p.km_actual ? Math.min(100, (p.km_actual / p.km_previsto) * 100) : 0;
                return (
                  <li key={p.id} className="flex flex-wrap items-center gap-4 px-5 py-3.5">
                    <div className="min-w-[90px]">
                      <p className="text-[15px] font-semibold">{placa(p.vehiculo_id)}</p>
                      <p className="text-[12px] text-label-3">{fmtDia(p.fecha_prevista)}</p>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[14px]">{p.tipo}</p>
                      {p.km_previsto != null && (
                        <div className="mt-1.5 flex items-center gap-3">
                          <div className="h-1.5 max-w-[240px] flex-1 overflow-hidden rounded-full bg-fill">
                            <div className={`h-full rounded-full ${pct > 95 ? "bg-red" : pct > 85 ? "bg-orange" : "bg-green"}`} style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-[12px] text-label-2 tabular">{p.km_restantes != null ? `faltan ${fmtNum(p.km_restantes)} km` : `a los ${fmtNum(p.km_previsto)} km`}</span>
                        </div>
                      )}
                    </div>
                    <Badge tono={(p.dias_restantes ?? 99) < 7 ? "orange" : "gray"}>{p.dias_restantes != null ? `en ${p.dias_restantes} días` : "—"}</Badge>
                    <Boton variante="secundario" onClick={() => setForm({ vehiculo_id: p.vehiculo_id, programa_id: p.id })}>Completar</Boton>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Vacio titulo="Sin servicios programados" texto="Se programan automáticamente cuando un vehículo empieza a reportar telemetría." />
          ))}

        {vista === "intervenciones" &&
          (intervenciones.datos?.length ? (
            <ul className="divide-y divide-hairline">
              {intervenciones.datos.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-4 px-5 py-3.5">
                  <div className="min-w-[90px]">
                    <p className="text-[15px] font-semibold">{placa(i.vehiculo_id)}</p>
                    <p className="text-[12px] text-label-3">{fmtFecha(i.realizado_en)}</p>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px]">{i.descripcion}</p>
                    <p className="text-[13px] text-label-2">{i.taller} · {fmtNum(i.km_al_servicio)} km {i.programa_id ? "· preventivo" : "· correctivo"}</p>
                  </div>
                  <span className="text-[15px] font-semibold tabular">{fmtCOP(i.costo)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Vacio titulo="Sin intervenciones registradas" texto="El historial es de solo inserción: sirve como auditoría." />
          ))}

        {vista === "reglas" && (
          <ul className="divide-y divide-hairline">
            {(reglas.datos ?? []).map((rg) => (
              <li key={rg.id} className="flex flex-wrap items-center gap-4 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-medium">{rg.nombre}</p>
                  <p className="text-[13px] text-label-2">
                    {METRICA[rg.metrica]} {OPERADOR[rg.operador]} {rg.operador !== "presente" && fmtNum(rg.umbral)}
                  </p>
                </div>
                <Badge tono={PRIORIDAD[rg.prioridad].tono}>{PRIORIDAD[rg.prioridad].texto}</Badge>
                {rg.operador !== "presente" && (
                  <Input
                    type="number"
                    aria-label="Umbral"
                    defaultValue={rg.umbral}
                    onBlur={(e) => Number(e.target.value) !== rg.umbral && editarRegla(rg, { umbral: Number(e.target.value) })}
                    className="h-8 w-24 text-right text-[14px]"
                  />
                )}
                <div className="w-[60px]">
                  <Interruptor etiqueta="" activo={rg.activa} onChange={(v) => editarRegla(rg, { activa: v })} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Hoja abierta={!!form} onCerrar={() => setForm(null)} titulo="Registrar intervención">
        {form && vehiculos.datos && (
          <FormIntervencion
            vehiculos={vehiculos.datos}
            programas={programas.datos ?? []}
            inicial={form}
            onListo={() => {
              setForm(null);
              alertas.recargar();
              programas.recargar();
              intervenciones.recargar();
              resumen.recargar();
              vehiculos.recargar();
            }}
          />
        )}
      </Hoja>
    </>
  );
}
