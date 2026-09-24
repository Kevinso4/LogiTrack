"use client";

import { useMemo, useState } from "react";
import { IconBuscar, IconCaja, IconChevron, IconCopo, IconMas, IconPeligro } from "@/components/icons";
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
import { CIUDADES, ESTADO_ENVIO, fmtFecha, fmtNum, hace } from "@/lib/formato";
import { useDatos, useEventosEnVivo } from "@/lib/hooks";
import type { Envio, EnvioDetalle, EstadoEnvio } from "@/lib/types";

type Filtro = "todos" | EstadoEnvio;

const TIPO_EVENTO: Record<string, { texto: string; color: string }> = {
  creado: { texto: "Creado", color: "bg-label-3" },
  asignado: { texto: "Vehículo asignado", color: "bg-accent" },
  reasignado: { texto: "Reasignado", color: "bg-indigo" },
  incidencia: { texto: "Incidencia", color: "bg-orange" },
  retrasado: { texto: "Retrasado", color: "bg-red" },
  reanudado: { texto: "Reanudado", color: "bg-accent" },
  entregado: { texto: "Entregado", color: "bg-green" },
  devuelto: { texto: "Devuelto", color: "bg-indigo" },
};

function enHoras(h: number) {
  const d = new Date(Date.now() + h * 3600_000);
  d.setMinutes(0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}

function FormularioEnvio({ onCreado }: { onCreado: (e: Envio) => void }) {
  const avisar = useAvisos();
  const [f, setF] = useState({
    cliente: "Distribuidora del Sinú S.A.S.",
    cliente_email: "logistica@sinu.co",
    origen: "Montería",
    destino: "Cartagena",
    sla: enHoras(24),
    peso_kg: "1200",
    volumen_m3: "8",
    requiere_refrigeracion: false,
    es_hazmat: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    const o = CIUDADES.find((c) => c.nombre === f.origen)!;
    const d = CIUDADES.find((c) => c.nombre === f.destino)!;
    setEnviando(true);
    setError(null);
    try {
      const creado = await api<Envio>("/api/v1/envios", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        json: {
          cliente: f.cliente,
          cliente_email: f.cliente_email || null,
          origen: o.nombre,
          destino: d.nombre,
          origen_lat: o.lat,
          origen_lon: o.lon,
          destino_lat: d.lat,
          destino_lon: d.lon,
          fecha_limite_sla: new Date(f.sla).toISOString(),
          es_internacional: o.pais !== d.pais,
          requiere_refrigeracion: f.requiere_refrigeracion,
          es_hazmat: f.es_hazmat,
          peso_kg: Number(f.peso_kg),
          volumen_m3: Number(f.volumen_m3),
        },
      });
      avisar(`Envío ${creado.codigo} creado`);
      onCreado(creado);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setEnviando(false);
    }
  }

  const internacional = CIUDADES.find((c) => c.nombre === f.origen)?.pais !== CIUDADES.find((c) => c.nombre === f.destino)?.pais;

  return (
    <form onSubmit={enviar} className="space-y-4">
      <Campo etiqueta="Cliente">
        <Input value={f.cliente} onChange={(e) => set("cliente", e.target.value)} required minLength={2} />
      </Campo>
      <Campo etiqueta="Correo de notificación">
        <Input type="email" value={f.cliente_email} onChange={(e) => set("cliente_email", e.target.value)} />
      </Campo>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Origen">
          <Select value={f.origen} onChange={(e) => set("origen", e.target.value)}>
            {CIUDADES.map((c) => <option key={c.nombre}>{c.nombre}</option>)}
          </Select>
        </Campo>
        <Campo etiqueta="Destino">
          <Select value={f.destino} onChange={(e) => set("destino", e.target.value)}>
            {CIUDADES.map((c) => <option key={c.nombre}>{c.nombre}</option>)}
          </Select>
        </Campo>
      </div>
      {internacional && <Badge tono="indigo">Envío internacional · requiere documentación aduanera</Badge>}
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Peso (kg)">
          <Input type="number" min="1" step="any" value={f.peso_kg} onChange={(e) => set("peso_kg", e.target.value)} required />
        </Campo>
        <Campo etiqueta="Volumen (m³)">
          <Input type="number" min="0.1" step="any" value={f.volumen_m3} onChange={(e) => set("volumen_m3", e.target.value)} required />
        </Campo>
      </div>
      <Campo etiqueta="Fecha límite (SLA)">
        <Input type="datetime-local" value={f.sla} onChange={(e) => set("sla", e.target.value)} required />
      </Campo>
      <div className="divide-y divide-hairline rounded-[12px] bg-fill px-3">
        <Interruptor etiqueta="Requiere refrigeración" activo={f.requiere_refrigeracion} onChange={(v) => set("requiere_refrigeracion", v)} />
        <Interruptor etiqueta="Mercancía peligrosa (hazmat)" activo={f.es_hazmat} onChange={(v) => set("es_hazmat", v)} />
      </div>
      {error && <ErrorCaja mensaje={error} />}
      <Boton type="submit" cargando={enviando} className="h-11 w-full">
        Crear envío
      </Boton>
      <p className="text-center text-[12px] text-label-3">
        Shipment responde 201 al instante; la asignación de vehículo ocurre en segundo plano consultando a Fleet.
      </p>
    </form>
  );
}

function DetalleEnvio({ id, onCambio }: { id: string; onCambio: () => void }) {
  const avisar = useAvisos();
  const { datos: e, recargar, error } = useDatos<EnvioDetalle>(`/api/v1/envios/${id}`, 4000);
  const [accion, setAccion] = useState<null | "incidencia" | "entrega">(null);
  const [tipoInc, setTipoInc] = useState("averia");
  const [texto, setTexto] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function ejecutar(ruta: string, json: unknown, mensaje: string) {
    setOcupado(true);
    try {
      await api(`/api/v1/envios/${id}/${ruta}`, { method: "POST", json });
      avisar(mensaje);
      setAccion(null);
      setTexto("");
      await recargar();
      onCambio();
    } catch (err) {
      avisar(err instanceof Error ? err.message : "Error", "error");
    } finally {
      setOcupado(false);
    }
  }

  if (error) return <ErrorCaja mensaje={error} />;
  if (!e) return <Esqueleto className="h-64" />;
  const est = ESTADO_ENVIO[e.estado];
  const activo = e.estado === "en_transito" || e.estado === "con_incidencia";

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[13px] text-label-2">{e.codigo}</p>
          <p className="font-display mt-0.5 text-[22px] font-semibold tracking-tight">
            {e.origen} → {e.destino}
          </p>
          <p className="text-[14px] text-label-2">{e.cliente}</p>
        </div>
        <Badge tono={est.tono} punto>
          {est.texto}
        </Badge>
      </div>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[14px] bg-hairline text-[13px] sm:grid-cols-4">
        {[
          ["Vehículo", e.vehiculo_placa ?? "Sin asignar"],
          ["Carga", `${fmtNum(e.peso_kg)} kg · ${fmtNum(e.volumen_m3)} m³`],
          ["SLA", fmtFecha(e.fecha_limite_sla)],
          ["Creado", hace(e.creado_en)],
        ].map(([k, v]) => (
          <div key={k} className="bg-surface-2 p-3">
            <dt className="text-label-3">{k}</dt>
            <dd className="mt-0.5 font-medium">{v}</dd>
          </div>
        ))}
      </dl>

      {(e.requiere_refrigeracion || e.es_hazmat || e.es_internacional) && (
        <div className="flex flex-wrap gap-2">
          {e.requiere_refrigeracion && <Badge tono="teal">Refrigerado</Badge>}
          {e.es_hazmat && <Badge tono="orange">Hazmat</Badge>}
          {e.es_internacional && <Badge tono="indigo">Internacional</Badge>}
        </div>
      )}

      <div>
        <h4 className="mb-3 text-[13px] font-semibold tracking-wide text-label-2 uppercase">Cadena de custodia</h4>
        <ol className="relative ml-1.5 border-l border-hairline">
          {e.eventos.map((ev, i) => {
            const t = TIPO_EVENTO[ev.tipo_evento] ?? { texto: ev.tipo_evento, color: "bg-label-3" };
            return (
              <li key={i} className="relative pb-4 pl-5 last:pb-0">
                <span className={cx("absolute top-1 -left-[5px] size-[9px] rounded-full ring-4 ring-surface", t.color)} />
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[14px] font-medium">{t.texto}</p>
                  <time className="text-[12px] text-label-3 tabular">{fmtFecha(ev.ocurrido_en)}</time>
                </div>
                {ev.notas && <p className="text-[13px] text-label-2">{ev.notas}</p>}
              </li>
            );
          })}
        </ol>
      </div>

      {accion === "incidencia" && (
        <div className="space-y-3 rounded-[14px] bg-orange/8 p-4 ring-1 ring-orange/20">
          <Campo etiqueta="Tipo de incidencia">
            <Select value={tipoInc} onChange={(x) => setTipoInc(x.target.value)}>
              <option value="averia">Avería del vehículo</option>
              <option value="accidente">Accidente</option>
              <option value="retraso_trafico">Retraso por tráfico</option>
              <option value="clima">Clima</option>
              <option value="otro">Otro</option>
            </Select>
          </Campo>
          <Campo etiqueta="Descripción">
            <Input value={texto} onChange={(x) => setTexto(x.target.value)} placeholder="Ej.: falla en el sistema de frenos" />
          </Campo>
          {(tipoInc === "averia" || tipoInc === "accidente") && (
            <p className="text-[12px] text-label-2">
              Inicia la saga: Fleet saca el vehículo de servicio → Shipment busca uno alternativo → si no hay, compensa marcando el envío como retrasado.
            </p>
          )}
          <div className="flex gap-2">
            <Boton variante="secundario" onClick={() => setAccion(null)}>Cancelar</Boton>
            <Boton cargando={ocupado} disabled={texto.trim().length < 3} onClick={() => ejecutar("incidencia", { tipo: tipoInc, descripcion: texto }, "Incidencia reportada")}>
              Reportar
            </Boton>
          </div>
        </div>
      )}

      {accion === "entrega" && (
        <div className="space-y-3 rounded-[14px] bg-green/8 p-4 ring-1 ring-green/20">
          <Campo etiqueta="Nombre de quien recibe">
            <Input value={texto} onChange={(x) => setTexto(x.target.value)} placeholder="Ej.: Laura Méndez" />
          </Campo>
          <div className="flex gap-2">
            <Boton variante="secundario" onClick={() => setAccion(null)}>Cancelar</Boton>
            <Boton
              cargando={ocupado}
              disabled={texto.trim().length < 2}
              onClick={() => ejecutar("prueba-entrega", { nombre_receptor: texto, lat: e.destino_lat, lon: e.destino_lon }, "Entrega registrada")}
            >
              Confirmar entrega
            </Boton>
          </div>
        </div>
      )}

      {accion === null && (
        <div className="flex flex-wrap gap-2 border-t border-hairline pt-4">
          {activo && <Boton onClick={() => { setAccion("entrega"); setTexto(""); }}>Registrar entrega</Boton>}
          {e.estado === "en_transito" && (
            <Boton variante="secundario" onClick={() => { setAccion("incidencia"); setTexto(""); }}>Reportar incidencia</Boton>
          )}
          {e.estado === "con_incidencia" && (
            <Boton variante="secundario" cargando={ocupado} onClick={() => ejecutar("reanudar", { notas: "Incidencia resuelta" }, "Envío reanudado")}>Reanudar</Boton>
          )}
          {(e.estado === "pendiente" || e.estado === "retrasado") && (
            <Boton variante="secundario" cargando={ocupado} onClick={() => ejecutar("asignar", undefined, "Asignación solicitada a Fleet")}>Reintentar asignación</Boton>
          )}
          {(activo || e.estado === "retrasado") && (
            <Boton variante="peligro" cargando={ocupado} onClick={() => ejecutar("devolucion", { notas: "Devuelto a solicitud del operador" }, "Envío devuelto")}>Devolver</Boton>
          )}
        </div>
      )}
    </div>
  );
}

