"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONSource, Map as MapaML, Marker } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { ESTADO_VEHICULO } from "@/lib/formato";
import type { Envio, Posicion, Vehiculo } from "@/lib/types";
import { cx } from "./ui";

// Estilo vectorial gratuito sin token (OpenFreeMap). El documento de arquitectura propone
// Mapbox GL JS; MapLibre es su fork abierto y comparte la misma API.
const ESTILO = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://tiles.openfreemap.org/styles/positron";

interface Props {
  vehiculos: Vehiculo[];
  posiciones: Posicion[];
  envios?: Envio[];
  recorrido?: Posicion[];
  seleccionado?: string | null;
  onSeleccionar?: (vehiculoId: string) => void;
  className?: string;
}

type Coleccion = GeoJSON.FeatureCollection<GeoJSON.Geometry>;
const vacio: Coleccion = { type: "FeatureCollection", features: [] };

export default function MapaFlota({ vehiculos, posiciones, envios = [], recorrido = [], seleccionado, onSeleccionar, className }: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapaML | null>(null);
  const marcadores = useRef(new globalThis.Map<string, { marker: Marker; el: HTMLDivElement }>());
  const libreria = useRef<typeof import("maplibre-gl") | null>(null);
  const [listo, setListo] = useState(false);
  const encuadrado = useRef(false);
  const alSeleccionar = useRef(onSeleccionar);
  alSeleccionar.current = onSeleccionar;

  useEffect(() => {
    let cancelado = false;
    import("maplibre-gl").then((ml) => {
      if (cancelado || !contenedor.current) return;
      libreria.current = ml;
      const m = new ml.Map({
        container: contenedor.current,
        style: ESTILO,
        center: [-75.3, 8.9],
        zoom: 6.2,
        attributionControl: { compact: true },
      });
      m.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
      m.on("load", () => {
        m.addSource("rutas", { type: "geojson", data: vacio });
        m.addLayer({
          id: "rutas",
          type: "line",
          source: "rutas",
          paint: { "line-color": "#0a84ff", "line-width": 2.5, "line-opacity": 0.55, "line-dasharray": [2, 2] },
          layout: { "line-cap": "round" },
        });
        m.addSource("destinos", { type: "geojson", data: vacio });
        m.addLayer({
          id: "destinos",
          type: "circle",
          source: "destinos",
          paint: { "circle-radius": 5, "circle-color": "#ffffff", "circle-stroke-color": "#0a84ff", "circle-stroke-width": 2.5 },
        });
        m.addSource("recorrido", { type: "geojson", data: vacio });
        m.addLayer({
          id: "recorrido",
          type: "line",
          source: "recorrido",
          paint: { "line-color": "#5e5ce6", "line-width": 4, "line-opacity": 0.85 },
          layout: { "line-cap": "round", "line-join": "round" },
        });
        setListo(true);
      });
      mapa.current = m;
    });
    const marcadoresActuales = marcadores.current;
    return () => {
      cancelado = true;
      marcadoresActuales.clear();
      mapa.current?.remove();
      mapa.current = null;
    };
  }, []);

  // Marcadores de vehículos
  useEffect(() => {
    const m = mapa.current;
    const ml = libreria.current;
    if (!m || !ml || !listo) return;
    const porId = new globalThis.Map(vehiculos.map((v) => [v.id, v]));
    const vistos = new Set<string>();
    for (const p of posiciones) {
      const v = porId.get(p.vehiculo_id);
      if (!v) continue;
      vistos.add(v.id);
      let entrada = marcadores.current.get(v.id);
      if (!entrada) {
        const el = document.createElement("div");
        el.className = "marcador";
        el.innerHTML = `<span class="punto"></span><span class="placa"></span>`;
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          alSeleccionar.current?.(v.id);
        });
        const marker = new ml.Marker({ element: el, anchor: "left", offset: [-8, 0] }).setLngLat([p.lon, p.lat]).addTo(m);
        entrada = { marker, el };
        marcadores.current.set(v.id, entrada);
      }
      entrada.marker.setLngLat([p.lon, p.lat]);
      const punto = entrada.el.querySelector<HTMLSpanElement>(".punto")!;
      punto.style.background = ESTADO_VEHICULO[v.estado].color;
      entrada.el.querySelector<HTMLSpanElement>(".placa")!.textContent = v.placa;
      entrada.el.classList.toggle("activo", v.id === seleccionado);
      entrada.el.style.zIndex = v.id === seleccionado ? "10" : "1";
    }
    for (const [id, { marker }] of marcadores.current) {
      if (!vistos.has(id)) {
        marker.remove();
        marcadores.current.delete(id);
      }
    }
    if (!encuadrado.current && posiciones.length > 1) {
      const limites = new ml.LngLatBounds();
      posiciones.forEach((p) => limites.extend([p.lon, p.lat]));
      m.fitBounds(limites, { padding: 70, maxZoom: 9, duration: 0 });
      encuadrado.current = true;
    }
  }, [vehiculos, posiciones, seleccionado, listo]);

  // Rutas planificadas (origen → destino) de los envíos en tránsito
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo) return;
    const activos = envios.filter((e) => e.estado === "en_transito" || e.estado === "con_incidencia");
    const posPorVehiculo = new globalThis.Map(posiciones.map((p) => [p.vehiculo_id, p]));
    (m.getSource("rutas") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: activos.map((e) => {
        const p = e.vehiculo_id ? posPorVehiculo.get(e.vehiculo_id) : undefined;
        const desde = p ? [p.lon, p.lat] : [e.origen_lon, e.origen_lat];
        return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [desde, [e.destino_lon, e.destino_lat]] } };
      }),
    });
    (m.getSource("destinos") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: activos.map((e) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [e.destino_lon, e.destino_lat] } })),
    });
  }, [envios, posiciones, listo]);

  // Recorrido del vehículo seleccionado
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo) return;
    (m.getSource("recorrido") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features:
        recorrido.length > 1
          ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: recorrido.map((p) => [p.lon, p.lat]) } }]
          : [],
    });
  }, [recorrido, listo]);

  // Centrar al seleccionar
  useEffect(() => {
    const m = mapa.current;
    if (!m || !seleccionado) return;
    const p = posiciones.find((x) => x.vehiculo_id === seleccionado);
    if (p) m.easeTo({ center: [p.lon, p.lat], zoom: Math.max(m.getZoom(), 8), duration: 800 });
    // Solo al cambiar la selección, no con cada nueva posición.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seleccionado]);

  return <div ref={contenedor} className={cx("overflow-hidden rounded-[20px] bg-fill ring-1 ring-hairline", className)} />;
}
