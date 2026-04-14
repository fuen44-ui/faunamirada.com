import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import cloudinary.api
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///faunamirada.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

db = SQLAlchemy(app)


class Obra(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    artista = db.Column(db.String(200), default='Fauna Mirada')
    año = db.Column(db.String(10))
    descripcion = db.Column(db.Text)
    tecnica = db.Column(db.String(100))
    categoria = db.Column(db.String(100), default='Pintura')
    tipo = db.Column(db.String(10), default='imagen')  # imagen o video
    cloudinary_url = db.Column(db.String(500))
    cloudinary_public_id = db.Column(db.String(200))
    thumbnail_url = db.Column(db.String(500))
    destacada = db.Column(db.Boolean, default=False)
    en_portfolio = db.Column(db.Boolean, default=False)
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
            'url': self.cloudinary_url,
            'thumbnail': self.thumbnail_url or self.cloudinary_url,
            'destacada': self.destacada,
        }


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
            resource_type = 'video' if es_video else 'image'
            resultado = cloudinary.uploader.upload(
                archivo,
                folder='faunamirada',
                resource_type=resource_type,
                transformation=[{'quality': 'auto', 'fetch_format': 'auto'}] if not es_video else []
            )

            cloudinary_url = resultado['secure_url']
            public_id = resultado['public_id']

            # Thumbnail para videos
            if es_video:
                thumbnail_url = cloudinary.utils.cloudinary_url(
                    public_id,
                    resource_type='video',
                    format='jpg',
                    transformation=[{'width': 800, 'crop': 'fill'}]
                )[0]
            else:
                thumbnail_url = cloudinary.utils.cloudinary_url(
                    public_id,
                    transformation=[{'width': 800, 'crop': 'fill', 'quality': 'auto'}]
                )[0]

            obra = Obra(
                titulo=titulo,
                artista=request.form.get('artista', 'Fauna Mirada'),
                año=request.form.get('año', ''),
                descripcion=request.form.get('descripcion', ''),
                tecnica=request.form.get('tecnica', ''),
                categoria=request.form.get('categoria', 'Pintura'),
                tipo=tipo,
                cloudinary_url=cloudinary_url,
                cloudinary_public_id=public_id,
                thumbnail_url=thumbnail_url,
                destacada='destacada' in request.form,
                en_portfolio='en_portfolio' in request.form
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
        if obra.cloudinary_public_id:
            resource_type = 'video' if obra.tipo == 'video' else 'image'
            cloudinary.uploader.destroy(obra.cloudinary_public_id, resource_type=resource_type)
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


@app.route('/api/obras')
def api_obras():
    obras = Obra.query.order_by(Obra.fecha_subida.desc()).all()
    return jsonify([o.to_dict() for o in obras])


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
