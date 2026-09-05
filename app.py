import os
import uuid
import subprocess
import tempfile
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import boto3
from botocore.client import Config
from PIL import Image
from datetime import datetime

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


# Catálogo de productos simulado (sin BD, se sustituirá por Printful/Gelato)
PRODUCTOS = [
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
    return render_template('shop.html', productos=PRODUCTOS, obras=obras_imprimibles)


@app.route('/shop/<producto_id>')
def shop_detalle(producto_id):
    producto = next((p for p in PRODUCTOS if p['id'] == producto_id), None)
    if not producto:
        return redirect(url_for('shop'))
    obra_id = request.args.get('obra_id', type=int)
    obras_imprimibles = Obra.query.filter_by(imprimible=True, tipo='imagen').order_by(Obra.fecha_subida.desc()).all()
    obra_seleccionada = Obra.query.get(obra_id) if obra_id else (obras_imprimibles[0] if obras_imprimibles else None)
    return render_template('shop_detalle.html',
                           producto=producto,
                           obras=obras_imprimibles,
                           obra=obra_seleccionada,
                           productos=PRODUCTOS)


@app.route('/api/obras')
def api_obras():
    obras = Obra.query.order_by(Obra.fecha_subida.desc()).all()
    return jsonify([o.to_dict() for o in obras])


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