export default function Envios() {
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [q, setQ] = useState("");
  const [creando, setCreando] = useState(false);
  const [detalle, setDetalle] = useState<string | null>(null);
  const ruta = `/api/v1/envios?limite=200${filtro !== "todos" ? `&estado=${filtro}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const { datos, cargando, error, recargar } = useDatos<Envio[]>(ruta, 5000);
  const resumen = useDatos<{ por_estado: Record<EstadoEnvio, number>; total: number }>("/api/v1/envios/resumen", 5000);
  useEventosEnVivo(5, (ev) => ev.tipo.startsWith("shipment.") && (recargar(), resumen.recargar()));

  const opciones = useMemo(() => {
    const pe = resumen.datos?.por_estado;
    return [
      { valor: "todos" as Filtro, texto: "Todos", cuenta: resumen.datos?.total },
      { valor: "en_transito" as Filtro, texto: "En tránsito", cuenta: pe?.en_transito },
      { valor: "con_incidencia" as Filtro, texto: "Incidencias", cuenta: pe?.con_incidencia },
      { valor: "retrasado" as Filtro, texto: "Retrasados", cuenta: pe?.retrasado },
      { valor: "entregado" as Filtro, texto: "Entregados", cuenta: pe?.entregado },
    ];
  }, [resumen.datos]);

  return (
    <>
      <Encabezado titulo="Envíos" subtitulo="Ciclo de vida completo, de la orden a la prueba de entrega.">
        <Boton onClick={() => setCreando(true)}>
          <IconMas /> Nuevo envío
        </Boton>
      </Encabezado>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="max-w-full overflow-x-auto">
          <Segmentado opciones={opciones} valor={filtro} onChange={setFiltro} />
        </div>
        <div className="relative w-full sm:w-64">
          <IconBuscar className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-label-3" />
          <Input placeholder="Buscar código, cliente, destino" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 pl-9 text-[14px]" />
        </div>
      </div>

      <Card padding={false} className="overflow-hidden">
        {error && <div className="p-4"><ErrorCaja mensaje={error} /></div>}
        {cargando && !datos ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Esqueleto key={i} className="h-14" />)}</div>
        ) : !datos?.length ? (
          <Vacio icono={<IconCaja className="size-10" />} titulo="No hay envíos" texto="Crea el primero con «Nuevo envío»." />
        ) : (
          <ul className="divide-y divide-hairline">
            {datos.map((e) => {
              const est = ESTADO_ENVIO[e.estado];
              const riesgo = !["entregado", "devuelto"].includes(e.estado) && new Date(e.fecha_limite_sla).getTime() - Date.now() < 2 * 3600_000;
              return (
                <li key={e.id}>
                  <button onClick={() => setDetalle(e.id)} className="grid w-full grid-cols-[1fr_auto] items-center gap-4 px-5 py-3.5 text-left transition hover:bg-fill/60 sm:grid-cols-[110px_1fr_110px_170px_auto]">
                    <span className="font-mono text-[13px] font-medium">{e.codigo}</span>
                    <span className="min-w-0">
                      <span className="block truncate text-[15px] font-medium">
                        {e.origen} → {e.destino}
                        <span className="ml-2 inline-flex gap-1 align-middle text-label-3">
                          {e.requiere_refrigeracion && <IconCopo />}
                          {e.es_hazmat && <IconPeligro />}
                        </span>
                      </span>
                      <span className="block truncate text-[13px] text-label-2">{e.cliente}</span>
                    </span>
                    <span className="hidden text-[13px] sm:block">
                      <span className="block text-label-3">Vehículo</span>
                      <span className="font-medium">{e.vehiculo_placa ?? "—"}</span>
                    </span>
                    <span className="hidden text-[13px] sm:block">
                      <span className="block text-label-3">SLA</span>
                      <span className={cx("font-medium tabular whitespace-nowrap", riesgo && "text-orange")}>{fmtFecha(e.fecha_limite_sla)}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge tono={est.tono} punto>{est.texto}</Badge>
                      <IconChevron className="size-4 text-label-3" />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Hoja abierta={creando} onCerrar={() => setCreando(false)} titulo="Nuevo envío">
        <FormularioEnvio
          onCreado={(e) => {
            setCreando(false);
            recargar();
            setDetalle(e.id);
          }}
        />
      </Hoja>
      <Hoja abierta={!!detalle} onCerrar={() => setDetalle(null)} titulo="Detalle del envío" ancho="max-w-2xl">
        {detalle && <DetalleEnvio id={detalle} onCambio={() => { recargar(); resumen.recargar(); }} />}
      </Hoja>
    </>
  );
}
