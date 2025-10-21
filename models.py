from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

import pytz

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telefone = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(100))
    estado_atual = db.Column(db.String(50), default='inicio')
    temp_servico_id = db.Column(db.Integer)
    temp_data = db.Column(db.String(10))

    agendamentos = db.relationship('Agendamento', backref='usuario', lazy=True)

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.String(500))
    duracao_minutos = db.Column(db.Integer, default=60)

    agendamentos = db.relationship('Agendamento', backref='servico', lazy=True)

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    
    # Armazenaremos a data e hora sempre em UTC para consistência
    data_hora = db.Column(db.DateTime, nullable=False) 
    
    # O status agora é mais flexível
    status = db.Column(db.String(20), default='Aberto') # Status: Aberto, Confirmado, Concluido, Cancelado
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(pytz.utc))