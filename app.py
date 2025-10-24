import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from flask_cors import CORS
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
from datetime import datetime, timedelta 

# --- Configuração Inicial ---
load_dotenv()
app = Flask(__name__)
CORS(app)

# Carregar das variáveis de ambiente
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Credenciais do Twilio
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER')
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Lista de telefones de administradores (do .env)
ADMIN_PHONES = os.environ.get("ADMIN_PHONES", "").split(",")

# Banco de Dados e Modelos
from models import db, Usuario, Servico, Agendamento
db.init_app(app)

# Fusos Horários
brasil_tz = pytz.timezone('America/Sao_Paulo')
utc_tz = pytz.utc

# --- Configuração do Admin e Login ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(600), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

class MyAdminIndexView(AdminIndexView):
    @expose('/')
    def index(self):
        if not current_user.is_authenticated: return redirect(url_for('login'))
        return super().index()

class SecureModelView(ModelView):
    def is_accessible(self): return current_user.is_authenticated

class UsuarioModelView(SecureModelView):
    column_list = ['nome', 'telefone', 'estado_atual', 'last_interaction_time']
    column_searchable_list = ['nome', 'telefone']

class ServicoModelView(SecureModelView):
    column_list = ['nome', 'duracao_minutos']
    form_columns = ['nome', 'descricao', 'duracao_minutos']

class AgendamentoModelView(SecureModelView):
    column_list = ['usuario.nome', 'servico.nome', 'data_hora', 'status', 'endereco', 'queixa']
    column_filters = ['status', 'data_hora', 'servico.nome']

admin = Admin(app, name='Painel Admin', template_mode='bootstrap3', index_view=MyAdminIndexView())

with app.app_context():
    admin.add_view(UsuarioModelView(Usuario, db.session))
    admin.add_view(ServicoModelView(Servico, db.session, name='Serviços'))
    admin.add_view(AgendamentoModelView(Agendamento, db.session))
    admin.add_view(SecureModelView(User, db.session, name='Admins'))

# --- Rotas de Autenticação Admin ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect('/admin')
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user); return redirect('/admin')
        return 'Usuário ou senha inválidos'
    return '''<form method="post"><h3>Login</h3>
        Usuário: <input type="text" name="username"><br>
        Senha: <input type="password" name="password"><br>
        <input type="submit" value="Entrar"></form>'''

@app.route('/logout')
@login_required
def logout():
    logout_user(); return 'Deslogado com sucesso'

@app.route('/criar_admin')
def criar_admin():
    db.create_all() 
    admin_username = os.environ.get("ADMIN_USERNAME"); admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_username or not admin_password: return "Variáveis ADMIN_USERNAME ou ADMIN_PASSWORD não definidas."
    admin_existente = User.query.filter_by(username=admin_username).first()
    if admin_existente: return f'Usuário "{admin_username}" já existe. Tabelas verificadas/criadas.'
    novo_admin = User(username=admin_username); novo_admin.set_password(admin_password)
    db.session.add(novo_admin); db.session.commit()
    return f'Admin "{admin_username}" e tabelas criados com sucesso!'

# --- Rotas Públicas ---
@app.route('/')
def index():
    return "<h1>Bot de Agendamento no ar!</h1><p>Aponte o webhook do Twilio para /bot.</p>"

# --- Funções Auxiliares do Bot ---
def listar_servicos_formatado_apenas_lista():
    servicos = Servico.query.all()
    if not servicos:
        return "Nenhum serviço disponível no momento. (Cadastre os serviços no /admin)"
    lista_texto = "Estes são os nossos serviços:\n\n"
    for servico in servicos:
        lista_texto += f"▪️ *{servico.nome}*\n"
    return lista_texto

def listar_servicos_formatado_com_numeros():
    servicos = Servico.query.all()
    if not servicos:
        return "Nenhum serviço disponível no momento. (Cadastre os serviços no /admin)"
    lista_texto = "Estes são os nossos serviços:\n\n"
    for i, servico in enumerate(servicos, 1):
        lista_texto += f"{i}️⃣ - *{servico.nome}*\n"
    return lista_texto

