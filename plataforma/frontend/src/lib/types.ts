export type Rol = "admin" | "operador" | "gestor_flota" | "conductor" | "cliente";

export interface Usuario {
  id: string;
  usuario: string;
  rol: Rol;
  nombre: string;
}

export type EstadoVehiculo = "activo" | "en_transito" | "en_mantenimiento" | "fuera_de_servicio";
export type TipoVehiculo = "furgon" | "camion" | "tractomula" | "van";

export interface Vehiculo {
  id: string;
  placa: string;
  tipo: TipoVehiculo;
  marca: string;
  capacidad_kg: number;
  capacidad_m3: number;
  anio: number;
  vencimiento_seguro: string;
  estado: EstadoVehiculo;
  refrigerado: boolean;
  certificado_hazmat: boolean;
  zona: string;
  actualizado_en: string;
  conductor: { id: string; nombre: string } | null;
}

export interface Conductor {
  id: string;
  nombre: string;
  numero_licencia: string;
  telefono: string | null;
  certificacion_hazmat: boolean;
  horas_conducidas_semana: number;
  categorias: string[];
  vehiculo_placa: string | null;
}

export type EstadoEnvio = "pendiente" | "en_transito" | "con_incidencia" | "retrasado" | "entregado" | "devuelto";

export interface EventoEnvio {
  tipo_evento: string;
  ocurrido_en: string;
  notas: string | null;
}

export interface Envio {
  id: string;
  codigo: string;
  cliente: string;
  cliente_email: string | null;
  origen: string;
  destino: string;
  origen_lat: number;
  origen_lon: number;
  destino_lat: number;
  destino_lon: number;
  estado: EstadoEnvio;
  fecha_limite_sla: string;
  es_internacional: boolean;
  requiere_refrigeracion: boolean;
  es_hazmat: boolean;
  peso_kg: number;
  volumen_m3: number;
  vehiculo_id: string | null;
  vehiculo_placa: string | null;
  creado_en: string;
  actualizado_en: string;
}

export interface EnvioDetalle extends Envio {
  eventos: EventoEnvio[];
  prueba: {
    nombre_receptor: string;
    entregado_en: string;
    url_firma: string | null;
    url_foto: string | null;
  } | null;
}

export interface Posicion {
  vehiculo_id: string;
  registrado_en: string;
  lat: number;
  lon: number;
  velocidad_kmh: number;
  nivel_combustible: number;
  temperatura_c: number | null;
  temperatura_motor_c: number;
  odometro_km: number;
  codigo_obd2: string | null;
}

export interface Alerta {
  id: string;
  vehiculo_id: string;
  metrica: string;
  valor: string;
  mensaje: string;
  prioridad: number;
  estado: "abierta" | "cerrada";
  creada_en: string;
  cerrada_en: string | null;
}

export interface Programa {
  id: string;
  vehiculo_id: string;
  tipo: string;
  fecha_prevista: string;
  km_previsto: number | null;
  prioridad: number;
  estado: "programado" | "completado";
  km_actual: number | null;
  km_restantes: number | null;
  dias_restantes: number | null;
}

export interface Intervencion {
  id: string;
  vehiculo_id: string;
  programa_id: string | null;
  descripcion: string;
  realizado_en: string;
  costo: number;
  taller: string;
  km_al_servicio: number;
}

export interface Regla {
  id: string;
  nombre: string;
  metrica: string;
  operador: "mayor" | "menor" | "presente";
  umbral: number;
  prioridad: number;
  activa: boolean;
  tipo_vehiculo: string | null;
}

export interface EventoDominio {
  event_id: string;
  tipo: string;
  origen: string;
  ocurrido_en: string;
  datos: Record<string, unknown>;
}

export interface EstadoServicio {
  servicio: string;
  ok: boolean;
  latencia_ms: number;
  circuito: string;
}
