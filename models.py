from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz 

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telefone = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(100))
    estado_atual = db.Column(db.String(50), default='inicio')
    
    # Campos temporários de agendamento
    temp_servico_id = db.Column(db.Integer)
    temp_data = db.Column(db.String(10))
    
    # Campos temporários do esboço
    temp_endereco = db.Column(db.String(200))
    temp_queixa = db.Column(db.String(500))
    temp_btus = db.Column(db.String(50))
    temp_marca = db.Column(db.String(100))

    # Campo de Timeout
    last_interaction_time = db.Column(db.DateTime, default=lambda: datetime.now(pytz.utc))

    # --- [MODIFICADO] Relação explícita ---
    agendamentos = db.relationship('Agendamento', back_populates='usuario', lazy=True)

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.String(500))
    duracao_minutos = db.Column(db.Integer, default=60)

    # --- [MODIFICADO] Relação explícita ---
    agendamentos = db.relationship('Agendamento', back_populates='servico', lazy=True)

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    
    data_hora = db.Column(db.DateTime, nullable=False) 
    status = db.Column(db.String(20), default='Aberto')
    
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(pytz.utc))
    
    # Campos permanentes do esboço
    endereco = db.Column(db.String(200))
    queixa = db.Column(db.String(500))
    btus = db.Column(db.String(50))
    marca = db.Column(db.String(100))
    
    # --- [ADICIONADO] Relações explícitas ---
    # Isso corrige o erro do Flask-Admin
    usuario = db.relationship('Usuario', back_populates='agendamentos')
    servico = db.relationship('Servico', back_populates='agendamentos')