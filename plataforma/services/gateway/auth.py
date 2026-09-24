"""Autenticación: JWT RS256 firmados por el gateway, validados localmente sin llamar a nadie.

- Access token de 15 min (configurable) y refresh token de 7 días, rotativo: cada uso emite uno
  nuevo e invalida el anterior; reutilizar uno ya usado revoca toda la sesión.
- Contraseñas con Argon2id. Los usuarios de demostración viven en memoria (no hay servicio de
  usuarios en el alcance de este entregable).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ACCESS_MIN = int(os.getenv("JWT_ACCESS_MINUTOS", "15"))
REFRESH_DIAS = int(os.getenv("JWT_REFRESH_DIAS", "7"))
ISSUER = "logitrack-gateway"

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)  # Argon2id


def _cargar_claves() -> tuple[bytes, bytes]:
    privada_pem = os.getenv("JWT_PRIVATE_KEY")
    if privada_pem:
        privada = serialization.load_pem_private_key(privada_pem.encode(), password=None)
    else:
        # Desarrollo: par de claves efímero. En producción se inyecta JWT_PRIVATE_KEY.
        privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    privada_bytes = privada.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    publica_bytes = privada.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return privada_bytes, publica_bytes


CLAVE_PRIVADA, CLAVE_PUBLICA = _cargar_claves()

_USUARIOS_DEMO = [
    ("admin", "admin123", "admin", "Administradora LogiTrack"),
    ("operador", "operador123", "operador", "Operador logístico"),
    ("gestor", "gestor123", "gestor_flota", "Gestor de flota"),
    ("conductor", "conductor123", "conductor", "Conductor"),
]
USUARIOS = {
    u: {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{u}.logitrack")), "usuario": u, "rol": r, "nombre": n,
        "hash": _hasher.hash(p)}
    for u, p, r, n in _USUARIOS_DEMO
}


def verificar_credenciales(usuario: str, clave: str) -> dict | None:
    u = USUARIOS.get(usuario)
    if not u:
        _hasher.hash(clave)  # igualar el tiempo de respuesta: no revela qué usuarios existen
        return None
    try:
        _hasher.verify(u["hash"], clave)
        return u
    except VerifyMismatchError:
        return None


def _firmar(claims: dict, duracion: timedelta) -> str:
    ahora = datetime.now(timezone.utc)
    return jwt.encode(
        {**claims, "iss": ISSUER, "iat": ahora, "exp": ahora + duracion, "jti": uuid.uuid4().hex},
        CLAVE_PRIVADA,
        algorithm="RS256",
    )


def emitir_tokens(usuario: dict, familia: str | None = None) -> tuple[dict, str, str]:
    """Devuelve (respuesta, jti del refresh, familia de sesión)."""
    familia = familia or uuid.uuid4().hex
    base = {"sub": usuario["id"], "usuario": usuario["usuario"], "rol": usuario["rol"], "nombre": usuario["nombre"]}
    access = _firmar({**base, "tipo": "access"}, timedelta(minutes=ACCESS_MIN))
    refresh = _firmar({**base, "tipo": "refresh", "familia": familia}, timedelta(days=REFRESH_DIAS))
    jti = jwt.decode(refresh, CLAVE_PUBLICA, algorithms=["RS256"], issuer=ISSUER)["jti"]
    respuesta = {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": ACCESS_MIN * 60,
        "usuario": {k: usuario[k] for k in ("id", "usuario", "rol", "nombre")},
    }
    return respuesta, jti, familia


def decodificar(token: str, tipo: str = "access") -> dict:
    claims = jwt.decode(token, CLAVE_PUBLICA, algorithms=["RS256"], issuer=ISSUER)
    if claims.get("tipo") != tipo:
        raise jwt.InvalidTokenError("Tipo de token incorrecto")
    return claims