def gerar_horarios_disponiveis(data_str):
    horarios_disponiveis = []
    try:
        data_obj = datetime.strptime(data_str, "%d/%m/%Y").date()
        data_selecionada = brasil_tz.localize(datetime(data_obj.year, data_obj.month, data_obj.day))
        agora_br = datetime.now(brasil_tz)
        if data_selecionada.date() < agora_br.date(): return []
        
        start_day_utc = data_selecionada.astimezone(utc_tz)
        end_day_utc = (data_selecionada + timedelta(days=1)).astimezone(utc_tz)
        start_day_utc_naive = start_day_utc.replace(tzinfo=None)
        end_day_utc_naive = end_day_utc.replace(tzinfo=None)

        agendamentos_no_dia = Agendamento.query.filter(
            Agendamento.data_hora >= start_day_utc_naive,
            Agendamento.data_hora < end_day_utc_naive
        ).all()

        horas_reservadas = set()
        for ag in agendamentos_no_dia:
            hora_agendada_utc = ag.data_hora.replace(tzinfo=utc_tz)
            hora_agendada_br = hora_agendada_utc.astimezone(brasil_tz)
            horas_reservadas.add(hora_agendada_br.strftime('%H:%M'))

        hora_inicio = 9; hora_fim = 17; contador_opcao = 1
        for hora in range(hora_inicio, hora_fim):
            hora_str = f"{hora}:00"; hora_formatada_comparacao = f"{hora:02d}:00"
            horario_do_slot = brasil_tz.localize(datetime(data_obj.year, data_obj.month, data_obj.day, hora, 0))
            if data_obj == agora_br.date() and horario_do_slot < agora_br: continue
            if hora_formatada_comparacao not in horas_reservadas:
                horarios_disponiveis.append(f"{contador_opcao} - {hora_str}")
                contador_opcao += 1
        return horarios_disponiveis
    except Exception as e:
        print(f"Erro ao gerar horários: {e}"); return []

