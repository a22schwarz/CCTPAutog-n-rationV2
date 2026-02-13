import sqlite3
import os
import socket
import subprocess
import webbrowser
import time
import shutil

BASE_DIR = os.path.dirname(__file__)

def _resolve_db_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)

DB_PATH = _resolve_db_path(os.environ.get("DB_PATH", "database.db"))

# Localisation de PHP portable
ADMIN_DIR = os.path.join(BASE_DIR, "admin")
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "8000"))
ADMIN_URL = os.environ.get("ADMIN_URL") or f"http://localhost:{ADMIN_PORT}/admin/index.php"

def _find_php_exe():
    env_path = os.environ.get("PHP_EXE")
    if env_path and os.path.exists(env_path):
        return env_path
    local_path = os.path.join(BASE_DIR, "php", "php.exe")
    if os.path.exists(local_path):
        return local_path
    return shutil.which("php")

def _is_port_open(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return column in [row[1] for row in cur.fetchall()]


def add_column_if_missing(cur, table, column, coltype):
    if not column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        print(f"→ Colonne ajoutée : {table}.{column} ({coltype})")



#  TABLE MODULES

def upgrade_modules(cur):
    print("→ Vérification table MODULES")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        );
    """)

    add_column_if_missing(cur, "modules", "marque", "TEXT")
    add_column_if_missing(cur, "modules", "reference", "TEXT")
    add_column_if_missing(cur, "modules", "nom_complet", "TEXT")
    add_column_if_missing(cur, "modules", "puissance_wc", "INTEGER")
    add_column_if_missing(cur, "modules", "type", "TEXT")
    add_column_if_missing(cur, "modules", "cadre", "TEXT")
    add_column_if_missing(cur, "modules", "backsheet", "TEXT")
    add_column_if_missing(cur, "modules", "dimensions", "TEXT")
    add_column_if_missing(cur, "modules", "longueur_cable", "TEXT")
    add_column_if_missing(cur, "modules", "poids", "TEXT")
    add_column_if_missing(cur, "modules", "garantie", "TEXT")
    add_column_if_missing(cur, "modules", "certif_carbone", "TEXT")
    add_column_if_missing(cur, "modules", "etn", "TEXT")


#  TABLE ONDULEURS

def upgrade_onduleurs(cur):
    print("→ Vérification table ONDULEURS")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS onduleurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        );
    """)

    add_column_if_missing(cur, "onduleurs", "nom_complet", "TEXT")
    add_column_if_missing(cur, "onduleurs", "marque", "TEXT")
    add_column_if_missing(cur, "onduleurs", "reference", "TEXT")
    add_column_if_missing(cur, "onduleurs", "puissance_kva", "REAL")
    add_column_if_missing(cur, "onduleurs", "type", "TEXT")
    add_column_if_missing(cur, "onduleurs", "tension_nominale", "TEXT")
    add_column_if_missing(cur, "onduleurs", "type_tension", "TEXT")
    add_column_if_missing(cur, "onduleurs", "raccordement_dc", "TEXT")
    add_column_if_missing(cur, "onduleurs", "para_dc", "TEXT")
    add_column_if_missing(cur, "onduleurs", "para_ac", "TEXT")
    add_column_if_missing(cur, "onduleurs", "afci", "TEXT")
    add_column_if_missing(cur, "onduleurs", "garantie", "TEXT")
    add_column_if_missing(cur, "onduleurs", "extension_garantie", "TEXT")



#  TABLE INTEGRATIONS

def upgrade_integrations(cur):
    print("→ Vérification table INTEGRATIONS")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        );
    """)

    add_column_if_missing(cur, "integrations", "marque", "TEXT")
    add_column_if_missing(cur, "integrations", "ref", "TEXT")
    add_column_if_missing(cur, "integrations", "fixation", "TEXT")
    add_column_if_missing(cur, "integrations", "Compat1", "TEXT")
    add_column_if_missing(cur, "integrations", "Compat2", "TEXT")
    add_column_if_missing(cur, "integrations", "Compat3", "TEXT")
    add_column_if_missing(cur, "integrations", "Compat4", "TEXT")
    add_column_if_missing(cur, "integrations", "Compat5", "TEXT")
    add_column_if_missing(cur, "integrations", "carac1", "TEXT")
    add_column_if_missing(cur, "integrations", "carac2", "TEXT")
    add_column_if_missing(cur, "integrations", "carac3", "TEXT")
    add_column_if_missing(cur, "integrations", "carac4", "TEXT")
    add_column_if_missing(cur, "integrations", "carac5", "TEXT")
    add_column_if_missing(cur, "integrations", "image", "TEXT")
    add_column_if_missing(cur, "integrations", "certification", "TEXT")
    add_column_if_missing(cur, "integrations", "garantie", "TEXT")
    add_column_if_missing(cur, "integrations", "notes", "TEXT")


#  TABLE INTEGRATIONS_CARACTERISTIQUES

def upgrade_integrations_caracteristiques(cur):
    print("→ Vérification table INTEGRATIONS_CARACTERISTIQUES")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS integrations_caracteristiques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            integration_id INTEGER NOT NULL,
            texte TEXT NOT NULL,
            FOREIGN KEY(integration_id) REFERENCES integrations(id)
        );
    """)

#  Lancement de l’interface PHP

def start_admin_interface(open_browser=True):
    print("\n--- Lancement de l'interface admin SQLite ---")

    if _is_port_open("127.0.0.1", ADMIN_PORT):
        print(f" Admin server already running: {ADMIN_URL}")
        if open_browser:
            webbrowser.open(ADMIN_URL)
        return False

    php_exe = _find_php_exe()
    if not php_exe:
        print("ERROR: php.exe not found.")
        return False

    subprocess.Popen(
        [php_exe, "-S", f"localhost:{ADMIN_PORT}"],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True
    )

    time.sleep(1)
    print(f" PHP server started: http://localhost:{ADMIN_PORT}")
    if open_browser:
        webbrowser.open(ADMIN_URL)
    return True


#  Routine INITIALE
def ensure_db():
    print("\n--- Initialisation / Mise a jour de la base SQLite ---")

    new_file = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if new_file:
        print("-> Creation de database.db...")
    else:
        print(" Base existante detectee : mise a niveau...")

    upgrade_modules(cur)
    upgrade_onduleurs(cur)
    upgrade_integrations(cur)
    upgrade_integrations_caracteristiques(cur)

    conn.commit()
    conn.close()

    print(" Base SQLite prete.\n")

def init_db(start_admin=True, open_browser=True):
    ensure_db()
    if start_admin:
        start_admin_interface(open_browser=open_browser)


if __name__ == "__main__":
    init_db()
