"""API Gateway — único punto de entrada público de LogiTrack.

Por cada petición: CORS por lista blanca → valida JWT RS256 localmente → rate limiting (token por
minuto en Redis, según rol) → enruta por prefijo a la red privada → log JSON con request_id →
errores normalizados. Además expone un feed de eventos del bus en vivo (SSE) para el panel.
"""
import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager

import httpx
import jwt
import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from common.bus import EventBus
from common.cliente_http import CircuitBreaker
from common.errores import cuerpo_error, error, instalar_manejadores
from common.logs import configurar_logs, request_id_var

from . import auth

configurar_logs("gateway")
log = logging.getLogger("gateway")

SERVICIOS = {
    "fleet": os.getenv("FLEET_URL", "http://fleet:8000"),
    "tracking": os.getenv("TRACKING_URL", "http://tracking:8000"),
    "shipment": os.getenv("SHIPMENT_URL", "http://shipment:8000"),
    "maintenance": os.getenv("MAINTENANCE_URL", "http://maintenance:8000"),
}
# Enrutamiento por prefijo: /api/v1/<prefijo>/** → servicio
PREFIJOS = {
    "vehiculos": "fleet",
    "conductores": "fleet",
    "asignaciones": "fleet",
    "telemetria": "tracking",
    "dispositivos": "tracking",
    "envios": "shipment",
    "mantenimiento": "maintenance",
}
LIMITES_POR_MINUTO = {"admin": 600, "operador": 600, "gestor_flota": 600, "conductor": 300, "cliente": 120,
                      "anonimo": 30, "login": 10}
EVENTOS_OCULTOS_EN_FEED = ("telemetry.",)  # alto volumen: el panel las consulta por REST
COOKIE_REFRESH = "lt_refresh"
COOKIE_SEGURA = os.getenv("COOKIE_SECURE", "false").lower() == "true"

redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
circuitos = {nombre: CircuitBreaker(nombre) for nombre in SERVICIOS}
bus = EventBus(os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/"), "gateway")
feed: deque[dict] = deque(maxlen=100)
oyentes: set[asyncio.Queue] = set()


async def al_evento(evento: dict) -> None:
    if evento.get("tipo", "").startswith(EVENTOS_OCULTOS_EN_FEED):
        return
    feed.append(evento)
    for cola in list(oyentes):
        if cola.qsize() < 100:
            cola.put_nowait(evento)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await bus.conectar()
    await bus.suscribir_efimera(["#"], al_evento)
    log.info("API Gateway listo")
    yield
    await bus.cerrar()
    await http.aclose()
    await redis.aclose()


app = FastAPI(title="LogiTrack · API Gateway", version="1.0.0", lifespan=lifespan)
instalar_manejadores(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "no-referrer"
    if COOKIE_SEGURA:
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return respuesta


# ---------------------------------------------------------------- utilidades


async def limitar(clave: str, rol: str) -> None:
    """Rate limiting por ventana de un minuto con contadores en Redis. Si Redis cae, no bloquea."""
    limite = LIMITES_POR_MINUTO.get(rol, 120)
    ventana = int(time.time() // 60)
    try:
        llave = f"rl:{clave}:{ventana}"
        n = await redis.incr(llave)
        if n == 1:
            await redis.expire(llave, 65)
    except Exception as exc:
        log.warning("Redis no disponible para rate limiting: %s", exc)
        return
    if n > limite:
        exc = error(429, "limite_excedido", f"Límite de {limite} peticiones por minuto excedido")
        exc.headers = {"Retry-After": str(60 - int(time.time()) % 60)}
        raise exc


def ip_cliente(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]


def identidad(request: Request, token: str | None = None) -> dict:
    if token is None:
        cabecera = request.headers.get("authorization", "")
        token = cabecera[7:] if cabecera.lower().startswith("bearer ") else None
    if not token:
        raise error(401, "no_autenticado", "Falta el token de acceso")
    try:
        return auth.decodificar(token)
    except jwt.ExpiredSignatureError:
        raise error(401, "token_expirado", "El token de acceso expiró")
    except jwt.InvalidTokenError:
        raise error(401, "token_invalido", "El token de acceso no es válido")


# ---------------------------------------------------------------- autenticación


class Credenciales(BaseModel):
    usuario: str = Field(min_length=1, max_length=60)
    clave: str = Field(min_length=1, max_length=128)


def _poner_cookie(respuesta: Response, refresh: str) -> None:
    respuesta.set_cookie(
        COOKIE_REFRESH, refresh, max_age=auth.REFRESH_DIAS * 86400, httponly=True, secure=COOKIE_SEGURA,
        samesite="strict", path="/api/v1/auth",
    )


async def _guardar_refresh(jti: str, familia: str) -> None:
    ttl = auth.REFRESH_DIAS * 86400
    await redis.set(f"refresh:{jti}", familia, ex=ttl)
    await redis.set(f"familia:{familia}", "activa", ex=ttl)


@app.post("/api/v1/auth/token", tags=["auth"])
async def token(datos: Credenciales, request: Request):
    await limitar(f"login:{ip_cliente(request)}", "login")
    usuario = auth.verificar_credenciales(datos.usuario, datos.clave)
    if not usuario:
        raise error(401, "credenciales_invalidas", "Usuario o contraseña incorrectos")
    cuerpo, jti, familia = auth.emitir_tokens(usuario)
    await _guardar_refresh(jti, familia)
    respuesta = JSONResponse({k: v for k, v in cuerpo.items() if k != "refresh_token"})
    _poner_cookie(respuesta, cuerpo["refresh_token"])
    return respuesta


@app.post("/api/v1/auth/refresh", tags=["auth"])
async def refrescar(request: Request):
    """Rotación de refresh tokens: reutilizar uno ya usado delata un robo y revoca la sesión."""
    refresh = request.cookies.get(COOKIE_REFRESH)
    if not refresh:
        raise error(401, "sin_sesion", "No hay sesión activa")
    try:
        claims = auth.decodificar(refresh, "refresh")
    except jwt.InvalidTokenError:
        raise error(401, "sesion_invalida", "La sesión expiró; vuelve a iniciar sesión")
    familia = claims["familia"]
    if not await redis.getdel(f"refresh:{claims['jti']}"):
        await redis.delete(f"familia:{familia}")
        log.warning("Reutilización de refresh token detectada; sesión revocada")
        raise error(401, "sesion_revocada", "La sesión fue revocada por seguridad")
    if not await redis.exists(f"familia:{familia}"):
        raise error(401, "sesion_revocada", "La sesión fue cerrada")
    usuario = auth.USUARIOS.get(claims["usuario"])
    if not usuario:
        raise error(401, "sesion_invalida", "El usuario ya no existe")
    cuerpo, jti, _ = auth.emitir_tokens(usuario, familia)
    await _guardar_refresh(jti, familia)
    respuesta = JSONResponse({k: v for k, v in cuerpo.items() if k != "refresh_token"})
    _poner_cookie(respuesta, cuerpo["refresh_token"])
    return respuesta


@app.post("/api/v1/auth/logout", tags=["auth"])
async def logout(request: Request):
    refresh = request.cookies.get(COOKIE_REFRESH)
    if refresh:
        try:
            claims = auth.decodificar(refresh, "refresh")
            await redis.delete(f"familia:{claims['familia']}", f"refresh:{claims['jti']}")
        except jwt.InvalidTokenError:
            pass
    respuesta = JSONResponse({"mensaje": "Sesión cerrada"})
    respuesta.delete_cookie(COOKIE_REFRESH, path="/api/v1/auth")
    return respuesta


# ---------------------------------------------------------------- salud y plataforma


@app.get("/health", tags=["salud"])
async def health():
    return {"estado": "vivo", "servicio": "gateway"}


@app.get("/ready", tags=["salud"])
async def ready():
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    listo = redis_ok and bus.conectado
    return JSONResponse({"estado": "listo" if listo else "no_listo", "checks": {"redis": redis_ok, "broker": bus.conectado}},
                        status_code=200 if listo else 503)


async def _sondear(nombre: str, url: str) -> dict:
    inicio = time.perf_counter()
    try:
        r = await http.get(f"{url}/ready", timeout=1.5)
        ok = r.status_code == 200
        detalle = r.json().get("checks", {})
    except Exception:
        ok, detalle = False, {}
    return {"servicio": nombre, "ok": ok, "latencia_ms": round((time.perf_counter() - inicio) * 1000),
            "circuito": circuitos[nombre].estado, "checks": detalle}


@app.get("/api/v1/estado/servicios", tags=["plataforma"])
async def estado_servicios(request: Request):
    identidad(request)
    resultados = await asyncio.gather(*(_sondear(n, u) for n, u in SERVICIOS.items()))
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    infraestructura = [
        {"servicio": "gateway", "ok": True, "latencia_ms": 0, "circuito": "cerrado", "checks": {}},
        {"servicio": "rabbitmq", "ok": bus.conectado, "latencia_ms": 0, "circuito": "cerrado", "checks": {}},
        {"servicio": "redis", "ok": redis_ok, "latencia_ms": 0, "circuito": "cerrado", "checks": {}},
    ]
    return infraestructura + list(resultados)


@app.get("/api/v1/eventos/recientes", tags=["plataforma"])
async def eventos_recientes(request: Request):
    identidad(request)
    return list(reversed(feed))


@app.get("/api/v1/eventos/stream", tags=["plataforma"])
async def eventos_stream(request: Request, token: str):
    """Server-Sent Events con los eventos de dominio del bus (EventSource no admite cabeceras,
    por eso el access token viaja como parámetro solo en este endpoint)."""
    identidad(request, token)
    cola: asyncio.Queue = asyncio.Queue()
    oyentes.add(cola)

    async def generar():
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    evento = await asyncio.wait_for(cola.get(), timeout=15)
                    yield f"event: dominio\ndata: {json.dumps(evento, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": latido\n\n"
        finally:
            oyentes.discard(cola)

    return StreamingResponse(generar(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- proxy


@app.api_route("/api/v1/{ruta:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"], tags=["proxy"])
async def proxy(ruta: str, request: Request):
    prefijo = ruta.split("/", 1)[0]
    nombre = PREFIJOS.get(prefijo)
    if not nombre:
        raise error(404, "ruta_no_encontrada", f"No existe el recurso /api/v1/{prefijo}")

    es_publica = request.method == "GET" and ruta.startswith("envios/seguimiento/")
    if es_publica:
        claims = {"sub": "", "rol": ""}
        await limitar(f"ip:{ip_cliente(request)}", "anonimo")
    else:
        claims = identidad(request)
        await limitar(f"u:{claims['sub']}", claims["rol"])

    circuito = circuitos[nombre]
    if circuito.estado == "abierto":
        raise error(503, "servicio_no_disponible", "El servicio no está disponible; inténtalo en unos segundos")

    cabeceras = {
        "X-Request-ID": request_id_var.get() or "",
        "X-User-Id": claims["sub"],
        "X-User-Role": claims["rol"],
    }
    for h in ("content-type", "idempotency-key", "x-device-key"):
        if h in request.headers:
            cabeceras[h] = request.headers[h]
    try:
        resp = await http.request(
            request.method,
            f"{SERVICIOS[nombre]}/api/v1/{ruta}",
            params=request.query_params,
            content=await request.body(),
            headers=cabeceras,
        )
    except httpx.TransportError as exc:
        circuito.fallo()
        log.error("Servicio %s no responde: %s", nombre, exc)
        return JSONResponse(
            cuerpo_error("servicio_no_disponible", "El servicio no está disponible; inténtalo en unos segundos"),
            status_code=503,
        )
    if resp.status_code >= 500:
        circuito.fallo()
    else:
        circuito.exito()
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"))
