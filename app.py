from flask import Flask, request, jsonify, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from config import DATABASE_URL
from models import db, Cliente, Chamado
from flask_cors import CORS
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
import os
from dotenv import load_dotenv
from models import db, Usuario, Servico, Agendamento 

load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY")

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
# Configurar painel de administração
admin = Admin(app, name='My Admin Panel', template_mode='bootstrap3')



def criar_tabelas():
    with app.app_context():
        db.create_all()


brasil_tz = pytz.timezone('America/Sao_Paulo')
utc_tz = pytz.utc

from twilio.rest import Client

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER')
# Instanciar o cliente Twilio com as credenciais
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


login_manager = LoginManager(app)
login_manager.login_view = 'login'


# Função para criar tabelas
def criar_tabelas():
    with app.app_context():
        db.create_all()

# Modelo de usuário com senha segura
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(600), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Admin protegido
class MyAdminIndexView(AdminIndexView):
    @expose('/')
    def index(self):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        return super().index()

class SecureModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated

# Classes de visualização do Admin (pode customizar colunas, etc.)
class UsuarioModelView(SecureModelView):
    column_list = ['nome', 'telefone', 'estado_atual'] # Colunas que aparecem na lista
    column_searchable_list = ['nome', 'telefone'] # Campos pesquisáveis

class ServicoModelView(SecureModelView):
    column_list = ['nome', 'duracao_minutos']
    form_columns = ['nome', 'descricao', 'duracao_minutos'] # Campos no form de criação/edição

class AgendamentoModelView(SecureModelView):
    column_list = ['usuario.nome', 'servico.nome', 'data_hora', 'status']
    column_filters = ['status', 'data_hora']

# Registrar views do admin
with app.app.context():

    # Adicione as novas views
    admin.add_view(UsuarioModelView(Usuario, db.session))
    admin.add_view(ServicoModelView(Servico, db.session, name='Serviços'))
    admin.add_view(AgendamentoModelView(Agendamento, db.session))
    admin.add_view(SecureModelView(User, db.session, name='Admins'))
# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect('/admin')
        return 'Usuário ou senha inválidos'
    return '''
        <form method="post">
            <h3>Login</h3>
            Usuário: <input type="text" name="username"><br>
            Senha: <input type="password" name="password"><br>
            <input type="submit" value="Entrar">
        </form>
    '''

# Rota de logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return 'Deslogado com sucesso'

# Rota para criar admin (use só 1x!)
@app.route('/criar_admin')
def criar_admin():
    admin_username = os.environ.get("ADMIN_USERNAME")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    admin_existente = User.query.filter_by(username=admin_username).first()
    if admin_existente:
        return f'Usuário "{admin_username}" já existe.'
    
    novo_admin = User(username=admin_username)
    novo_admin.set_password(admin_password)
    db.session.add(novo_admin)
    db.session.commit()
    
    return f'Usuário administrador "{admin_username}" criado com sucesso!'

@app.route('/')
def index():
    return render_template('index.html')  # Ou o caminho para o arquivo HTML

@app.route('/atender')
def atender():
    id_chamado = request.args.get("id_chamado")
    colaborador = request.args.get("colaborador")

    chamado = Chamado.query.filter_by(id=id_chamado).first()

    if not chamado:
        return {"erro": "Chamado não encontrado"}, 404

    chamado.status = "emandamento"
    chamado.pessoa_em_andamento = colaborador
    db.session.commit()

    return jsonify({"mensagem": "Chamado atualizado com sucesso"}), 200



def listar_servicos_formatado():
    """Busca os serviços no DB e retorna uma string formatada."""
    servicos = Servico.query.all()
    if not servicos:
        return "Nenhum serviço disponível no momento."
    lista_texto = "Estes são os nossos serviços:\n\n"
    for i, servico in enumerate(servicos, 1):
        lista_texto += f"{i}️⃣ - *{servico.nome}*\n"
    return lista_texto

def gerar_horarios_disponiveis(data_str):
    """Gera uma lista de horários disponíveis para uma data."""
    # Lógica simplificada: horários fixos das 9h às 17h, de hora em hora.
    # Numa aplicação real, você consultaria o banco para ver horários já agendados.
    horarios = []
    try:
        data_obj = datetime.strptime(data_str, "%d/%m/%Y").date()
        # Lógica para não agendar no passado
        if data_obj < datetime.now(brasil_tz).date():
            return []
            
        hora_inicio = 9
        hora_fim = 17
        for i, hora in enumerate(range(hora_inicio, hora_fim + 1)):
            horarios.append(f"{i+1} - {hora}:00")
        return horarios
    except ValueError:
        return []

