from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# Renomeado de Cliente para Usuario
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telefone = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(100))
    # estado_atual controla a conversa do bot
    estado_atual = db.Column(db.String(50), default='inicio')
    # Campos temporários para guardar informações durante o agendamento
    temp_servico_id = db.Column(db.Integer)
    temp_data = db.Column(db.String(10)) # Formato DD/MM/YYYY

    agendamentos = db.relationship('Agendamento', backref='usuario', lazy=True)

# Novo modelo para os serviços oferecidos
class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.String(500))
    duracao_minutos = db.Column(db.Integer, default=60) # Duração padrão de 60 min

    agendamentos = db.relationship('Agendamento', backref='servico', lazy=True)

# Novo modelo para os agendamentos
class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='Confirmado') # Ex: Confirmado, Cancelado
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)