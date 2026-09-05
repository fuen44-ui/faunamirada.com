import os
import json
import uuid
from functools import wraps
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import boto3
from botocore.client import Config
from PIL import Image
from datetime import datetime

from proveedores import obtener_proveedor

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///faunamirada.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '').rstrip('/')

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    config=Config(signature_version='s3v4'),
    region_name='auto',
)

db = SQLAlchemy(app)


def subir_a_r2(datos, key, content_type):
    s3.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=datos, ContentType=content_type)
    return f'{R2_PUBLIC_URL}/{key}'


def generar_miniatura(imagen_bytes):
    img = Image.open(BytesIO(imagen_bytes))
    img = img.convert('RGB')
    img.thumbnail((800, 800))
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


class Obra(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    artista = db.Column(db.String(200), default='Fauna Mirada')
    año = db.Column(db.String(10))
    descripcion = db.Column(db.Text)
    tecnica = db.Column(db.String(100))
    categoria = db.Column(db.String(100), default='Pintura')
    tipo = db.Column(db.String(10), default='imagen')  # imagen o video
    archivo_url = db.Column(db.String(500))
    archivo_key = db.Column(db.String(200))
    thumbnail_url = db.Column(db.String(500))
    thumbnail_key = db.Column(db.String(200))
    destacada = db.Column(db.Boolean, default=False)
    en_portfolio = db.Column(db.Boolean, default=False)
    imprimible = db.Column(db.Boolean, default=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'titulo': self.titulo,
            'artista': self.artista,
            'año': self.año,
            'descripcion': self.descripcion,
            'tecnica': self.tecnica,
            'categoria': self.categoria,
            'tipo': self.tipo,
            'url': self.archivo_url,
            'thumbnail': self.thumbnail_url or self.archivo_url,
            'destacada': self.destacada,
        }


class Ajuste(db.Model):
    clave = db.Column(db.String(100), primary_key=True)
    valor = db.Column(db.Text, default='')


def get_ajuste(clave, default=''):
    a = db.session.get(Ajuste, clave)
    return a.valor if a and a.valor else default


def set_ajuste(clave, valor):
    a = db.session.get(Ajuste, clave)
    if a:
        a.valor = valor
    else:
        db.session.add(Ajuste(clave=clave, valor=valor))
    db.session.commit()


class Producto(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    icono = db.Column(db.String(10), default='🎁')
    imagen_base = db.Column(db.String(500))
    precio = db.Column(db.Float, default=0)  # PVP al cliente, IVA incluido
    precio_coste = db.Column(db.Float, default=0)  # lo que cobra el proveedor de impresión
    iva = db.Column(db.Float, default=21)
    transporte = db.Column(db.Float, default=0)  # coste de envío que asumes tú
    proveedor_ref = db.Column(db.String(200))  # id/variant del producto en Printful/Gelato/...
    precio_coste_revisado_en = db.Column(db.DateTime)
    alerta_precio = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True)

    @property
    def precio_sin_iva(self):
        return self.precio / (1 + (self.iva or 0) / 100) if self.precio else 0

    @property
    def margen(self):
        return self.precio_sin_iva - (self.precio_coste or 0) - (self.transporte or 0)

    @property
    def margen_porcentaje(self):
        base = self.precio_sin_iva
        return (self.margen / base * 100) if base else 0


class Oferta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    precio = db.Column(db.Float, nullable=False)
    portes_incluidos = db.Column(db.Boolean, default=True)
    activa = db.Column(db.Boolean, default=True)
    items = db.relationship('OfertaItem', backref='oferta', cascade='all, delete-orphan')


class OfertaItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    oferta_id = db.Column(db.Integer, db.ForeignKey('oferta.id'), nullable=False)
    producto_id = db.Column(db.String(50), nullable=False)
    cantidad = db.Column(db.Integer, default=1)


class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stripe_session_id = db.Column(db.String(200))
    email = db.Column(db.String(200))
    items = db.Column(db.Text)
    total = db.Column(db.Float)
    estado = db.Column(db.String(50), default='pagado')
    proveedor = db.Column(db.String(50))
    proveedor_pedido_id = db.Column(db.String(200))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


def requiere_login(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if not session.get('admin'):
            flash('Debes iniciar sesión para acceder', 'error')
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorada


# Catálogo inicial: se carga en la tabla Producto la primera vez que arranca
# la app (si está vacía). A partir de ahí se edita desde /admin/productos.
PRODUCTOS_INICIALES = [
    {
        'id': 'taza',
        'nombre': 'Taza',
        'descripcion': 'Taza de cerámica de 330ml con tu obra favorita.',
        'precio': 18.90,
        'imagen_base': 'https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?w=600&q=80',
        'icono': '☕',
    },
    {
        'id': 'camiseta',
        'nombre': 'Camiseta',
        'descripcion': 'Camiseta 100% algodón orgánico, tallas XS–XXL.',
        'precio': 29.90,
        'imagen_base': 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=600&q=80',
        'icono': '👕',
    },
    {
        'id': 'sudadera',
        'nombre': 'Sudadera',
        'descripcion': 'Sudadera unisex con capucha, interior afelpado.',
        'precio': 49.90,
        'imagen_base': 'https://images.unsplash.com/photo-1556821840-3a63f15732ce?w=600&q=80',
        'icono': '🧥',
    },
    {
        'id': 'bolsa',
        'nombre': 'Bolsa de tela',
        'descripcion': 'Bolsa tote 100% algodón, resistente y reutilizable.',
        'precio': 14.90,
        'imagen_base': 'https://images.unsplash.com/photo-1597633544424-20d0b6ec3094?w=600&q=80',
        'icono': '👜',
    },
    {
        'id': 'postal',
        'nombre': 'Postal',
        'descripcion': 'Postal de papel satinado 350g, 15×10cm.',
        'precio': 4.90,
        'imagen_base': 'https://images.unsplash.com/photo-1607344645866-009c320c5ab8?w=600&q=80',
        'icono': '📮',
    },
]


with app.app_context():
    db.create_all()
    if not get_ajuste('admin_password_hash'):
        clave_inicial = os.getenv('ADMIN_PASSWORD', 'faunamirada2026')
        set_ajuste('admin_password_hash', generate_password_hash(clave_inicial))
    if Producto.query.count() == 0:
        for p in PRODUCTOS_INICIALES:
            db.session.add(Producto(
                id=p['id'], nombre=p['nombre'], descripcion=p['descripcion'],
                icono=p['icono'], imagen_base=p['imagen_base'], precio=p['precio'],
            ))
        db.session.commit()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        clave = request.form.get('password', '')
        hash_guardado = get_ajuste('admin_password_hash')
        if hash_guardado and check_password_hash(hash_guardado, clave):
            session['admin'] = True
            flash('Sesión iniciada', 'success')
            return redirect(request.args.get('next') or url_for('galeria'))
        flash('Contraseña incorrecta', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('admin', None)
    flash('Sesión cerrada', 'success')
    return redirect(url_for('galeria'))


@app.route('/')
def galeria():
    categoria = request.args.get('categoria', '')
    if categoria:
        obras = Obra.query.filter_by(categoria=categoria).order_by(Obra.fecha_subida.desc()).all()
    else:
        obras = Obra.query.order_by(Obra.fecha_subida.desc()).all()

    categorias = db.session.query(Obra.categoria).distinct().all()
    categorias = [c[0] for c in categorias if c[0]]
    destacadas = Obra.query.filter_by(destacada=True).limit(3).all()

    return render_template('galeria.html',
                           obras=obras,
                           categorias=categorias,
                           categoria_activa=categoria,
                           destacadas=destacadas)


@app.route('/obra/<int:id>')
def detalle(id):
    obra = Obra.query.get_or_404(id)
    relacionadas = Obra.query.filter(
        Obra.categoria == obra.categoria,
        Obra.id != obra.id
    ).limit(4).all()
    return render_template('detalle.html', obra=obra, relacionadas=relacionadas)


@app.route('/subir', methods=['GET', 'POST'])
@requiere_login
def subir():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        if not titulo:
            flash('El título es obligatorio', 'error')
            return redirect(url_for('subir'))

        archivo = request.files.get('archivo')
        if not archivo or archivo.filename == '':
            flash('Debes seleccionar un archivo', 'error')
            return redirect(url_for('subir'))

        # Detectar tipo
        nombre = archivo.filename.lower()
        es_video = any(nombre.endswith(ext) for ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv'])
        tipo = 'video' if es_video else 'imagen'

        try:
            ext = os.path.splitext(nombre)[1]
            clave = f'faunamirada/{uuid.uuid4().hex}{ext}'
            datos = archivo.read()

            archivo_url = subir_a_r2(datos, clave, archivo.mimetype)

            thumbnail_url = None
            clave_thumb = None
            if not es_video:
                clave_thumb = f'faunamirada/thumb_{uuid.uuid4().hex}.jpg'
                miniatura = generar_miniatura(datos)
                thumbnail_url = subir_a_r2(miniatura, clave_thumb, 'image/jpeg')

            obra = Obra(
                titulo=titulo,
                artista=request.form.get('artista', 'Fauna Mirada'),
                año=request.form.get('año', ''),
                descripcion=request.form.get('descripcion', ''),
                tecnica=request.form.get('tecnica', ''),
                categoria=request.form.get('categoria', 'Pintura'),
                tipo=tipo,
                archivo_url=archivo_url,
                archivo_key=clave,
                thumbnail_url=thumbnail_url,
                thumbnail_key=clave_thumb,
                destacada='destacada' in request.form,
                en_portfolio='en_portfolio' in request.form,
                imprimible='imprimible' in request.form
            )
            db.session.add(obra)
            db.session.commit()

            flash('Obra publicada correctamente', 'success')
            return redirect(url_for('detalle', id=obra.id))

        except Exception as e:
            flash(f'Error al subir el archivo: {str(e)}', 'error')
            return redirect(url_for('subir'))

    categorias_default = ['Pintura', 'Escultura', 'Fotografía', 'Ilustración', 'Digital', 'Mixta']
    return render_template('subir.html', categorias=categorias_default)


@app.route('/eliminar/<int:id>', methods=['POST'])
@requiere_login
def eliminar(id):
    obra = Obra.query.get_or_404(id)
    try:
        if obra.archivo_key:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=obra.archivo_key)
        if obra.thumbnail_key:
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=obra.thumbnail_key)
        db.session.delete(obra)
        db.session.commit()
        flash('Obra eliminada', 'success')
    except Exception as e:
        flash(f'Error al eliminar: {str(e)}', 'error')
    return redirect(url_for('galeria'))


@app.route('/portfolio')
def portfolio():
    obras = Obra.query.filter_by(en_portfolio=True).order_by(Obra.fecha_subida.desc()).all()
    return render_template('portfolio.html', obras=obras)


@app.route('/shop')
def shop():
    obras_imprimibles = Obra.query.filter_by(imprimible=True, tipo='imagen').order_by(Obra.fecha_subida.desc()).all()
    ofertas = Oferta.query.filter_by(activa=True).all()
    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('shop.html', productos=productos, obras=obras_imprimibles, ofertas=ofertas)


@app.route('/shop/<producto_id>')
def shop_detalle(producto_id):
    producto = db.session.get(Producto, producto_id)
    if not producto or not producto.activo:
        return redirect(url_for('shop'))
    obra_id = request.args.get('obra_id', type=int)
    obras_imprimibles = Obra.query.filter_by(imprimible=True, tipo='imagen').order_by(Obra.fecha_subida.desc()).all()
    obra_seleccionada = Obra.query.get(obra_id) if obra_id else (obras_imprimibles[0] if obras_imprimibles else None)
    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('shop_detalle.html',
                           producto=producto,
                           obras=obras_imprimibles,
                           obra=obra_seleccionada,
                           productos=productos)


@app.route('/api/obras')
def api_obras():
    obras = Obra.query.order_by(Obra.fecha_subida.desc()).all()
    return jsonify([o.to_dict() for o in obras])


# --- Ajustes (proveedor de impresión + pasarela de pago) ---

@app.route('/admin/ajustes', methods=['GET', 'POST'])
@requiere_login
def admin_ajustes():
    claves = ['proveedor_activo', 'printful_api_key', 'gelato_api_key',
              'stripe_secret_key', 'stripe_publishable_key', 'stripe_webhook_secret']
    if request.method == 'POST':
        for clave in claves:
            set_ajuste(clave, request.form.get(clave, '').strip())
        nueva_password = request.form.get('nueva_password', '').strip()
        if nueva_password:
            set_ajuste('admin_password_hash', generate_password_hash(nueva_password))
        flash('Ajustes guardados', 'success')
        return redirect(url_for('admin_ajustes'))
    valores = {clave: get_ajuste(clave) for clave in claves}
    return render_template('admin_ajustes.html', valores=valores)


# --- Productos y precios ---

@app.route('/admin/productos', methods=['GET', 'POST'])
@requiere_login
def admin_productos():
    if request.method == 'POST':
        pid = request.form.get('id', '').strip().lower()
        if not pid:
            flash('Falta el identificador del producto', 'error')
            return redirect(url_for('admin_productos'))
        producto = db.session.get(Producto, pid) or Producto(id=pid)
        producto.nombre = request.form.get('nombre', '').strip() or pid
        producto.descripcion = request.form.get('descripcion', '').strip()
        producto.icono = request.form.get('icono', '🎁').strip() or '🎁'
        producto.imagen_base = request.form.get('imagen_base', '').strip()
        producto.precio = float(request.form.get('precio', 0) or 0)
        producto.precio_coste = float(request.form.get('precio_coste', 0) or 0)
        producto.iva = float(request.form.get('iva', 21) or 0)
        producto.transporte = float(request.form.get('transporte', 0) or 0)
        producto.proveedor_ref = request.form.get('proveedor_ref', '').strip()
        producto.alerta_precio = False
        db.session.add(producto)
        db.session.commit()
        flash('Producto guardado', 'success')
        return redirect(url_for('admin_productos'))
    productos = Producto.query.order_by(Producto.nombre).all()
    return render_template('admin_productos.html', productos=productos)


@app.route('/admin/productos/<id>/toggle', methods=['POST'])
@requiere_login
def admin_productos_toggle(id):
    producto = Producto.query.get_or_404(id)
    producto.activo = not producto.activo
    db.session.commit()
    return redirect(url_for('admin_productos'))


@app.route('/admin/productos/<id>/comprobar-precio', methods=['POST'])
@requiere_login
def admin_productos_comprobar_precio(id):
    producto = Producto.query.get_or_404(id)
    proveedor = obtener_proveedor(get_ajuste)
    try:
        precio_actual = proveedor.consultar_precio(producto)
        producto.precio_coste_revisado_en = datetime.utcnow()
        if precio_actual is not None and abs(precio_actual - (producto.precio_coste or 0)) > 0.005:
            producto.alerta_precio = True
            flash(
                f'El proveedor ({proveedor.nombre}) cobra ahora {precio_actual:.2f}€ por '
                f'"{producto.nombre}" (antes {producto.precio_coste:.2f}€). Revisa el coste y el margen.',
                'error'
            )
        else:
            producto.alerta_precio = False
            flash('Sin cambios en el precio del proveedor', 'success')
        db.session.commit()
    except NotImplementedError as e:
        flash(str(e), 'error')
    return redirect(url_for('admin_productos'))


# --- Ofertas / combos ---

@app.route('/admin/ofertas', methods=['GET', 'POST'])
@requiere_login
def admin_ofertas():
    if request.method == 'POST':
        oferta = Oferta(
            nombre=request.form.get('nombre', '').strip(),
            descripcion=request.form.get('descripcion', '').strip(),
            precio=float(request.form.get('precio', 0) or 0),
            portes_incluidos='portes_incluidos' in request.form,
        )
        db.session.add(oferta)
        db.session.flush()
        for producto_id, cantidad in zip(request.form.getlist('producto_id'), request.form.getlist('cantidad')):
            if producto_id and cantidad and int(cantidad) > 0:
                db.session.add(OfertaItem(oferta_id=oferta.id, producto_id=producto_id, cantidad=int(cantidad)))
        db.session.commit()
        flash('Oferta creada', 'success')
        return redirect(url_for('admin_ofertas'))
    ofertas = Oferta.query.order_by(Oferta.id.desc()).all()
    productos = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    return render_template('admin_ofertas.html', ofertas=ofertas, productos=productos)


@app.route('/admin/ofertas/<int:id>/toggle', methods=['POST'])
@requiere_login
def admin_ofertas_toggle(id):
    oferta = Oferta.query.get_or_404(id)
    oferta.activa = not oferta.activa
    db.session.commit()
    return redirect(url_for('admin_ofertas'))


@app.route('/admin/ofertas/<int:id>/eliminar', methods=['POST'])
@requiere_login
def admin_ofertas_eliminar(id):
    oferta = Oferta.query.get_or_404(id)
    db.session.delete(oferta)
    db.session.commit()
    flash('Oferta eliminada', 'success')
    return redirect(url_for('admin_ofertas'))


@app.route('/admin/pedidos')
@requiere_login
def admin_pedidos():
    pedidos = Pedido.query.order_by(Pedido.fecha.desc()).all()
    return render_template('admin_pedidos.html', pedidos=pedidos)


# --- Carrito y checkout ---

def _detalle_carrito():
    carrito = session.get('carrito', [])
    detalles = []
    total = 0
    for idx, it in enumerate(carrito):
        if it['tipo'] == 'producto':
            producto = db.session.get(Producto, it['producto_id'])
            if not producto:
                continue
            obra = db.session.get(Obra, it['obra_id'])
            subtotal = producto.precio * it['cantidad']
            detalles.append({
                'idx': idx, 'tipo': 'producto', 'nombre': producto.nombre,
                'obra_titulo': obra.titulo if obra else '',
                'imagen': (obra.thumbnail_url or obra.archivo_url) if obra else producto.imagen_base,
                'cantidad': it['cantidad'], 'precio_unidad': producto.precio, 'subtotal': subtotal,
            })
        else:
            oferta = db.session.get(Oferta, it['oferta_id'])
            if not oferta:
                continue
            subtotal = oferta.precio * it['cantidad']
            detalles.append({
                'idx': idx, 'tipo': 'oferta', 'nombre': oferta.nombre,
                'obra_titulo': '', 'imagen': None,
                'cantidad': it['cantidad'], 'precio_unidad': oferta.precio, 'subtotal': subtotal,
            })
        total += subtotal
    return detalles, total


@app.route('/carrito')
def carrito():
    detalles, total = _detalle_carrito()
    return render_template('carrito.html', items=detalles, total=total)


@app.route('/carrito/agregar', methods=['POST'])
def carrito_agregar():
    carrito = session.get('carrito', [])
    tipo = request.form.get('tipo')
    cantidad = max(1, int(request.form.get('cantidad', 1) or 1))
    if tipo == 'producto':
        carrito.append({
            'tipo': 'producto',
            'producto_id': request.form.get('producto_id'),
            'obra_id': request.form.get('obra_id', type=int),
            'cantidad': cantidad,
        })
    elif tipo == 'oferta':
        carrito.append({
            'tipo': 'oferta',
            'oferta_id': request.form.get('oferta_id', type=int),
            'cantidad': cantidad,
        })
    session['carrito'] = carrito
    session.modified = True
    flash('Añadido al carrito', 'success')
    return redirect(request.referrer or url_for('shop'))


@app.route('/carrito/quitar/<int:idx>', methods=['POST'])
def carrito_quitar(idx):
    carrito = session.get('carrito', [])
    if 0 <= idx < len(carrito):
        carrito.pop(idx)
    session['carrito'] = carrito
    session.modified = True
    return redirect(url_for('carrito'))


@app.route('/checkout', methods=['POST'])
def checkout():
    import stripe
    clave_stripe = get_ajuste('stripe_secret_key')
    if not clave_stripe:
        flash('La tienda todavía no tiene configurado el cobro online. Contacta con el administrador.', 'error')
        return redirect(url_for('carrito'))

    detalles, total = _detalle_carrito()
    if not detalles:
        flash('El carrito está vacío', 'error')
        return redirect(url_for('carrito'))

    stripe.api_key = clave_stripe
    line_items = [{
        'price_data': {
            'currency': 'eur',
            'product_data': {'name': f"{d['nombre']}" + (f" — {d['obra_titulo']}" if d['obra_titulo'] else '')},
            'unit_amount': round(d['precio_unidad'] * 100),
        },
        'quantity': d['cantidad'],
    } for d in detalles]

    checkout_session = stripe.checkout.Session.create(
        mode='payment',
        line_items=line_items,
        shipping_address_collection={'allowed_countries': ['ES', 'PT', 'FR', 'IT', 'DE']},
        success_url=url_for('checkout_exito', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=url_for('carrito', _external=True),
        metadata={'carrito': json.dumps(session.get('carrito', []))},
    )
    return redirect(checkout_session.url, code=303)


@app.route('/checkout/exito')
def checkout_exito():
    session.pop('carrito', None)
    return render_template('checkout_exito.html')


@app.route('/webhook/stripe', methods=['POST'])
def webhook_stripe():
    import stripe
    payload = request.data
    firma = request.headers.get('Stripe-Signature', '')
    secreto = get_ajuste('stripe_webhook_secret')

    try:
        if secreto:
            evento = stripe.Webhook.construct_event(payload, firma, secreto)
        else:
            evento = json.loads(payload)
    except Exception:
        return '', 400

    if evento.get('type') == 'checkout.session.completed':
        datos = evento['data']['object']
        carrito = json.loads(datos.get('metadata', {}).get('carrito', '[]'))
        pedido = Pedido(
            stripe_session_id=datos.get('id'),
            email=(datos.get('customer_details') or {}).get('email', ''),
            items=json.dumps(carrito),
            total=(datos.get('amount_total') or 0) / 100,
        )
        db.session.add(pedido)
        db.session.commit()

        try:
            proveedor = obtener_proveedor(get_ajuste)
            pedido.proveedor = proveedor.nombre
            pedido.proveedor_pedido_id = proveedor.crear_pedido({
                'pedido_id': pedido.id,
                'carrito': carrito,
                'direccion': datos.get('shipping_details') or datos.get('customer_details'),
            })
            pedido.estado = 'enviado_a_produccion'
        except Exception as e:
            pedido.estado = f'error_proveedor: {e}'
        db.session.commit()

    return '', 200


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
