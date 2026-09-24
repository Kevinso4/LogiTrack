"use client";

import { useState } from "react";
import { IconBuscar, IconCamion, IconCopo, IconMas, IconPeligro } from "@/components/icons";
import {
  Badge,
  Boton,
  Campo,
  Card,
  cx,
  Encabezado,
  ErrorCaja,
  Esqueleto,
  Hoja,
  Input,
  Interruptor,
  Segmentado,
  Select,
  useAvisos,
  Vacio,
} from "@/components/ui";
import { api } from "@/lib/api";
import { CIUDADES, ESTADO_VEHICULO, fmtDia, fmtNum, hace, PRIORIDAD, TIPO_VEHICULO } from "@/lib/formato";
import { useDatos, useEventosEnVivo } from "@/lib/hooks";
import type { Alerta, Conductor, EstadoVehiculo, Posicion, Vehiculo } from "@/lib/types";

type Vista = "vehiculos" | "conductores";
type FiltroEstado = "todos" | EstadoVehiculo;

function FormVehiculo({ onListo }: { onListo: () => void }) {
  const avisar = useAvisos();
  const [f, setF] = useState({
    placa: "", tipo: "camion", marca: "", capacidad_kg: "5000", capacidad_m3: "25", anio: "2023",
    vencimiento_seguro: "2027-06-30", zona: "Montería", refrigerado: false, certificado_hazmat: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      await api("/api/v1/vehiculos", {
        method: "POST",
        json: { ...f, capacidad_kg: Number(f.capacidad_kg), capacidad_m3: Number(f.capacidad_m3), anio: Number(f.anio) },
      });
      avisar(`Vehículo ${f.placa.toUpperCase()} registrado`);
      onListo();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Placa"><Input value={f.placa} onChange={(e) => set("placa", e.target.value.toUpperCase())} placeholder="MTR-909" required minLength={5} maxLength={10} /></Campo>
        <Campo etiqueta="Tipo">
          <Select value={f.tipo} onChange={(e) => set("tipo", e.target.value)}>
            {Object.entries(TIPO_VEHICULO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Campo>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Marca y modelo"><Input value={f.marca} onChange={(e) => set("marca", e.target.value)} placeholder="Hino 500" required minLength={2} /></Campo>
        <Campo etiqueta="Año"><Input type="number" min="1990" max="2100" value={f.anio} onChange={(e) => set("anio", e.target.value)} required /></Campo>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Capacidad (kg)"><Input type="number" min="1" value={f.capacidad_kg} onChange={(e) => set("capacidad_kg", e.target.value)} required /></Campo>
        <Campo etiqueta="Capacidad (m³)"><Input type="number" min="0.1" step="any" value={f.capacidad_m3} onChange={(e) => set("capacidad_m3", e.target.value)} required /></Campo>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Zona base">
          <Select value={f.zona} onChange={(e) => set("zona", e.target.value)}>
            {CIUDADES.filter((c) => c.pais === "CO").map((c) => <option key={c.nombre}>{c.nombre}</option>)}
          </Select>
        </Campo>
        <Campo etiqueta="Vence el seguro"><Input type="date" value={f.vencimiento_seguro} onChange={(e) => set("vencimiento_seguro", e.target.value)} required /></Campo>
      </div>
      <div className="divide-y divide-hairline rounded-[12px] bg-fill px-3">
        <Interruptor etiqueta="Refrigerado" activo={f.refrigerado} onChange={(v) => set("refrigerado", v)} />
        <Interruptor etiqueta="Certificado para mercancía peligrosa" activo={f.certificado_hazmat} onChange={(v) => set("certificado_hazmat", v)} />
      </div>
      {error && <ErrorCaja mensaje={error} />}
      <Boton type="submit" cargando={enviando} className="h-11 w-full">Registrar vehículo</Boton>
    </form>
  );
}

function DetalleVehiculo({ v, conductores, onCambio }: { v: Vehiculo; conductores: Conductor[]; onCambio: () => void }) {
  const avisar = useAvisos();
  const pos = useDatos<Posicion>(`/api/v1/telemetria/${v.id}/ultima`, 5000);
  const alertas = useDatos<Alerta[]>(`/api/v1/mantenimiento/alertas?vehiculo_id=${v.id}&limite=5`, 8000);
  const [conductor, setConductor] = useState(v.conductor?.id ?? "");
  const [ocupado, setOcupado] = useState(false);

  async function cambiarEstado(estado: EstadoVehiculo) {
    setOcupado(true);
    try {
      await api(`/api/v1/vehiculos/${v.id}/estado`, { method: "PATCH", json: { estado, motivo: "Cambio manual desde el panel" } });
      avisar(`${v.placa}: ${ESTADO_VEHICULO[estado].texto}`);
      onCambio();
    } catch (err) {
      avisar(err instanceof Error ? err.message : "Error", "error");
    } finally {
      setOcupado(false);
    }
  }

  async function asignar() {
    setOcupado(true);
    try {
      await api("/api/v1/asignaciones", { method: "POST", json: { vehiculo_id: v.id, conductor_id: conductor } });
      avisar("Conductor asignado");
      onCambio();
    } catch (err) {
      avisar(err instanceof Error ? err.message : "Error", "error");
    } finally {
      setOcupado(false);
    }
  }

  const p = pos.datos;
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-display text-[28px] font-bold tracking-tight">{v.placa}</p>
          <p className="text-[14px] text-label-2">{v.marca} · {TIPO_VEHICULO[v.tipo]} · {v.anio}</p>
        </div>
        <Badge tono={ESTADO_VEHICULO[v.estado].tono} punto>{ESTADO_VEHICULO[v.estado].texto}</Badge>
      </div>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[14px] bg-hairline text-[13px] sm:grid-cols-4">
        {[
          ["Velocidad", p ? `${fmtNum(p.velocidad_kmh)} km/h` : "—"],
          ["Combustible", p ? `${fmtNum(p.nivel_combustible)} %` : "—"],
          ["Motor", p ? `${fmtNum(p.temperatura_motor_c)} °C` : "—"],
          ["Odómetro", p ? `${fmtNum(p.odometro_km)} km` : "—"],
          ["Capacidad", `${fmtNum(v.capacidad_kg)} kg`],
          ["Volumen", `${fmtNum(v.capacidad_m3)} m³`],
          ["Zona", v.zona],
          ["Seguro", fmtDia(v.vencimiento_seguro)],
        ].map(([k, val]) => (
          <div key={k} className="bg-surface-2 p-3">
            <dt className="text-label-3">{k}</dt>
            <dd className="mt-0.5 font-medium tabular">{val}</dd>
          </div>
        ))}
      </dl>
      {p && <p className="-mt-3 text-[12px] text-label-3">Telemetría {hace(p.registrado_en)}</p>}

      <div>
        <h4 className="mb-2 text-[13px] font-semibold tracking-wide text-label-2 uppercase">Estado operativo</h4>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(Object.keys(ESTADO_VEHICULO) as EstadoVehiculo[]).map((e) => (
            <button
              key={e}
              disabled={ocupado || e === v.estado}
              onClick={() => cambiarEstado(e)}
              className={cx(
                "rounded-[12px] px-3 py-2.5 text-[13px] font-medium ring-1 transition",
                e === v.estado ? "bg-accent text-white ring-accent" : "bg-surface-2 ring-hairline hover:bg-fill disabled:opacity-50",
              )}
            >
              {ESTADO_VEHICULO[e].texto}
            </button>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-label-3">Cada cambio publica vehicle.status_changed; si el vehículo sale de servicio, Shipment reasigna sus envíos.</p>
      </div>

      <div>
        <h4 className="mb-2 text-[13px] font-semibold tracking-wide text-label-2 uppercase">Conductor</h4>
        <div className="flex gap-2">
          <Select value={conductor} onChange={(e) => setConductor(e.target.value)}>
            <option value="">Sin conductor</option>
            {conductores.map((c) => (
              <option key={c.id} value={c.id}>{c.nombre}{c.vehiculo_placa && c.vehiculo_placa !== v.placa ? ` (en ${c.vehiculo_placa})` : ""}</option>
            ))}
          </Select>
          <Boton variante="secundario" disabled={!conductor || conductor === v.conductor?.id} cargando={ocupado} onClick={asignar}>Asignar</Boton>
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-[13px] font-semibold tracking-wide text-label-2 uppercase">Alertas recientes</h4>
        {alertas.datos?.length ? (
          <ul className="space-y-1.5">
            {alertas.datos.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 rounded-[10px] bg-surface-2 px-3 py-2 text-[13px]">
                <span className="truncate">{a.mensaje}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge tono={a.estado === "abierta" ? PRIORIDAD[a.prioridad].tono : "gray"}>{a.estado === "abierta" ? PRIORIDAD[a.prioridad].texto : "Cerrada"}</Badge>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-label-3">Sin alertas.</p>
        )}
      </div>
    </div>
  );
}

function FormConductor({ onListo }: { onListo: () => void }) {
  const avisar = useAvisos();
  const [f, setF] = useState({ nombre: "", numero_licencia: "", telefono: "", certificacion_hazmat: false, categoria: "C2" });
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      await api("/api/v1/conductores", {
        method: "POST",
        json: { nombre: f.nombre, numero_licencia: f.numero_licencia, telefono: f.telefono || null, certificacion_hazmat: f.certificacion_hazmat, categorias: [f.categoria] },
      });
      avisar(`${f.nombre} registrado`);
      onListo();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setEnviando(false);
    }
  }
  return (
    <form onSubmit={enviar} className="space-y-4">
      <Campo etiqueta="Nombre completo"><Input value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} required minLength={3} /></Campo>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Número de licencia"><Input value={f.numero_licencia} onChange={(e) => setF({ ...f, numero_licencia: e.target.value })} required minLength={4} /></Campo>
        <Campo etiqueta="Categoría">
          <Select value={f.categoria} onChange={(e) => setF({ ...f, categoria: e.target.value })}>
            {["C1", "C2", "C3"].map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Campo>
      </div>
      <Campo etiqueta="Teléfono"><Input value={f.telefono} onChange={(e) => setF({ ...f, telefono: e.target.value })} /></Campo>
      <div className="rounded-[12px] bg-fill px-3">
        <Interruptor etiqueta="Certificación en mercancía peligrosa" activo={f.certificacion_hazmat} onChange={(v) => setF({ ...f, certificacion_hazmat: v })} />
      </div>
      {error && <ErrorCaja mensaje={error} />}
      <Boton type="submit" cargando={enviando} className="h-11 w-full">Registrar conductor</Boton>
    </form>
  );
}

export default function Flota() {
  const [vista, setVista] = useState<Vista>("vehiculos");
  const [filtro, setFiltro] = useState<FiltroEstado>("todos");
  const [q, setQ] = useState("");
  const [creando, setCreando] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const vehiculos = useDatos<Vehiculo[]>("/api/v1/vehiculos", 5000);
  const conductores = useDatos<Conductor[]>("/api/v1/conductores", 15000);
  useEventosEnVivo(5, (e) => e.tipo === "vehicle.status_changed" && vehiculos.recargar());

  const lista = (vehiculos.datos ?? []).filter(
    (v) => (filtro === "todos" || v.estado === filtro) && (!q || `${v.placa} ${v.marca} ${v.zona}`.toLowerCase().includes(q.toLowerCase())),
  );
  const cuenta = (e: EstadoVehiculo) => vehiculos.datos?.filter((v) => v.estado === e).length;
  const seleccionado = vehiculos.datos?.find((v) => v.id === sel);

  return (
    <>
      <Encabezado titulo="Flota" subtitulo="Vehículos, conductores y estado operativo.">
        <Segmentado opciones={[{ valor: "vehiculos" as Vista, texto: "Vehículos" }, { valor: "conductores" as Vista, texto: "Conductores" }]} valor={vista} onChange={setVista} />
        <Boton onClick={() => setCreando(true)}><IconMas /> {vista === "vehiculos" ? "Nuevo vehículo" : "Nuevo conductor"}</Boton>
      </Encabezado>

      {vista === "vehiculos" ? (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="max-w-full overflow-x-auto">
              <Segmentado
                opciones={[
                  { valor: "todos" as FiltroEstado, texto: "Todos", cuenta: vehiculos.datos?.length },
                  ...(Object.keys(ESTADO_VEHICULO) as EstadoVehiculo[]).map((e) => ({ valor: e as FiltroEstado, texto: ESTADO_VEHICULO[e].texto, cuenta: cuenta(e) })),
                ]}
                valor={filtro}
                onChange={setFiltro}
              />
            </div>
            <div className="relative w-full sm:w-60">
              <IconBuscar className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-label-3" />
              <Input placeholder="Buscar placa, marca, zona" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 pl-9 text-[14px]" />
            </div>
          </div>
          {vehiculos.error && <ErrorCaja mensaje={vehiculos.error} />}
          {vehiculos.cargando && !vehiculos.datos ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Esqueleto key={i} className="h-44 rounded-[20px]" />)}</div>
          ) : lista.length === 0 ? (
            <Card><Vacio icono={<IconCamion className="size-10" />} titulo="Sin vehículos" texto="Ajusta el filtro o registra un vehículo." /></Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {lista.map((v, i) => {
                const est = ESTADO_VEHICULO[v.estado];
                return (
                  <button
                    key={v.id}
                    onClick={() => setSel(v.id)}
                    style={{ animationDelay: `${i * 30}ms` }}
                    className="group rounded-[20px] bg-surface p-5 text-left shadow-card ring-1 ring-hairline transition duration-300 hover:-translate-y-0.5 hover:shadow-sheet animate-aparecer"
                  >
                    <div className="flex items-start justify-between">
                      <div className="grid size-11 place-items-center rounded-[12px] bg-fill text-label-2 transition group-hover:text-accent">
                        <IconCamion className="size-6" />
                      </div>
                      <Badge tono={est.tono} punto>{est.texto}</Badge>
                    </div>
                    <p className="font-display mt-4 text-[22px] font-semibold tracking-tight">{v.placa}</p>
                    <p className="text-[13px] text-label-2">{v.marca} · {TIPO_VEHICULO[v.tipo]}</p>
                    <div className="mt-4 flex items-center justify-between text-[13px]">
                      <span className="truncate text-label-2">{v.conductor?.nombre ?? <span className="text-label-3">Sin conductor</span>}</span>
                      <span className="flex items-center gap-1.5 text-label-3">
                        {v.refrigerado && <span title="Refrigerado" className="text-teal"><IconCopo /></span>}
                        {v.certificado_hazmat && <span title="Hazmat" className="text-orange"><IconPeligro /></span>}
                        <span className="tabular">{fmtNum(v.capacidad_kg / 1000)} t</span>
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </>
      ) : (
        <Card padding={false} className="overflow-hidden">
          <ul className="divide-y divide-hairline">
            {(conductores.datos ?? []).map((c) => (
              <li key={c.id} className="flex items-center gap-4 px-5 py-3.5">
                <div className="grid size-10 place-items-center rounded-full bg-gradient-to-br from-[#8e8e93] to-[#636366] text-[14px] font-semibold text-white">
                  {c.nombre.split(" ").map((p) => p[0]).slice(0, 2).join("")}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] font-medium">{c.nombre}</p>
                  <p className="truncate text-[13px] text-label-2">Licencia {c.numero_licencia} · {c.categorias.join(", ")}{c.telefono ? ` · ${c.telefono}` : ""}</p>
                </div>
                {c.certificacion_hazmat && <Badge tono="orange">Hazmat</Badge>}
                <Badge tono={c.vehiculo_placa ? "accent" : "gray"}>{c.vehiculo_placa ?? "Sin vehículo"}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Hoja abierta={creando} onCerrar={() => setCreando(false)} titulo={vista === "vehiculos" ? "Nuevo vehículo" : "Nuevo conductor"}>
        {vista === "vehiculos" ? (
          <FormVehiculo onListo={() => { setCreando(false); vehiculos.recargar(); }} />
        ) : (
          <FormConductor onListo={() => { setCreando(false); conductores.recargar(); }} />
        )}
      </Hoja>
      <Hoja abierta={!!seleccionado} onCerrar={() => setSel(null)} titulo="Vehículo" ancho="max-w-2xl">
        {seleccionado && (
          <DetalleVehiculo
            key={seleccionado.id}
            v={seleccionado}
            conductores={conductores.datos ?? []}
            onCambio={() => { vehiculos.recargar(); conductores.recargar(); }}
          />
        )}
      </Hoja>
    </>
  );
}