# --- Rota Principal do Bot ---
@app.route("/bot", methods=["POST"])
def processar_mensagem():
    dados = request.form
    telefone_usuario = dados.get("From", "").replace("whatsapp:", "")
    mensagem_usuario = dados.get("Body", "").strip()
    resposta = MessagingResponse()

    GRUPO_INTERNO = os.environ.get("GRUPO_WHATSAPP_INTERNO")
    agora_utc = datetime.now(utc_tz) # Pega a hora atual em UTC

    usuario = Usuario.query.filter_by(telefone=telefone_usuario).first()
    if not usuario:
        usuario = Usuario(telefone=telefone_usuario, 
                          estado_atual="aguardando_nome",
                          last_interaction_time=agora_utc)
        db.session.add(usuario); db.session.commit()
        resposta.message("Olá! Bem-vindo(a) ao nosso sistema de agendamento. Para começar, qual o seu nome?")
        return str(resposta)

    # --- [LÓGICA DE TIMEOUT CORRIGIDA] ---
    if not usuario.last_interaction_time:
        usuario.last_interaction_time = agora_utc
    
    # Garante que o objeto do banco de dados seja 'aware'
    ultima_interacao_aware = usuario.last_interaction_time.replace(tzinfo=utc_tz)
    delta = agora_utc - ultima_interacao_aware
    delta_segundos = delta.total_seconds()
    
    # 900 segundos = 15 minutos
    if delta_segundos > 900 and mensagem_usuario.lower() != 'menu':
        
        # Força o reset do estado e salva
        usuario.estado_atual = "menu_principal"
        usuario.last_interaction_time = agora_utc
        db.session.commit()

        # Envia a mensagem de reset e PÁRA A EXECUÇÃO
        resposta.message(f"Você demorou muito para responder. Vamos recomeçar do menu principal.\n\n"
                         f"1️⃣ Ver Nossos Serviços\n"
                         f"2️⃣ Agendar um Horário")
        return str(resposta) 
    
    # Se não houve timeout, apenas atualiza o tempo e continua
    usuario.last_interaction_time = agora_utc
    db.session.commit()
    # --- [FIM DA LÓGICA DE TIMEOUT] ---

    # --- Comandos de Admin ---
    if telefone_usuario in ADMIN_PHONES:
        if mensagem_usuario.lower().startswith("concluir "):
            try:
                agendamento_id = int(mensagem_usuario.split(" ")[1])
                agendamento = Agendamento.query.get(agendamento_id)
                if agendamento:
                    agendamento.status = 'Concluido'; db.session.commit()
                    resposta.message(f"✅ Agendamento *{agendamento_id}* marcado como Concluído.")
                else: resposta.message(f"Agendamento {agendamento_id} não encontrado.")
            except (ValueError, IndexError):
                resposta.message("Formato inválido. Use: *concluir [ID]*")
            return str(resposta)

    # --- Máquina de Estados da Conversa ---
    if usuario.estado_atual == "aguardando_nome":
        usuario.nome = mensagem_usuario
        usuario.estado_atual = "menu_principal"
        db.session.commit()
        resposta.message(f"Olá, {usuario.nome}!\nComo posso te ajudar hoje?\n\n"
                         "1️⃣ Ver Nossos Serviços\n"
                         "2️⃣ Agendar um Horário")
        return str(resposta)

    if mensagem_usuario.lower() == 'menu':
        usuario.estado_atual = "menu_principal"; db.session.commit()
        resposta.message(f"Ok, {usuario.nome}. Voltamos ao menu principal.\n\n"
                         "1️⃣ Ver Nossos Serviços\n"
                         "2️⃣ Agendar um Horário")
        return str(resposta)
    
    if usuario.estado_atual == "menu_principal":
        if mensagem_usuario == "1":
            servicos_formatados = listar_servicos_formatado_apenas_lista()
            resposta.message(f"{servicos_formatados}\n\nDigite '2' para agendar ou 'menu' para voltar.")
        elif mensagem_usuario == "2":
            usuario.estado_atual = "agendando_servico"
            db.session.commit()
            servicos_formatados = listar_servicos_formatado_com_numeros()
            resposta.message(f"{servicos_formatados}\n\nPor favor, digite o *número* do serviço que você deseja agendar.")
        else:
            resposta.message("Opção inválida. Por favor, escolha uma das opções abaixo:\n"
                             "1️⃣ Ver Nossos Serviços\n"
                             "2️⃣ Agendar um Horário")
        return str(resposta)

    if usuario.estado_atual == "agendando_servico":
        try:
            servicos = Servico.query.all()
            servico_escolhido = servicos[int(mensagem_usuario) - 1]
            usuario.temp_servico_id = servico_escolhido.id
            usuario.estado_atual = "coletando_endereco"
            db.session.commit()
            resposta.message(f"Ótima escolha: *{servico_escolhido.nome}*.\n\n"
                             "Para continuar, por favor, informe o *endereço completo* (Rua, Número, Bairro):")
        except (ValueError, IndexError):
            resposta.message("Por favor, digite um *número válido* da lista de serviços.")
        return str(resposta)

    if usuario.estado_atual == "coletando_endereco":
        usuario.temp_endereco = mensagem_usuario
        usuario.estado_atual = "coletando_queixa"
        db.session.commit()
        resposta.message("Qual a *queixa* do ar-condicionado? (ex: não gela, barulho, pingando, etc.)")
        return str(resposta)

    if usuario.estado_atual == "coletando_queixa":
        usuario.temp_queixa = mensagem_usuario
        usuario.estado_atual = "coletando_btus"
        db.session.commit()
        resposta.message("Quantos *BTUs* tem o aparelho? (ex: 9000, 12000, 18000)")
        return str(resposta)
        
    if usuario.estado_atual == "coletando_btus":
        usuario.temp_btus = mensagem_usuario
        usuario.estado_atual = "coletando_marca"
        db.session.commit()
        resposta.message("Qual a *marca* do ar-condicionado? (ex: LG, Samsung, Consul, etc.)")
        return str(resposta)

    if usuario.estado_atual == "coletando_marca":
        usuario.temp_marca = mensagem_usuario
        usuario.estado_atual = "agendando_data"
        db.session.commit()
        resposta.message("Obrigado pelas informações.\n\n"
                         "Agora, por favor, digite a *data* que você deseja o atendimento (ex: 25/12/2025).")
        return str(resposta)

    if usuario.estado_atual == "agendando_data":
        horarios = gerar_horarios_disponiveis(mensagem_usuario)
        if not horarios:
            resposta.message("Data inválida, no passado ou sem horários disponíveis. Por favor, digite uma data futura no formato DD/MM/YYYY.")
            return str(resposta)
        usuario.temp_data = mensagem_usuario
        usuario.estado_atual = "agendando_horario"
        db.session.commit()
        horarios_texto = "\n".join(horarios)
        resposta.message(f"Estes são os horários disponíveis para {mensagem_usuario}:\n\n"
                         f"{horarios_texto}\n\n"
                         "Digite o *número* do horário que você prefere.")
        return str(resposta)

    if usuario.estado_atual == "agendando_horario":
        try:
            horarios_disponis = gerar_horarios_disponiveis(usuario.temp_data)
            horario_selecionado_str = horarios_disponis[int(mensagem_usuario) - 1].split(" - ")[1]
            hora, minuto = map(int, horario_selecionado_str.split(':'))
            data_agendamento = datetime.strptime(usuario.temp_data, "%d/%m/%Y")
            data_hora_naive = datetime(data_agendamento.year, data_agendamento.month, data_agendamento.day, hour=hora, minute=minuto)
            data_hora_brasil = brasil_tz.localize(data_hora_naive)
            data_hora_utc = data_hora_brasil.astimezone(utc_tz)

            novo_agendamento = Agendamento(
                usuario_id=usuario.id,
                servico_id=usuario.temp_servico_id,
                data_hora=data_hora_utc,
                endereco=usuario.temp_endereco,
                queixa=usuario.temp_queixa,
                btus=usuario.temp_btus,
                marca=usuario.temp_marca
            )
            db.session.add(novo_agendamento)
            
            usuario.estado_atual = "menu_principal"
            usuario.temp_data = None; usuario.temp_servico_id = None;
            usuario.temp_endereco = None; usuario.temp_queixa = None;
            usuario.temp_btus = None; usuario.temp_marca = None;
            db.session.commit()

            servico = Servico.query.get(novo_agendamento.servico_id)

            resposta.message(f"👍 Solicitação de agendamento recebida!\n\n"
                             f"Serviço: *{servico.nome}*\n"
                             f"Data: *{data_hora_brasil.strftime('%d/%m/%Y')}*\n"
                             f"Horário: *{data_hora_brasil.strftime('%H:%M')}*\n\n"
                             "Em breve nossa equipe entrará em contato para confirmar.\n"
                             "Para um novo serviço, digite 'menu'.")
            
            numero_destino = None
            if GRUPO_INTERNO: numero_destino = GRUPO_INTERNO
            elif ADMIN_PHONES: numero_destino = f"whatsapp:{ADMIN_PHONES[0]}" 

            if numero_destino:
                mensagem_notificacao = (
                    f"🔔 *Nova Solicitação (ID: {novo_agendamento.id})*\n\n"
                    f"*Cliente:* {usuario.nome}\n"
                    f"*Telefone:* {usuario.telefone}\n"
                    f"*Serviço:* {servico.nome}\n\n"
                    f"*Data:* {data_hora_brasil.strftime('%d/%m/%Y às %H:%M')}\n\n"
                    f"*Local:* {novo_agendamento.endereco}\n"
                    f"*Queixa:* {novo_agendamento.queixa}\n"
                    f"*BTUs:* {novo_agendamento.btus}\n"
                    f"*Marca:* {novo_agendamento.marca}\n\n"
                    f"Para concluir, responda: *concluir {novo_agendamento.id}*"
                )
                try:
                    client.messages.create(
                        body=mensagem_notificacao,
                        from_=TWILIO_WHATSAPP_NUMBER,
                        to=numero_destino
                    )
                except Exception as e: print(f"Erro ao enviar notificação para {numero_destino}: {e}")
            
        except (ValueError, IndexError):
            resposta.message("Por favor, digite um *número de horário válido* da lista.")
        except Exception as e:
            print(f"Erro inesperado no agendamento: {e}")
            resposta.message("Ocorreu um erro ao tentar agendar. Tente novamente.")
            
        return str(resposta)

    usuario.estado_atual = 'menu_principal'; db.session.commit()
    resposta.message(f"Desculpe, não entendi. Voltamos ao menu principal.\n\n"
                     "1️⃣ Ver Nossos Serviços\n"
                     "2️⃣ Agendar um Horário")
    return str(resposta)

