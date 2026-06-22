"""Atualiza a senha do SISREG para São José no banco de dados."""
import os
import sqlite3

from cryptography.fernet import Fernet

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "app.db"),
)

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = Fernet.generate_key().decode()
    os.environ["SECRET_KEY"] = SECRET_KEY
    print(f"[AVISO] SECRET_KEY gerada automaticamente: {SECRET_KEY}")
    print("[AVISO] Defina a variável de ambiente SECRET_KEY com este valor para persistência.")
    print()

cipher = Fernet(SECRET_KEY.encode() if isinstance(SECRET_KEY, str) else SECRET_KEY)
nova_senha = "Med@1115"
senha_enc = cipher.encrypt(nova_senha.encode()).decode()

conn = sqlite3.connect(DB_PATH)
try:
    conn.execute("""
        UPDATE credentials
        SET sisreg_pass_encrypted = ?, updated_at = datetime('now')
        WHERE unidade = 'sao_jose'
    """, (senha_enc,))
    conn.commit()
    if conn.total_changes > 0:
        print("OK - Senha do SISREG (São José) atualizada para Med@1115")
    else:
        print("Registro 'sao_jose' não encontrado. Inserindo...")
        conn.execute("""
            INSERT INTO credentials (unidade, sisreg_user, sisreg_pass_encrypted, codigo_ups, otimus_user, otimus_pass_encrypted, updated_at)
            VALUES ('sao_jose', 'MED.LEIDE', ?, '9385835', 'gustavo.weingartner', ?, datetime('now'))
        """, (senha_enc, senha_enc))
        conn.commit()
        print("OK - Registro 'sao_jose' criado com senha SISREG = Med@1115")
        print("ATENÇÃO: A senha do Otimus precisa ser configurada pela interface web.")
finally:
    conn.close()
