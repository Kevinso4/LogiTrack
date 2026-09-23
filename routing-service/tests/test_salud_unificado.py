"""La convención unificada: /health y /ready (defecto 2.1).

Antes routing solo respondía /health/live y /health/ready, así que el
panel.html (que llama /health) y cualquier sonda con la convención de la
mayoría lo pintaba en rojo con un 404: media demo caída en una sustentación.

Ahora responden las dos rutas nuevas, y las viejas quedan como alias exacto:
los healthchecks de Docker y el script de demo siguen funcionando sin tocarlos.
"""


async def test_health_corto_responde(cliente):
    respuesta = await cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "vivo"


async def test_ready_corto_responde(cliente):
    respuesta = await cliente.get("/ready")
    assert respuesta.status_code == 200
    assert respuesta.json()["dependencias"]["basedatos"] == "sano"


async def test_las_rutas_largas_siguen_como_alias(cliente):
    vieja_live = await cliente.get("/health/live")
    vieja_ready = await cliente.get("/health/ready")
    assert vieja_live.status_code == 200
    assert vieja_ready.status_code == 200
    assert vieja_live.json() == {"estado": "vivo", "servicio": "routing-service"}