# --- ROTAS DE API (Atualizadas com novos campos) ---
def formatar_agendamento(agendamento):
    data_hora_utc = agendamento.data_hora.replace(tzinfo=utc_tz)
    data_hora_brasil = data_hora_utc.astimezone(brasil_tz)

    return {
        "id_agendamento": agendamento.id,
        "status": agendamento.status,
        "data_agendamento": data_hora_brasil.strftime('%d/%m/%Y'),
        "hora_agendamento": data_hora_brasil.strftime('%H:%M'),
        "data_criacao_utc": agendamento.data_criacao.isoformat(),
        "cliente": {
            "nome": agendamento.usuario.nome,
            "telefone": agendamento.usuario.telefone
        },
        "servico": {
            "nome": agendamento.servico.nome,
            "descricao": agendamento.servico.descricao
        },
        "detalhes": {
            "endereco": agendamento.endereco,
            "queixa": agendamento.queixa,
            "btus": agendamento.btus,
            "marca": agendamento.marca
        }
    }

@app.route("/agendamentos/abertos", methods=["GET"])
def agendamentos_abertos():
    try:
        agendamentos = Agendamento.query.filter(
            Agendamento.status.in_(['Aberto', 'Confirmado'])
        ).order_by(Agendamento.data_hora.asc()).all()
        lista_agendamentos = [formatar_agendamento(ag) for ag in agendamentos]
        return jsonify(lista_agendamentos)
    except Exception as e: return jsonify({"erro": str(e)}), 500

@app.route("/agendamentos/concluidos", methods=["GET"])
def agendamentos_concluidos():
    try:
        agendamentos = Agendamento.query.filter_by(
            status='Concluido'
        ).order_by(Agendamento.data_hora.desc()).all()
        lista_agendamentos = [formatar_agendamento(ag) for ag in agendamentos]
        return jsonify(lista_agendamentos)
    except Exception as e: return jsonify({"erro": str(e)}), 500


if __name__ == "__main__":
    with app.app_context(): db.create_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))