# --- Rota Principal do Bot ---

@app.route("/bot", methods=["POST"])
def processar_mensagem():
    dados = request.form
    telefone_usuario = dados.get("From", "").replace("whatsapp:", "")
    mensagem_usuario = dados.get("Body", "").strip()
    resposta = MessagingResponse()

    # GRUPO_INTERNO para notificações de novos agendamentos
    GRUPO_INTERNO = 'whatsapp:+55SEUNUMERODEGRUPO' 

    # Busca ou cria o usuário
    usuario = Usuario.query.filter_by(telefone=telefone_usuario).first()
    if not usuario:
        usuario = Usuario(telefone=telefone_usuario, estado_atual="aguardando_nome")
        db.session.add(usuario)
        db.session.commit()
        resposta.message("Olá! Bem-vindo(a) ao nosso sistema de agendamento. Para começar, qual o seu nome?")
        return str(resposta)

    # --- Máquina de Estados da Conversa ---

    # 1. Recebendo o nome do usuário
    if usuario.estado_atual == "aguardando_nome":
        usuario.nome = mensagem_usuario
        usuario.estado_atual = "menu_principal"
        db.session.commit()
        resposta.message(f"Olá, {usuario.nome}!\nComo posso te ajudar hoje?\n\n"
                         "1️⃣ Ver Serviços\n"
                         "2️⃣ Agendar um Serviço\n"
                         "3️⃣ Meus Agendamentos")
        return str(resposta)

    # Lógica de voltar para o menu
    if mensagem_usuario.lower() == 'menu':
        usuario.estado_atual = "menu_principal"
        db.session.commit()
        resposta.message(f"Ok, {usuario.nome}. Voltamos ao menu principal.\n\n"
                         "1️⃣ Ver Serviços\n"
                         "2️⃣ Agendar um Serviço\n"
                         "3️⃣ Meus Agendamentos")
        return str(resposta)
        
    # 2. Menu Principal
    if usuario.estado_atual == "menu_principal":
        if mensagem_usuario == "1":
            resposta.message(listar_servicos_formatado())
            resposta.message("Digite '2' para agendar ou 'menu' para voltar.")
        elif mensagem_usuario == "2":
            usuario.estado_atual = "agendando_servico"
            db.session.commit()
            resposta.message(listar_servicos_formatado())
            resposta.message("\nPor favor, digite o *número* do serviço que você deseja agendar.")
        elif mensagem_usuario == "3":
            # Lógica para mostrar agendamentos (a ser implementada)
            resposta.message("Funcionalidade 'Meus Agendamentos' em desenvolvimento.")
        else:
            resposta.message("Opção inválida. Por favor, escolha uma das opções abaixo:\n"
                             "1️⃣ Ver Serviços\n"
                             "2️⃣ Agendar um Serviço\n"
                             "3️⃣ Meus Agendamentos")
        return str(resposta)

    # 3. Etapa de Agendamento: Escolha do serviço
    if usuario.estado_atual == "agendando_servico":
        try:
            servicos = Servico.query.all()
            servico_escolhido = servicos[int(mensagem_usuario) - 1]
            usuario.temp_servico_id = servico_escolhido.id
            usuario.estado_atual = "agendando_data"
            db.session.commit()
            resposta.message(f"Ótima escolha! Vamos agendar o serviço: *{servico_escolhido.nome}*.\n\n"
                             "Por favor, digite a data que você deseja (ex: 31/12/2025).")
        except (ValueError, IndexError):
            resposta.message("Por favor, digite um *número válido* da lista de serviços.")
        return str(resposta)

    # 4. Etapa de Agendamento: Escolha da data
    if usuario.estado_atual == "agendando_data":
        horarios = gerar_horarios_disponiveis(mensagem_usuario)
        if not horarios:
            resposta.message("Data inválida ou no passado. Por favor, digite uma data futura no formato DD/MM/YYYY.")
            return str(resposta)
            
        usuario.temp_data = mensagem_usuario
        usuario.estado_atual = "agendando_horario"
        db.session.commit()
        
        horarios_texto = "\n".join(horarios)
        resposta.message(f"Estes são os horários disponíveis para {mensagem_usuario}:\n\n"
                         f"{horarios_texto}\n\n"
                         "Digite o *número* do horário que você prefere.")
        return str(resposta)

    # 5. Etapa de Agendamento: Escolha do horário e confirmação
    if usuario.estado_atual == "agendando_horario":
        try:
            horarios_disponiveis = gerar_horarios_disponiveis(usuario.temp_data)
            horario_selecionado_str = horarios_disponiveis[int(mensagem_usuario) - 1].split(" - ")[1] # Pega "HH:MM"
            hora, minuto = map(int, horario_selecionado_str.split(':'))
            
            data_agendamento = datetime.strptime(usuario.temp_data, "%d/%m/%Y")
            data_hora_agendamento = datetime(data_agendamento.year, data_agendamento.month, data_agendamento.day, hour=hora, minute=minuto)
            
            # Salvar no banco
            novo_agendamento = Agendamento(
                usuario_id=usuario.id,
                servico_id=usuario.temp_servico_id,
                data_hora=data_hora_agendamento
            )
            db.session.add(novo_agendamento)
            
            # Limpar dados temporários e voltar ao menu
            usuario.estado_atual = "menu_principal"
            usuario.temp_data = None
            usuario.temp_servico_id = None
            db.session.commit()

            servico = Servico.query.get(novo_agendamento.servico_id)

            # Mensagem de confirmação para o cliente
            resposta.message(f"✅ Agendamento Confirmado!\n\n"
                             f"Serviço: *{servico.nome}*\n"
                             f"Data: *{novo_agendamento.data_hora.strftime('%d/%m/%Y')}*\n"
                             f"Horário: *{novo_agendamento.data_hora.strftime('%H:%M')}*\n\n"
                             "Obrigado! Para um novo serviço, basta enviar uma mensagem.")
            
            # Mensagem de notificação para o grupo interno
            mensagem_grupo = (
                f"🎉 Novo Agendamento!\n\n"
                f"Cliente: {usuario.nome}\n"
                f"Telefone: {usuario.telefone}\n"
                f"Serviço: {servico.nome}\n"
                f"Data: {novo_agendamento.data_hora.strftime('%d/%m/%Y às %H:%M')}"
            )
            client.messages.create(
                body=mensagem_grupo,
                from_=os.environ.get('TWILIO_WHATSAPP_NUMBER'),
                to=GRUPO_INTERNO
            )
            
        except (ValueError, IndexError):
            resposta.message("Por favor, digite um *número de horário válido* da lista.")
        
        return str(resposta)


    # Mensagem padrão caso o estado se perca
    usuario.estado_atual = 'menu_principal'
    db.session.commit()
    resposta.message(f"Desculpe, não entendi. Vamos voltar ao menu principal.\n\n"
                     "1️⃣ Ver Serviços\n"
                     "2️⃣ Agendar um Serviço\n"
                     "3️⃣ Meus Agendamentos")
    return str(resposta)


