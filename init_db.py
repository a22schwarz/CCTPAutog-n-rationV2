import sqlite3
import os
import socket
import subprocess
import webbrowser
import time

DB_PATH = "database.db"

# Localisation de PHP portable
BASE_DIR = os.path.dirname(__file__)
PHP_EXE = os.path.join(BASE_DIR, "php", "php.exe")
ADMIN_DIR = os.path.join(BASE_DIR, "admin")
ADMIN_URL = "http://localhost:8000/admin/index.php"


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

def start_admin_interface():
    print("\n--- Lancement de l’interface admin SQLite ---")

    if not os.path.exists(PHP_EXE):
        print("❌ ERREUR : php.exe introuvable !")
        return

    subprocess.Popen(
        [PHP_EXE, "-S", "localhost:8000"],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True
    )

    time.sleep(1)
    print(" Serveur PHP lancé : http://localhost:8000")
    webbrowser.open(ADMIN_URL)


#  Routine INITIALE
def init_db():
    print("\n--- Initialisation / Mise à jour de la base SQLite ---")

    new_file = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if new_file:
        print("→ Création de database.db…")
    else:
        print(" Base existante détectée : mise à niveau…")

    upgrade_modules(cur)
    upgrade_onduleurs(cur)
    upgrade_integrations(cur)
    upgrade_integrations_caracteristiques(cur)

    conn.commit()
    conn.close()

    print(" Base SQLite prête.\n")
    start_admin_interface()


if __name__ == "__main__":
    init_db()
