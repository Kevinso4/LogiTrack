import type { EstadoEnvio, EstadoVehiculo } from "./types";

type Tono = "green" | "accent" | "orange" | "red" | "gray" | "indigo" | "teal";

export const ESTADO_VEHICULO: Record<EstadoVehiculo, { texto: string; tono: Tono; color: string }> = {
  activo: { texto: "Disponible", tono: "green", color: "var(--green)" },
  en_transito: { texto: "En tránsito", tono: "accent", color: "var(--accent)" },
  en_mantenimiento: { texto: "Mantenimiento", tono: "orange", color: "var(--orange)" },
  fuera_de_servicio: { texto: "Fuera de servicio", tono: "red", color: "var(--red)" },
};

export const ESTADO_ENVIO: Record<EstadoEnvio, { texto: string; tono: Tono }> = {
  pendiente: { texto: "Pendiente", tono: "gray" },
  en_transito: { texto: "En tránsito", tono: "accent" },
  con_incidencia: { texto: "Con incidencia", tono: "orange" },
  retrasado: { texto: "Retrasado", tono: "red" },
  entregado: { texto: "Entregado", tono: "green" },
  devuelto: { texto: "Devuelto", tono: "indigo" },
};

export const TIPO_VEHICULO: Record<string, string> = {
  furgon: "Furgón",
  camion: "Camión",
  tractomula: "Tractomula",
  van: "Van",
};

export const PRIORIDAD: Record<number, { texto: string; tono: Tono }> = {
  1: { texto: "Crítica", tono: "red" },
  2: { texto: "Media", tono: "orange" },
  3: { texto: "Baja", tono: "gray" },
};

/** Ciudades con coordenadas para crear envíos (origen/destino) y ubicar la flota. */
export const CIUDADES: { nombre: string; lat: number; lon: number; pais: string }[] = [
  { nombre: "Montería", lat: 8.7479, lon: -75.8814, pais: "CO" },
  { nombre: "Cartagena", lat: 10.391, lon: -75.4794, pais: "CO" },
  { nombre: "Barranquilla", lat: 10.9685, lon: -74.7813, pais: "CO" },
  { nombre: "Sincelejo", lat: 9.3047, lon: -75.3978, pais: "CO" },
  { nombre: "Santa Marta", lat: 11.2408, lon: -74.199, pais: "CO" },
  { nombre: "Medellín", lat: 6.2442, lon: -75.5812, pais: "CO" },
  { nombre: "Bogotá", lat: 4.711, lon: -74.0721, pais: "CO" },
  { nombre: "Cali", lat: 3.4516, lon: -76.532, pais: "CO" },
  { nombre: "Bucaramanga", lat: 7.1193, lon: -73.1227, pais: "CO" },
  { nombre: "Ciudad de Panamá", lat: 8.9824, lon: -79.5199, pais: "PA" },
  { nombre: "Quito", lat: -0.1807, lon: -78.4678, pais: "EC" },
];

const fechaCorta = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const soloFecha = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short", year: "numeric" });
const numero = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 });
const moneda = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });

export const fmtFecha = (iso: string) => fechaCorta.format(new Date(iso));
export const fmtDia = (iso: string) => soloFecha.format(new Date(iso.length === 10 ? `${iso}T12:00:00` : iso));
export const fmtNum = (n: number | null | undefined) => (n == null ? "—" : numero.format(n));
export const fmtCOP = (n: number) => moneda.format(n);

export function hace(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 10) return "ahora";
  if (s < 60) return `hace ${Math.floor(s)} s`;
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
}

/** Descripción legible de un evento de dominio para el feed en vivo. */
export function describirEvento(tipo: string, d: Record<string, unknown>): { titulo: string; detalle: string; tono: Tono } {
  const s = (k: string) => (d[k] == null ? "" : String(d[k]));
  switch (tipo) {
    case "shipment.created":
      return { titulo: `Envío ${s("codigo")} creado`, detalle: `${s("origen")} → ${s("destino")}`, tono: "gray" };
    case "shipment.assigned":
      return { titulo: `${s("codigo")} asignado`, detalle: `Vehículo ${s("placa")} en camino a ${s("destino")}`, tono: "accent" };
    case "shipment.reassigned":
      return { titulo: `${s("codigo")} reasignado`, detalle: `${s("placa_anterior")} → ${s("placa")}`, tono: "indigo" };
    case "shipment.incident":
      return { titulo: `Incidencia en ${s("codigo")}`, detalle: `${s("tipo")}: ${s("descripcion")}`, tono: "orange" };
    case "shipment.delayed":
      return { titulo: `${s("codigo")} retrasado`, detalle: s("motivo"), tono: "red" };
    case "shipment.delivered":
      return { titulo: `${s("codigo")} entregado`, detalle: `Recibido por ${s("receptor")}`, tono: "green" };
    case "shipment.returned":
      return { titulo: `${s("codigo")} devuelto`, detalle: s("motivo") || "Devuelto al remitente", tono: "indigo" };
    case "vehicle.status_changed": {
      const e = ESTADO_VEHICULO[s("estado_nuevo") as EstadoVehiculo];
      return { titulo: `${s("placa")} · ${e?.texto ?? s("estado_nuevo")}`, detalle: s("motivo"), tono: e?.tono ?? "gray" };
    }
    case "maintenance.alert":
      return { titulo: "Alerta de mantenimiento", detalle: s("mensaje"), tono: d.critica ? "red" : "orange" };
    case "maintenance.scheduled":
      return { titulo: "Mantenimiento programado", detalle: `${s("tipo")} · ${s("fecha_prevista")}`, tono: "teal" };
    case "maintenance.completed":
      return { titulo: "Mantenimiento completado", detalle: s("descripcion"), tono: "green" };
    default:
      return { titulo: tipo, detalle: "", tono: "gray" };
  }
}