@app.route("/chamados_abertos", methods=["GET"])
def chamados_abertos():
    
    # Obter todos os chamados abertos, separados por setor
    chamados_ti = Chamado.query.filter_by(setor="TI", status="Aberto").all()
    chamados_manutencao = Chamado.query.filter_by(setor="Manutenção", status="Aberto").all()
    chamados_apoio = Chamado.query.filter_by(setor="Apoio", status="Aberto").all()
    
    # Organizar os dados para enviar como JSON
    chamados_data = {
        "TI": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": utc_tz.localize(chamado.horario_criacao).astimezone(brasil_tz).strftime('%H:%M') if chamado.horario_criacao else None,
            "chamado_id": chamado.chamado_id,
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome
        } for chamado in chamados_ti],
        
        "Manutencao": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": utc_tz.localize(chamado.horario_criacao).astimezone(brasil_tz).strftime('%H:%M') if chamado.horario_criacao else None,
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome
        } for chamado in chamados_manutencao],
        
        "Apoio": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": utc_tz.localize(chamado.horario_criacao).astimezone(brasil_tz).strftime('%H:%M') if chamado.horario_criacao else None,
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "sala": chamado.sala
        } for chamado in chamados_apoio]
    }
    
    return jsonify(chamados_data)


@app.route("/chamados_concluidos", methods=["GET"])
def chamados_concluidos():
    
    # Obter todos os chamados concluidos, separados por setor
    chamados_ti = Chamado.query.filter_by(setor="TI", status="Concluído").all()
    chamados_manutencao = Chamado.query.filter_by(setor="Manutenção", status="Concluído").all()
    chamados_apoio = Chamado.query.filter_by(setor="Apoio", status="Concluído").all()
    
    # Organizar os dados para enviar como JSON
    chamados_data = {
        "TI": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": chamado.horario_criacao.strftime('%H:%M'),
            "chamado_id": chamado.chamado_id,
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "pessoa_conclusao": chamado.pessoa_conclusao,
            "data": chamado.data.strftime('%d/%m/%Y')
        } for chamado in chamados_ti],
        
        "Manutencao": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": chamado.horario_criacao.strftime('%H:%M'),
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "pessoa_conclusao": chamado.pessoa_conclusao,
            "data": chamado.data.strftime('%d/%m/%Y')
        } for chamado in chamados_manutencao],
        
        "Apoio": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": chamado.horario_criacao.strftime('%H:%M'),
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "pessoa_conclusao": chamado.pessoa_conclusao,
            "sala": chamado.sala,
            "data": chamado.data.strftime('%d/%m/%Y')
        } for chamado in chamados_apoio]
    }
    
    return jsonify(chamados_data)

