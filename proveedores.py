import uuid


class ProveedorBase:
    """Interfaz común para cualquier proveedor de impresión bajo demanda.

    Para añadir un proveedor nuevo: crear una subclase con nombre único,
    implementar crear_pedido() mapeando nuestro pedido a su API, y añadirla
    a obtener_proveedor(). Cambiar de proveedor en producción no requiere
    tocar código: se hace desde /admin/ajustes.
    """
    nombre = 'base'

    def crear_pedido(self, pedido):
        raise NotImplementedError

    def consultar_precio(self, producto):
        """Devuelve el coste actual que cobra el proveedor por `producto`
        (un modelo Producto de app.py, con su producto.proveedor_ref), o
        lanza NotImplementedError si este proveedor aún no puede consultarlo."""
        raise NotImplementedError


class ProveedorSimulado(ProveedorBase):
    """Proveedor por defecto: no imprime nada de verdad, solo registra el
    pedido como si se hubiera enviado. Se usa mientras no haya una cuenta
    real de Printful/Gelato configurada en Ajustes, para poder probar todo
    el flujo de carrito y pago sin depender de terceros."""
    nombre = 'simulado'

    def crear_pedido(self, pedido):
        return f"SIMULADO-{uuid.uuid4().hex[:10]}"

    def consultar_precio(self, producto):
        # No hay proveedor real detrás: el coste no cambia solo.
        return producto.precio_coste


class ProveedorPrintful(ProveedorBase):
    """Integración con la API de Printful (https://developers.printful.com).

    Pendiente de completar cuando haya cuenta real: falta el mapeo entre
    nuestros producto_id (taza, camiseta...) y los variant_id concretos del
    catálogo de Printful, que se define al sincronizar productos en su
    panel. Sin ese mapeo, esta clase no puede construir un pedido válido.
    """
    nombre = 'printful'

    def __init__(self, api_key):
        self.api_key = api_key

    def crear_pedido(self, pedido):
        raise NotImplementedError(
            'Falta configurar el mapeo de productos a variant_id de Printful '
            'antes de poder enviar pedidos reales.'
        )

    def consultar_precio(self, producto):
        if not producto.proveedor_ref:
            raise NotImplementedError(
                f'"{producto.nombre}" no tiene un variant_id de Printful asignado '
                '(campo "ID/variant del proveedor").'
            )
        raise NotImplementedError(
            'Falta completar la llamada real a la API de Printful '
            '(GET /products/variant/{id}) para consultar precios.'
        )


class ProveedorGelato(ProveedorBase):
    """Integración con la API de Gelato (https://docs.gelato.com).

    Igual que Printful: pendiente del mapeo de nuestros producto_id a los
    product UID de Gelato una vez exista cuenta real.
    """
    nombre = 'gelato'

    def __init__(self, api_key):
        self.api_key = api_key

    def crear_pedido(self, pedido):
        raise NotImplementedError(
            'Falta configurar el mapeo de productos al catálogo de Gelato '
            'antes de poder enviar pedidos reales.'
        )

    def consultar_precio(self, producto):
        if not producto.proveedor_ref:
            raise NotImplementedError(
                f'"{producto.nombre}" no tiene un product UID de Gelato asignado '
                '(campo "ID/variant del proveedor").'
            )
        raise NotImplementedError(
            'Falta completar la llamada real a la API de Gelato para consultar precios.'
        )


def obtener_proveedor(get_ajuste):
    """get_ajuste es la función get_ajuste(clave, default) de app.py —
    se pasa por parámetro para no crear un import circular."""
    activo = get_ajuste('proveedor_activo', 'simulado')

    if activo == 'printful':
        clave = get_ajuste('printful_api_key', '')
        return ProveedorPrintful(clave) if clave else ProveedorSimulado()

    if activo == 'gelato':
        clave = get_ajuste('gelato_api_key', '')
        return ProveedorGelato(clave) if clave else ProveedorSimulado()

    return ProveedorSimulado()