@app.route("/chamados_andamento", methods=["GET"])
def chamados_andamento():
    
    # Obter todos os chamados concluidos, separados por setor
    chamados_ti = Chamado.query.filter_by(setor="TI", status="Em andamento").all()
    chamados_manutencao = Chamado.query.filter_by(setor="Manutenção", status="Em andamento").all()
    chamados_apoio = Chamado.query.filter_by(setor="Apoio", status="Em andamento").all()
    
    # Organizar os dados para enviar como JSON
    chamados_data = {
        "TI": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": chamado.horario_criacao.strftime('%H:%M'),
            "chamado_id": chamado.chamado_id,
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "pessoa_conclusao": chamado.pessoa_conclusao,
            "pessoa_em_andamento": chamado.pessoa_em_andamento,
            "data": chamado.data
        } for chamado in chamados_ti],
        
        "Manutencao": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": chamado.horario_criacao.strftime('%H:%M'),
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "pessoa_conclusao": chamado.pessoa_conclusao,
            "pessoa_em_andamento": chamado.pessoa_em_andamento,
            "data": chamado.data
        } for chamado in chamados_manutencao],
        
        "Apoio": [{
            "id": chamado.id,
            "descricao": chamado.descricao,
            "status":chamado.status,
            "data_criacao": chamado.data_criacao.strftime('%d/%m/%Y'),
            "horario_criacao": chamado.horario_criacao.strftime('%H:%M'),
            "setor_cliente": chamado.setor_cliente,
            "nome": chamado.nome,
            "pessoa_conclusao": chamado.pessoa_conclusao,
            "pessoa_em_andamento": chamado.pessoa_em_andamento,
            "sala": chamado.sala,
            "data": chamado.data
        } for chamado in chamados_apoio]
    }
    
    return jsonify(chamados_data)


@app.route('/chamados-atender/<int:id>', methods=['POST'])
def atender_chamado(id):
    data = request.get_json()

    nome_responsavel = data.get("nome")
    telefone_responsavel = data.get("telefone")

    if not nome_responsavel or not telefone_responsavel:
        return jsonify({"erro": "Nome e telefone são obrigatórios."}), 400

    chamado = Chamado.query.get_or_404(id)

    if chamado.status != "Aberto":
        return jsonify({"erro": "Chamado já foi atendido ou está em andamento."}), 400

    chamado.pessoa_em_andamento = nome_responsavel
    chamado.status = "Em andamento"

    db.session.commit()

    return jsonify({
        "mensagem": "Chamado atribuído com sucesso.",
        "chamado_id": chamado.id,
        "responsavel": nome_responsavel
    })

@app.route('/chamados-concluir/<int:id>', methods=['POST'])
def concluir_chamado(id):
    data = request.get_json()

    nome_responsavel = data.get("nome")
    telefone_responsavel = data.get("telefone")

    if not nome_responsavel or not telefone_responsavel:
        return jsonify({"erro": "Nome e telefone são obrigatórios."}), 400

    chamado = Chamado.query.get_or_404(id)

    if chamado.status != "Aberto" and chamado.status != "Em andamento":
        return jsonify({"erro": "Chamado já foi atendido ou está em andamento."}), 400

    chamado.horario = datetime.now(brasil_tz).time()
    chamado.data = datetime.now().date()
    chamado.pessoa_conclusao = nome_responsavel
    chamado.status = "Concluído"

    db.session.commit()

    return jsonify({
        "mensagem": "Chamado concluído com sucesso.",
        "chamado_id": chamado.id,
        "responsavel": nome_responsavel
    })
    
if __name__ == "__main__":
    criar_tabelas()  # Garantir que as tabelas sejam criadas
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))