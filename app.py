from flask import Flask, render_template, request, send_file, url_for, redirect  # On importe Flask : (routes / pages / formulaires)
from docxtpl import DocxTemplate, RichText  # génération Word et texte conditionnellement surligné
from datetime import datetime, timezone  # pour la date
import pandas as pd  # poru lire le CSV
import sqlite3
import re, \
    json  # re pour simplifier la recherche dans le CSV et json  pour gérer le format json (utile pour les tableaux avec des valeurs différentes selon la zone)
from io import BytesIO  # le tampon mémoire qui sert à générer le .docx sans avoir à créer un fichier dans le dur
import os
import uuid
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlparse
from urllib.request import urlopen

import requests
from werkzeug.utils import secure_filename
from werkzeug.datastructures import MultiDict

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.environ.get("DB_PATH", "database.db")
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, DB_PATH)
os.environ["DB_PATH"] = DB_PATH

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "cctp-images")
PROJECT_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff'}
PROJECT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
# Le lancement direct ``python app.py`` est le mode local et utilise SQLite,
# même si PyCharm conserve des variables Supabase dans sa configuration.
# En production (application importée par Gunicorn), les identifiants activent
# Supabase. CCTP_STORAGE=local|supabase permet de forcer explicitement le choix.
STORAGE_BACKEND = os.environ.get("CCTP_STORAGE", "").strip().lower()
if STORAGE_BACKEND not in {"", "local", "sqlite", "supabase"}:
    raise RuntimeError("CCTP_STORAGE doit valoir 'local', 'sqlite' ou 'supabase'.")
if STORAGE_BACKEND == "supabase" and not (SUPABASE_URL and SUPABASE_KEY):
    raise RuntimeError(
        "CCTP_STORAGE=supabase exige SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY."
    )
USE_SUPABASE = (
    STORAGE_BACKEND == "supabase"
    or (
        STORAGE_BACKEND == ""
        and __name__ != "__main__"
        and bool(SUPABASE_URL and SUPABASE_KEY)
    )
)

ADMIN_URL = os.environ.get("ADMIN_URL", "/admin")
INVERTER_FORM_FIELDS = {
    'marque': 'Marque',
    'ref': 'Référence',
    'puissance': 'Puissance kVA',
    'type': 'Type',
    'tension': 'Tension nominale',
    'type-tension': 'Type tension',
    'raccord': 'Raccordement DC',
    'para-dc': 'Parafoudre DC',
    'para-ac': 'Parafoudre AC',
    'afci': 'AFCI',
    'garantie': 'Garantie',
    'ext-garantie': 'Extension garantie',
}

# Supabase uniquement: pas d'initialisation SQLite.

def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

def _sb_select(table, filters=None, order=None):
    if not USE_SUPABASE:
        return []
    params = {}
    if filters:
        params.update(filters)
    if order:
        params["order"] = order
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.get(url, headers=_sb_headers(), params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _sb_insert(table, data):
    if not USE_SUPABASE:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _sb_headers()
    headers["Prefer"] = "return=representation"
    resp = requests.post(url, headers=headers, json=data, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _sb_update(table, filters, data):
    if not USE_SUPABASE:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _sb_headers()
    headers["Prefer"] = "return=representation"
    resp = requests.patch(url, headers=headers, params=filters, json=data, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _sb_delete(table, filters):
    if not USE_SUPABASE:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _sb_headers()
    headers["Prefer"] = "return=representation"
    resp = requests.delete(url, headers=headers, params=filters, timeout=10)
    resp.raise_for_status()
    if not resp.text:
        return []
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}

def _sb_upload_image(file_storage, folder):
    if not USE_SUPABASE:
        return ""
    if not file_storage or not file_storage.filename:
        return ""
    filename = secure_filename(file_storage.filename)
    if not filename:
        return ""
    ext = os.path.splitext(filename)[1].lower()
    name = f"{uuid.uuid4().hex}{ext}"
    path = f"{folder}/{name}"
    encoded_path = quote(path, safe="/")
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{encoded_path}"
    headers = _sb_headers()
    headers["Content-Type"] = file_storage.mimetype or "application/octet-stream"
    headers["x-upsert"] = "true"
    resp = requests.post(url, headers=headers, data=file_storage.read(), timeout=15)
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{encoded_path}"

def _local_upload_image(file_storage, folder):
    if not file_storage or not file_storage.filename:
        return ""
    filename = secure_filename(file_storage.filename)
    if not filename:
        return ""
    ext = os.path.splitext(filename)[1].lower()
    name = f"{uuid.uuid4().hex}{ext}"
    upload_dir = os.path.join(BASE_DIR, "static", folder)
    os.makedirs(upload_dir, exist_ok=True)
    dst = os.path.join(upload_dir, name)
    file_storage.save(dst)
    return name

def save_image(file_storage, folder):
    return _sb_upload_image(file_storage, folder) if USE_SUPABASE else _local_upload_image(file_storage, folder)


def save_project_image(file_storage):
    """Enregistre une image de projet et renvoie une référence persistante."""
    filename = secure_filename(file_storage.filename) if file_storage else ""
    if os.path.splitext(filename)[1].lower() not in PROJECT_IMAGE_EXTENSIONS:
        return ""
    try:
        file_storage.stream.seek(0)
        image_data = file_storage.stream.read(PROJECT_IMAGE_MAX_BYTES + 1)
        file_storage.stream.seek(0)
        if not image_data or len(image_data) > PROJECT_IMAGE_MAX_BYTES:
            return ""
        from docx.image.image import Image
        Image.from_file(BytesIO(image_data))
    except Exception:
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
        return ""
    value = save_image(file_storage, "project-images")
    if not value or value.startswith(("http://", "https://")):
        return value
    return f"project-images/{value}"


def normalize_project_image_ref(value):
    """N'accepte que les références générées dans le dossier du projet."""
    value = str(value or '').strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        if not USE_SUPABASE:
            return ""
        base = urlparse(SUPABASE_URL)
        prefix = f"/storage/v1/object/public/{SUPABASE_BUCKET}/project-images/"
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            return ""
        relative_name = unquote(parsed.path)
        if not relative_name.startswith(prefix):
            return ""
        filename = relative_name[len(prefix):]
        return value if _valid_project_image_name(filename) else ""
    prefix = "project-images/"
    if not value.startswith(prefix):
        return ""
    filename = value[len(prefix):]
    return value if _valid_project_image_name(filename) else ""


def _valid_project_image_name(filename):
    stem, extension = os.path.splitext(filename)
    return bool(re.fullmatch(r'[0-9a-f]{32}', stem)) and extension.lower() in PROJECT_IMAGE_EXTENSIONS


def project_image_url(value):
    value = normalize_project_image_ref(value)
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return url_for("static", filename=value)


def delete_project_image(value):
    """Supprime une image générée par l'application, sans accepter d'autre chemin."""
    value = normalize_project_image_ref(value)
    if not value:
        return
    filename = os.path.basename(unquote(urlparse(value).path))
    if USE_SUPABASE:
        object_path = quote(f"project-images/{filename}", safe="/")
        url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_path}"
        response = requests.delete(url, headers=_sb_headers(), timeout=10)
        response.raise_for_status()
        return
    path = os.path.join(BASE_DIR, "static", "project-images", filename)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def project_photo_refs(project):
    data = (project or {}).get('form_data', {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    refs = set()
    for photo_key in ('structure_model', 'structure_location', 'structure_reinforcement'):
        values = (data or {}).get(f'{photo_key}_photo_saved', [])
        for value in values if isinstance(values, list) else [values]:
            ref = normalize_project_image_ref(value)
            if ref:
                refs.add(ref)
    return refs


app = Flask(__name__)  # création de l'app Flask
app.config.update(TEMPLATE='TemplateCCTP.updated2.docx', CSV_SEP=';',
                  MAX_ZONES=4)  # on configure le nom du template word à remplir, ce qui sépare les infos du csv (en l'occurence un ;) et le nombre de zones max (car 4 zones possibles en VT)

@app.context_processor
def inject_admin_url():
    return {"admin_url": ADMIN_URL, "project_image_url": project_image_url}

@app.template_filter("img_url")
def img_url(value, folder):
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return url_for("static", filename=f"{folder}/{value}")

# Il se trouve que les infos dans le csv AC et VT ont des noms différents donc on crée un dicitionnaire d'alias pour les données qu'on va chercher l'ensemble des dénominations trouvables dans les 2 types de CSV.
FIELD_ALIASES = {
    'nom_projet': ['nom projet', 'nom du projet'],
    'type_installation': ['nature de la centrale', 'type installation', 'type de centrale'],
    'maitre_ouvrage': ['nom client', 'maître d’ouvrage', 'maitre d’ouvrage', 'client'],
    'ville': ['localisation', 'ville'],
    'deposecandelabres': ['Nbre candélabre à déposer'],
    'abattagearbres': ['Nbre d\'arbres à abattre'],
    'adresse': ['adresse', 'adresse du site'],
    'puissance_kwc': ['puissance de la centrale', 'puissance zone totale', 'puissance install', 'puissande l’install',
                      'puissande l\'install', 'puissance installée'],
    'valorisation': ["valorisation de l'énergie produite", 'mode de valorisation', 'valorisation'],
}

# Types de zones ombrières qu’on sait reconnaître rapidement qui sert en particulier dans le 9.3.4	Fourniture et pose des coffrets AC avec les balises if has_ombrieres à différencier de des balises if Ombrieres qui sont le fruit d'un choix opéré à la fin du formulaire (lors do cochage de la section Présence d'ombrières et présence de hangars)
OMB_TYPES = ["OMB VL DOUBLE", "OMB VL SIMPLE", "OMB VL PORTIQUE", "OMB PL", "OMB BOIS VL SIMPLE", "OMB BOIS VL DOUBLE"]
# Pareil
TOITURE_TYPES = ["TT LESTE SUD", "TT LESTE E/W", "TT SOUDE", "TT BAC ACIER"]

INSTALLATION_MAP = { #création d'un mapping pour la description générale
    "Toiture": "en toiture",
    "Ombrière": "en ombrières",
    "Centrale au sol": "au sol",
    "Ombrière + Sol": "en ombrières et au sol",
    "Ombrière + Toiture": "en ombrières et en toiture",
    "Toiture + Sol": "au sol et en toiture",
    "TT + SOL + OMB": "en toiture, en ombrières et au sol"
}

def query(sql, params=()): #Exécute une requête SQL et renvoie le résultat sous forme de liste de dictionnaires.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def execute_sql(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def _sqlite_insert(table, data):
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    return execute_sql(sql, list(data.values()))

def _sqlite_update(table, data, row_id):
    set_clause = ", ".join([f"{k}=?" for k in data.keys()])
    sql = f"UPDATE {table} SET {set_clause} WHERE id=?"
    execute_sql(sql, list(data.values()) + [row_id])

def _sqlite_delete(table, row_id):
    execute_sql(f"DELETE FROM {table} WHERE id=?", (row_id,))


def _ensure_local_projects_table():
    """Met à niveau automatiquement une ancienne base SQLite au démarrage."""
    if USE_SUPABASE:
        return
    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'Projet sans nom',
            form_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


_ensure_local_projects_table()

def _admin_list(table):
    if USE_SUPABASE:
        return _sb_select(table, order="id.desc")
    return query(f"SELECT * FROM {table} ORDER BY id DESC")

def _admin_get(table, row_id):
    if USE_SUPABASE:
        rows = _sb_select(table, filters={"id": f"eq.{row_id}"})
        return rows[0] if rows else None
    rows = query(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    return rows[0] if rows else None


def load_module_df():
    rows = _sb_select("modules", order="id.desc") if USE_SUPABASE else query("SELECT * FROM modules")
    if not rows:
        return pd.DataFrame(columns=[
            "Marque PV", "Ref PV", "Nom complet", "Puissance Wc", "Type",
            "Cadre", "Backsheet", "Dimensions mm", "Longueur câble mm",
            "Poids kg", "Garantie", "Certif carbone", "ETN"
        ])
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "marque": "Marque PV",
        "reference": "Ref PV",
        "nom_complet": "Nom complet",
        "puissance_wc": "Puissance Wc",
        "type": "Type",
        "cadre": "Cadre",
        "backsheet": "Backsheet",
        "dimensions": "Dimensions mm",
        "longueur_cable": "Longueur câble mm",
        "poids": "Poids kg",
        "garantie": "Garantie",
        "certif_carbone": "Certif carbone",
        "etn": "ETN",
    })
    return df.fillna('')


def load_inverter_df():
    rows = _sb_select("onduleurs", order="id.desc") if USE_SUPABASE else query("SELECT * FROM onduleurs")
    if not rows:
        return pd.DataFrame(columns=[
            "Nom complet", "Marque", "Référence", "Puissance kVA",
            "Type", "Tension nominale", "Type tension",
            "Raccordement DC", "Parafoudre DC", "Parafoudre AC",
            "AFCI", "Garantie", "Extension garantie"
        ])
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "nom_complet": "Nom complet",
        "marque": "Marque",
        "reference": "Référence",
        "puissance_kva": "Puissance kVA",
        "type": "Type",
        "tension_nominale": "Tension nominale",
        "type_tension": "Type tension",
        "raccordement_dc": "Raccordement DC",
        "para_dc": "Parafoudre DC",
        "para_ac": "Parafoudre AC",
        "afci": "AFCI",
        "garantie": "Garantie",
        "extension_garantie": "Extension garantie",
    })
    return df.fillna('')


def load_si_df():
    rows = _sb_select("integrations", order="id.desc") if USE_SUPABASE else query("SELECT * FROM integrations")
    if not rows:
        return pd.DataFrame(columns=[
            "Marque", "Référence", "Fixation", "Compatibilité 1", "Compatibilité 2", "Compatibilité 3", "Compatibilité 4", "Compatibilité 5",
            "Caractéristique 1", "Caractéristique 2", "Caractéristique 3", "Caractéristique 4", "Caractéristique 5", "Image",
            "Certification", "Garantie"
        ])

    df = pd.DataFrame(rows)
    def _col(name):
        if name in df.columns:
            return name
        lower = name.lower()
        return lower if lower in df.columns else name

    df = df.rename(columns={
        _col("marque"): "Marque",
        _col("ref"): "Référence",
        _col("fixation"): "Fixation",
        _col("Compat1"): "Compatibilité 1",
        _col("Compat2"): "Compatibilité 2",
        _col("Compat3"): "Compatibilité 3",
        _col("Compat4"): "Compatibilité 4",
        _col("Compat5"): "Compatibilité 5",
        _col("carac1"): "Caractéristique 1",
        _col("carac2"): "Caractéristique 2",
        _col("carac3"): "Caractéristique 3",
        _col("carac4"): "Caractéristique 4",
        _col("carac5"): "Caractéristique 5",
        _col("image"): "Image",
        _col("certification"): "Certification",
        _col("garantie"): "Garantie",
    })

    return df.fillna('')

def load_si_image(img_name):
    import os

    if not img_name or not img_name.strip():
        return None

    img_name = img_name.strip()

    # Si l'extension manque, on teste les extensions usuelles
    possible_names = [
        img_name,
        img_name + ".png",
        img_name + ".jpg",
        img_name + ".jpeg",
        img_name.lower(),
        img_name.lower() + ".png",
        img_name.lower() + ".jpg",
        img_name.lower() + ".jpeg",
    ]

    base_dir = os.path.join("static", "si")

    for name in possible_names:
        path = os.path.join(base_dir, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()

    return None



MODULE_DB = load_module_df()
INVERTER_DB = load_inverter_df()
SI_DB = load_si_df()

PV_MODULES = set(MODULE_DB["Nom complet"].dropna().unique().tolist())
INVERTERS = set(INVERTER_DB["Nom complet"].dropna().unique().tolist())
SI_OPTIONS = set((SI_DB["Marque"] + " - " + SI_DB["Référence"]).dropna().unique().tolist())


# Cette fonction sert a lire un fichier CSV venant soit d’un upload soit d’un texte collé.Le but c’est de toujours recuperer les données proprement: en forcant un séparateur précis on évite que pandas transforme les cases vides en NaN , on garde des chaines vides "" au lieu d'écrire "Nan"
def parse_csv(src, from_text=False):
    opts = dict(sep=app.config['CSV_SEP'], header=None, dtype=str, keep_default_na=False,
                engine='python')  # prepare toutes les options pandas pour lire un CSV avec ; en separateur et tout en texte
    return pd.read_csv(BytesIO(src.encode()), **opts) if from_text else pd.read_csv(src,
                                                                                    **opts)  # lit le csv depuis un texte (transformé en fichier en memoire) si from_text=True sinon lit direct le fichier uploadé


# Cette fonction sert a chercher la premiere valeur qui se trouve juste apres un mot cle donné (alias) dans le CSV. Elle verifie chaque ligne et chaque colonne, compare en ignorant les majuscules/minuscules et les espaces, et renvoie la valeur de la cellule suivante si ca correspond.
def find_first(df, aliases):
    if df.empty: return ''  # si le tableau est vide on renvoie vide
    if isinstance(aliases, str): aliases = [aliases]  # si un seul alias est donné on le met dans une liste
    aliases = [a.strip().casefold() for a in aliases if
               a and a.strip()]  # on nettoie chaque alias et on passe en minuscule
    if not aliases: return ''  # si la liste est vide on renvoie vide
    for row in df.itertuples(index=False):  # on parcourt chaque ligne
        vals = [str(x).strip() for x in row]  # on nettoie chaque valeur de la ligne
        for i in range(
                len(vals) - 1):  # on regarde chaque cellule sauf la derniere (pas la denrière car on cherche le mot-clé qui se trouve être à gauche, donc si on cherche la dernnière on trouvera jamais de valeur)
            if any(alias in vals[i].casefold() for alias in aliases):  # si un alias est trouvé dans la cellule
                return vals[i + 1].strip()  # on renvoie la cellule d'apres
    return ''  # si rien trouvé on renvoie une chaine vide


# Cette fonction sert a recuperer une valeur dans le CSV en passant par le systeme d'alias défini en haut du fichier. On donne un nom officiel (canonical_key) et ca va chercher toutes les variantes possibles dans FIELD_ALIASES.
def find_value(df, canonical_key):
    return find_first(df, FIELD_ALIASES.get(canonical_key, [canonical_key]))


def get_module_from_db(marque, ref):
    marque, ref = (marque or '').strip().upper(), (ref or '').strip().upper()
    for _, row in MODULE_DB.iterrows():
        if (row.get("Marque PV", "").strip().upper() == marque and
                row.get("Ref PV", "").strip().upper() == ref):
            return row.to_dict()
    return None


def get_inverter_from_db(nom):
    nom = (nom or '').strip().upper()
    for _, row in INVERTER_DB.iterrows():
        if row.get("Nom complet", "").strip().upper() == nom:
            return row.to_dict()
    return None


def get_si_from_db(marque, ref):
    marque = (marque or "").strip().upper()
    ref = (ref or "").strip().upper()

    def _normalize(row_dict):
        return {
            "Marque": row_dict.get("marque") or row_dict.get("Marque") or "",
            "Référence": row_dict.get("ref") or row_dict.get("Référence") or "",
            "Fixation": row_dict.get("fixation") or row_dict.get("Fixation") or "",
            "Compat1": row_dict.get("Compat1") or row_dict.get("compat1") or "",
            "Compat2": row_dict.get("Compat2") or row_dict.get("compat2") or "",
            "Compat3": row_dict.get("Compat3") or row_dict.get("compat3") or "",
            "Compat4": row_dict.get("Compat4") or row_dict.get("compat4") or "",
            "Compat5": row_dict.get("Compat5") or row_dict.get("compat5") or "",
            "carac1": row_dict.get("carac1") or "",
            "carac2": row_dict.get("carac2") or "",
            "carac3": row_dict.get("carac3") or "",
            "carac4": row_dict.get("carac4") or "",
            "carac5": row_dict.get("carac5") or "",
            "Certification": row_dict.get("certification") or row_dict.get("Certification") or "",
            "Garantie": row_dict.get("garantie") or row_dict.get("Garantie") or "",
            "Image": row_dict.get("image") or row_dict.get("Image") or "",
            "principales_caracteristiques": row_dict.get("principales_caracteristiques") or "",
        }

    if USE_SUPABASE:
        rows = _sb_select("integrations")
        row = next(
            (r for r in rows
             if (r.get("marque") or "").strip().upper() == marque
             and (r.get("ref") or "").strip().upper() == ref),
            None,
        )
        if not row:
            return None
        data = _normalize(row)
        carac_rows = _sb_select(
            "integrations_caracteristiques",
            filters={"integration_id": f"eq.{row.get('id')}"},
        )
        caracs = [r.get("texte", "") for r in carac_rows if r.get("texte")]
        data["Caractéristiques"] = "\n".join(caracs) if caracs else data.get("principales_caracteristiques", "")
        return data

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1) Récupération de la ligne principale
    cur.execute("""
        SELECT * FROM integrations
        WHERE UPPER(marque) = ? AND UPPER(ref) = ?
    """, (marque, ref))
    row = cur.fetchone()

    if not row:
        conn.close()
        return None

    data = _normalize(dict(row))

    # 2) Récupération des caractéristiques détaillées
    cur.execute("""
        SELECT texte FROM integrations_caracteristiques
        WHERE integration_id = ?
    """, (row["id"],))

    caracs = [r["texte"] for r in cur.fetchall()]

    # 3) Fusion
    if caracs:
        data["Caractéristiques"] = "\n".join(caracs)
    else:
        # fallback : anciennes données éventuelles
        data["Caractéristiques"] = data.get("principales_caracteristiques", "")

    conn.close()
    return data


def normalize_dict(d):
    """Convertit un dict en version normalisée pour comparaison (triée, sans None, et cast en string),
       en ignorant les objets InlineImage qui ne sont PAS sérialisables."""
    if not isinstance(d, dict):
        return {}

    norm = {}
    for k, v in d.items():
        # IGNORE les InlineImage (NE SURTOUT PAS appeler str() dessus)
        from docxtpl.inline_image import InlineImage
        if isinstance(v, InlineImage):
            continue

        if v is None:
            val = ""
        else:
            val = str(v).strip().upper()

        norm[k] = val

    return norm



# Recupere toutes les infos d'une zone precise dans le CSV et les renvoie sous forme de dictionnaire
def extract_zone(df, n):
    typ = find_first(df, [f"typologie zone {n}"])  # cherche le type de la zone n (1,2,3,4)
    if not typ: return None  # si pasde type trouvé, la zone n'existe pas
    return {'name': f'Zone {n}', 'type': typ or '', 'puissance': find_first(df, [f"puissance zone {n}"]) or '',
            'modules': find_first(df, [f"nombre panneaux zone {n}",
                                       f"nb panneaux zone {n}"]) or ''}  # type, puissance, panneau trouvé


# Detecte automatiquement toutes les zones presentes dans le CSV et retourne leurs infos
def detect_zones(df):
    if df.empty or df.shape[1] < 2: return []  # si CSV vide ou moins de 2 colonnes, on renvoie une liste vide
    nums = sorted({int(m.group(1)) for cell in df.iloc[:, 1] if (m := re.search(r'zone\s*(\d+)', str(cell),
                                                                                re.I))})  # recupere tous les numeros de zones trouves dans la 2e colonne
    return [z for z in (extract_zone(df, n) for n in nums) if z][:app.config[
        'MAX_ZONES']]  # appelle extract_zone pour chaque numero et garde seulement les zones valides jusqu'a la limite MAX_ZONES de 4 zones

# Sélectionner 400/800V pour le paragraphe 9.3.2.	Fourniture et pose TBGT avec la tension demandée
def get_voltage(bt_mt):
    return "400V" if bt_mt == "BT" else ("800V" if bt_mt == "MT" else "Non défini")


# verifie si une case a cocher du formulaire a ete cochee (renvoie True si oui sinon False)
def to_bool(form, key):
    return form.get(key) == 'on'  # dans les formulaires HTML une checkbox renvoie "on" si elle est cochee


def review_text(value, missing_label="Non défini", **formatting):
    """Texte Word normal si renseigné, jaune lorsqu'une vérification est requise."""
    text = str(value or '').strip()
    formatting.setdefault('font', 'Source Sans Pro')
    formatting.setdefault('size', 20)  # taille attendue par docxtpl en demi-points
    force_regular = 'bold' not in formatting
    rich_text = (
        RichText(text, **formatting)
        if text else RichText(missing_label, highlight='FFFF00', **formatting)
    )
    if force_regular:
        # docxtpl n'écrit aucun attribut lorsque bold=False : Word hérite alors
        # parfois du gras du paragraphe contenant la balise. On neutralise
        # explicitement cet héritage dans chaque run généré.
        rich_text.xml = rich_text.xml.replace(
            '<w:rPr>', '<w:rPr><w:b w:val="0"/><w:bCs w:val="0"/>'
        )
    return rich_text


MISSING_SENTINEL = "[[CCTP_MISSING_VALUE]]"


class MissingTemplateValue(str):
    """Valeur visible dans Word mais toujours fausse dans les conditions Jinja."""
    def __new__(cls):
        return super().__new__(cls, MISSING_SENTINEL)

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __getattr__(self, _name):
        return self

    def __getitem__(self, _key):
        return self


def mark_empty_template_values(value):
    """Prépare une copie du contexte où les textes vides restent repérables."""
    if value is None or (isinstance(value, str) and value == ""):
        return MissingTemplateValue()
    if isinstance(value, dict):
        return {key: mark_empty_template_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mark_empty_template_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mark_empty_template_values(item) for item in value)
    return value


def highlight_missing_values(docx_buffer, highlight_dc_section=False):
    """Remplace et surligne toutes les informations à vérifier dans le Word."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document(docx_buffer)
    missing_labels = (MISSING_SENTINEL, "Non défini", "Non définie", "inconnu", "inconnue")

    def shade_run(run):
        properties = run._r.get_or_add_rPr()
        for existing in properties.findall(qn('w:shd')):
            properties.remove(existing)
        shading = OxmlElement('w:shd')
        shading.set(qn('w:val'), 'clear')
        shading.set(qn('w:color'), 'auto')
        shading.set(qn('w:fill'), 'FFFF00')
        properties.append(shading)

    def force_regular_run(run):
        properties = run._r.get_or_add_rPr()
        for tag in ('w:b', 'w:bCs', 'w:i', 'w:iCs'):
            element = properties.find(qn(tag))
            if element is None:
                element = OxmlElement(tag)
                properties.append(element)
            element.set(qn('w:val'), '0')
        fonts = properties.find(qn('w:rFonts'))
        if fonts is None:
            fonts = OxmlElement('w:rFonts')
            properties.append(fonts)
        for attribute in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
            fonts.set(qn(attribute), 'Source Sans Pro')
        for tag in ('w:sz', 'w:szCs'):
            size = properties.find(qn(tag))
            if size is None:
                size = OxmlElement(tag)
                properties.append(size)
            size.set(qn('w:val'), '18')

    def process_paragraph(paragraph):
        technical_location = any(marker in paragraph.text.casefold() for marker in (
            'onduleurs de la zone',
            'onduleurs seront implantés',
            'onduleurs seront installés',
            'coffrets dc de la zone',
            'coffrets dc seront implantés',
            'coffrets dc seront installés',
        ))
        for run in paragraph.runs:
            original = run.text
            if not original:
                continue
            text = original.replace(MISSING_SENTINEL, "À compléter")
            should_highlight = text != original or any(
                label.casefold() in text.casefold() for label in missing_labels[1:]
            )
            if should_highlight:
                run.text = text
                shade_run(run)
            if technical_location:
                force_regular_run(run)

    def process_table(table):
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    process_paragraph(paragraph)
                for nested_table in cell.tables:
                    process_table(nested_table)

    for paragraph in document.paragraphs:
        process_paragraph(paragraph)
    if highlight_dc_section:
        inside_dc_section = False
        for paragraph in document.paragraphs:
            if paragraph.text.strip() == "Fourniture et pose des coffrets DC":
                inside_dc_section = True
            elif inside_dc_section and paragraph.text.strip() == "Mise à la terre":
                break
            if inside_dc_section:
                for run in paragraph.runs:
                    if run.text:
                        shade_run(run)
                        force_regular_run(run)
    for table in document.tables:
        process_table(table)
    for section in document.sections:
        for part in (section.header, section.footer):
            for paragraph in part.paragraphs:
                process_paragraph(paragraph)
            for table in part.tables:
                process_table(table)

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output


# convertit une valeur texte en nombre flottant (float) en gerant les virgules et les valeurs vides
def _to_float(s):
    if isinstance(s, (int, float)):
        return float(s)
    try:
        s = str(s or '').replace(',',
                              '.').strip()  # si s est None on le remplace par '', on change la virgule en point et on enleve les espaces
        return float(
            s) if s and s != '-' else 0.0  # si c'est pas vide et pas juste '-' on le transforme en float sinon on renvoie 0.0
    except ValueError:
        return 0.0  # si la conversion echoue on renvoie 0.0


# Pareil dns l'autre sens, on convertit un nombre décimal en entier
def _to_int(s):
    if isinstance(s, (int, float)):
        return int(s)
    try:
        s = str(s or '').strip()
        return int(s) if s and s != '-' else 0
    except ValueError:
        return 0


# calcule la somme totale des puissances et du nombre de modules sur toutes les zones
def compute_totals(zones):
    return (
        sum(_to_float(z.get('puissance')) for z in zones),  # additionne toutes les puissances converties en float
        sum(_to_int(z.get('modules')) for z in zones)  # additionne tous les modules convertis en int
    )


# lit un champ du formulaire qui contient un tableau en JSON et le converti en liste python (sert pour les tableaux du lot charpente et recap), sinon renvoie liste vide
def load_table_json(form, name):
    try:
        return json.loads(form.get(name, '[]'))  # recupere la valeur, si vide prend '[]', puis parse en JSON
    except json.JSONDecodeError:
        return []  # si le JSON est invalide on renvoie une liste vide


# nettoie les lignes des tabkeaux Présence ombrières et Présence  tableau en enlevant les espaces et en s'assurant que toutes les cles existent
def sanitize_rows(rows):
    for r in rows:  # pour chaque ligne du tableau
        for k in ('type', 'desc', 'modules', 'orient', 'incli', 'hbp'):  # pour chaque champ attendu
            r[k] = (r.get(k) or '').strip()  # recupere la valeur, met '' si None, enleve les espaces
    return rows  # renvoie le tableau nettoyé


def _project_form_values(data):
    """Recrée un MultiDict à partir des données d'un brouillon sauvegardé."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    pairs = []
    for key, values in (data or {}).items():
        for value in values if isinstance(values, list) else [values]:
            pairs.append((key, str(value)))
    return MultiDict(pairs)


def _list_projects():
    projects = (
        _sb_select("projects", order="updated_at.desc")
        if USE_SUPABASE
        else query("SELECT * FROM projects")
    )

    def sort_key(project):
        data = project.get('form_data', {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        filename = str((data or {}).get('csv_filename', ''))
        match = re.search(r'(?<!\d)(\d{4})(?!\d)', filename)
        project['project_number'] = match.group(1) if match else ''
        name = (project.get('name') or '').casefold()
        # D'abord les CSV portant un numéro projet à quatre chiffres, puis les
        # autres brouillons par ordre alphabétique.
        return (0, int(match.group(1)), name) if match else (1, 0, name)

    # sort_key ajoute aussi project_number, utilisé pour l'affichage dans le menu.
    return sorted(projects, key=sort_key)


def _get_project(project_id):
    rows = (
        _sb_select("projects", filters={"id": f"eq.{project_id}"})
        if USE_SUPABASE
        else query("SELECT * FROM projects WHERE id = ?", (project_id,))
    )
    return rows[0] if rows else None


@app.route(
    '/')  # definit la route racine qui affiche la page d'accueil pour envoyer un CSV,charge et renvoie la page HTML upload.html au navigateur
def upload():
    return render_template(
        'upload.html',
        projects=_list_projects(),
        admin_url=ADMIN_URL,
    )


# Après l’envoi du CSV ; elle lit le fichier si présent, prépare toutes les données et affiche le grand formulaire par zones
@app.route('/form', methods=['POST'])
def form(saved_project=None):

    global PV_MODULES, INVERTERS, MODULE_DB, INVERTER_DB, SI_DB

    # Recharge TOUJOURS la base à chaque appel
    MODULE_DB = load_module_df()
    INVERTER_DB = load_inverter_df()
    SI_DB = load_si_df()

    PV_MODULES = set(MODULE_DB["Nom complet"].dropna().unique().tolist())
    INVERTERS = set(INVERTER_DB["Nom complet"].dropna().unique().tolist())
    SI_OPTIONS = set((SI_DB["Marque"] + " - " + SI_DB["Référence"]).dropna().unique().tolist())

    form_values = _project_form_values(saved_project.get('form_data')) if saved_project else request.form
    if saved_project:
        csv_text = form_values.get('csv_text', '')
        df = parse_csv(csv_text, from_text=True) if csv_text.strip() else pd.DataFrame()
        try:
            zones = json.loads(form_values.get('zones_json', '[]'))
        except json.JSONDecodeError:
            zones = []
        zones = zones or detect_zones(df)
    else:
        f = request.files.get('csv_file')
        df = parse_csv(f) if f and f.filename.lower().endswith('.csv') else pd.DataFrame()
        zones = detect_zones(df)
    csv_data = {k: find_value(df, k) for k in
                FIELD_ALIASES}  # Extrait les informations “projet” grace aux alias (ex. nom_projet, ville, adresse, puissance_kwc) qui correspondent aux balises word({{ nom_projet }}, {{ ville }}, etc.)
    marque_pv = find_first(df, ['marque pv']) or ''
    ref_pv = find_first(df, ['ref pv']) or ''
    module_info = get_module_from_db(marque_pv, ref_pv)
    ti_val = csv_data.get('type_installation', '') or ''  # valeur brute du CSV pour la nature de centrale
    ti_val = ti_val.strip()
    implantation_val = INSTALLATION_MAP.get(ti_val, ti_val if ti_val else "")
    nb_cand = _to_int(csv_data.get('deposecandelabres', '0'))
    nb_arb = _to_int(csv_data.get('abattagearbres', '0'))

    csv_data['nb_deposecandelabres'] = nb_cand
    csv_data['nb_abattagearbres'] = nb_arb
    csv_data['deposecandelabres'] = '1' if nb_cand > 0 else '0'
    csv_data['abattagearbres'] = '1' if nb_arb > 0 else '0'
    ctx = {
        # Construit le contexte envoyé au template formulaire.html ; il préremplit l’interface et transporte les données jusqu’à generate pour produire le Word
        'csv_text': ("\n".join(df.astype(str).agg(';'.join, axis=1))) if not df.empty else '',
        'csv_filename': form_values.get('csv_filename', '') if saved_project else (f.filename if f else ''),
        # Version texte du CSV (séparateur ;)
        'zones': zones,
        # Liste des zones détectées plus haut; utilisée pour afficher une colonne par zone dans la table de paramètres
        'admin_url': ADMIN_URL,
        # URL de l'admin
        'zones_json': json.dumps(zones),
        # Sérialisation JSON ; pour que generate relise exactement les mêmes zones sans devoir relire le CSV
        'panel_options': list(PV_MODULES),
        # panneaux proposés dans les listes déroulantes ; le choix final remontera dans z['module'] et sera réutilisé dans le word
        'inverter_options': list(INVERTERS),  # Pareil
        'si_options': list(SI_OPTIONS),
        # Pour chaque zoneon propose la liste de SI correspondant grâce à la liste établie dans INTEGRATIONS
        'latitude': form_values.get('latitude', ''),  # on demande de remplir la latitude
        'longitude': form_values.get('longitude', ''),  # Pareil
        'AC_VT': form_values.get('AC_VT', 'Autoconsommation'),
        # Choix “Autoconsommation / Vente Totale”  et repris generate pour alimenter les balises word
        'bt_mt': form_values.get('bt_mt', 'BT'),
        # Choix BT/MT; repris par generate pour labalise VOTRE_TENSION dans le document word et les balises if bt_mt == "MT" dans 9.3.2.	Fourniture et pose TBGT
        'ZONES': zones,  # Permet au word d'utiliser zones en majuscules
        'NB_ZONES': len(zones),
        # Nombre total de zones utile dans le word pour afficher un bloc seulement s’il y a au moins une zone
        'default_module': module_info.get('Nom complet', '') if module_info else '',
        'module_details': module_info or {},

        # ajoute dans le contexte toutes les infos projet extraites du CSV via les alias (ex. nom_projet, ville, adresse, puissance_kwc) ; chaque clé correspond directement à une balise du modèle Word pour être remplacée automatiquement
        **csv_data,

        'implantation_globale': form_values.get('implantation_globale', implantation_val),
        'type_installation_csv': ti_val,  # stocke la valeur brute du CSV (pour usage ultérieur)
    }

    module_details = []
    inverter_details = []
    si_details = []

    for z in zones:
        # MODULES (nom + ref disponibles dans le CSV)
        mod_name = find_first(df, [f"panneau zone {z['name'][-1]}", f"module zone {z['name'][-1]}"])
        mod_ref = find_first(df, [f"ref panneau zone {z['name'][-1]}", f"ref module zone {z['name'][-1]}"])
        mod = get_module_from_db(mod_name, mod_ref)
        module_details.append(mod or {})

        # ONDULEURS (uniquement nom dans le CSV)
        inv_name = find_first(df, [f"onduleur zone {z['name'][-1]}", f"inverter zone {z['name'][-1]}"])
        inv = get_inverter_from_db(inv_name)
        inverter_details.append(inv or {})

        # SYSTÈMES D’INTÉGRATION
        sys_name_raw = find_first(df, [f"si zone {z['name'][-1]}", f"sys zone {z['name'][-1]}"])
        sys_ref_raw = find_first(df, [f"ref si zone {z['name'][-1]}", f"ref sys zone {z['name'][-1]}"])

        # Décomposition si format "Marque - Référence"
        if sys_name_raw and " - " in sys_name_raw:
            marque, ref = sys_name_raw.split(" - ", 1)
            sys_name = marque.strip()
            sys_ref = ref.strip()
        else:
            sys_name = (sys_name_raw or "").strip()
            sys_ref = (sys_ref_raw or "").strip()

        # Recherche dans la DB
        si_row = get_si_from_db(sys_name, sys_ref)
        # On prépare un dict de base
        base = si_row or {}

        # Priorité aux champs carac1, carac2, etc de la BDD
        for k in range(5):
            key = f"carac_{k + 1}"
            base[key] = base.get(key, "") or base.get(f"carac{k + 1}", "") or ""

        # Ensuite seulement, on écrase si Caractéristiques existe
        raw_caracs = base.get("Caractéristiques", "")
        if raw_caracs:
            lignes = [l.strip() for l in raw_caracs.splitlines() if l.strip()]
            for k in range(5):
                if k < len(lignes):
                    base[f"carac_{k + 1}"] = lignes[k]

        si_details.append(base)

        # Ajout du chemin image si dispo
        if si_row and si_row.get("Image"):
            img_name = si_row["Image"].strip()
            if img_name.startswith("http://") or img_name.startswith("https://"):
                si_details[-1]["IMAGE_URL"] = img_name
            else:
                si_details[-1]["IMAGE_URL"] = url_for('static', filename=f"si/{img_name}")
        else:
            si_details[-1]["IMAGE_URL"] = ""

    # Injecter les détails
    ctx["module_details"] = module_details
    ctx["inverter_details"] = inverter_details
    ctx["si_details"] = si_details

    # Nettoyage MODULE_DB pour éviter doublons et lignes vides
    clean_modules = MODULE_DB.dropna(subset=["Nom complet"])
    clean_modules = clean_modules[clean_modules["Nom complet"].str.strip() != ""]
    clean_modules = clean_modules.drop_duplicates(subset=["Nom complet"], keep="first")
    ctx["panel_db"] = clean_modules.set_index("Nom complet").to_dict(orient="index")

    # Nettoyage INVERTER_DB
    clean_inverters = INVERTER_DB.dropna(subset=["Nom complet"])
    clean_inverters = clean_inverters[clean_inverters["Nom complet"].str.strip() != ""]
    clean_inverters = clean_inverters.drop_duplicates(subset=["Nom complet"], keep="first")
    ctx["inverter_db"] = clean_inverters.set_index("Nom complet").to_dict(orient="index")

    # Reconstruit les blocs d'onduleurs supplémentaires d'un brouillon sauvegardé.
    extra_inverter_rows = []
    for i in range(len(zones)):
        names = form_values.getlist(f'zone-{i}-inverter-extra')
        field_values = {
            suffix: form_values.getlist(f'zone-{i}-inverter-extra-{suffix}')
            for suffix in INVERTER_FORM_FIELDS
        }
        rows = []
        for row_index, name in enumerate(names):
            row = {'name': name}
            for suffix, values in field_values.items():
                row[suffix] = values[row_index] if row_index < len(values) else ''
            rows.append(row)
        extra_inverter_rows.append(rows)
    ctx['extra_inverter_rows'] = extra_inverter_rows

    # Nettoyage et injection SI_DB pour le JS
    clean_si = SI_DB.copy()

    # Supprime les lignes sans Marque ou Référence
    if not clean_si.empty:
        clean_si = clean_si.dropna(subset=["Marque", "Référence"])
        clean_si = clean_si[(clean_si["Marque"].str.strip() != "") &
                            (clean_si["Référence"].str.strip() != "")]
        clean_si = clean_si.drop_duplicates(subset=["Marque", "Référence"], keep="first")

        # Crée une clé unique identique à SI_OPTIONS ("Marque - Référence")
        clean_si["Nom complet"] = clean_si["Marque"] + " - " + clean_si["Référence"]

        ctx["si_db"] = clean_si.set_index("Nom complet").to_dict(orient="index")
    else:
        ctx["si_db"] = {}

    # Les informations générales peuvent avoir été corrigées après l'import.
    # Elles doivent donc primer sur les valeurs extraites du CSV à la reprise.
    for key in (
        'nom_projet', 'ville', 'adresse', 'maitre_ouvrage', 'latitude', 'longitude', 'AC_VT',
        'bt_mt', 'implantation_globale', 'deposecandelabres', 'abattagearbres',
        'training_required', 'training_responsible',
        'training_people', 'training_hours', 'project_financing', 'spv_name',
    ):
        if form_values.get(key) is not None:
            ctx[key] = form_values.get(key)

    ctx.update({
        'form_values': form_values,
        # Le template emploie déjà request.form à de nombreux endroits. On lui
        # fournit les valeurs du brouillon lors d'une reprise.
        'request': SimpleNamespace(form=form_values),
        'project_id': saved_project.get('id') if saved_project else '',
        'saved_omb_table': load_table_json(form_values, 'omb_table'),
        'saved_hang_table': load_table_json(form_values, 'hang_table'),
    })
    return render_template('formulaire.html', **ctx)


@app.route('/projects/<int:project_id>')
def project_resume(project_id):
    project = _get_project(project_id)
    if not project:
        return "Projet introuvable.", 404
    return form(saved_project=project)


@app.route('/projects/<int:project_id>/delete', methods=['POST'])
def project_delete(project_id):
    project = _get_project(project_id)
    if not project:
        return "Projet introuvable.", 404
    if USE_SUPABASE:
        _sb_delete("projects", {"id": f"eq.{project_id}"})
    else:
        _sqlite_delete("projects", project_id)
    for image_ref in project_photo_refs(project):
        delete_project_image(image_ref)
    return redirect(url_for('upload'))


@app.route('/projects/save', methods=['POST'])
def project_save():
    project_id_raw = (request.form.get('project_id') or '').strip()
    if project_id_raw and not project_id_raw.isdigit():
        return "Identifiant de projet invalide.", 400
    project_id = int(project_id_raw) if project_id_raw else None
    existing_project = _get_project(project_id) if project_id is not None else None
    if project_id is not None and not existing_project:
        return "Projet introuvable.", 404
    old_photo_refs = project_photo_refs(existing_project)
    form_data = request.form.to_dict(flat=False)
    form_data.pop('project_id', None)
    for photo_key in ('structure_model', 'structure_location', 'structure_reinforcement'):
        refs = [
            ref for ref in (
                normalize_project_image_ref(value)
                for value in request.form.getlist(f'{photo_key}_photo_saved')
            )
            if ref
        ]
        image_file = request.files.get(f'{photo_key}_photo_file')
        if image_file and image_file.filename:
            saved = save_project_image(image_file)
            if saved:
                refs = [saved]
        form_data[f'{photo_key}_photo_saved'] = refs[:1]
    form_payload = form_data if USE_SUPABASE else json.dumps(form_data)
    project_name = (request.form.get('nom_projet') or '').strip() or 'Projet sans nom'
    payload = {
        'name': project_name,
        'form_data': form_payload,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    if project_id:
        if USE_SUPABASE:
            _sb_update('projects', {'id': f'eq.{project_id}'}, payload)
        else:
            _sqlite_update('projects', payload, project_id)
        saved_id = project_id
    else:
        if USE_SUPABASE:
            inserted = _sb_insert('projects', payload)
            if not inserted:
                return "Impossible de sauvegarder le projet.", 502
            saved_id = inserted[0]['id']
        else:
            saved_id = _sqlite_insert('projects', payload)
    new_photo_refs = {
        ref for photo_key in ('structure_model', 'structure_location', 'structure_reinforcement')
        for ref in form_data.get(f'{photo_key}_photo_saved', [])
        if normalize_project_image_ref(ref)
    }
    for obsolete_ref in old_photo_refs - new_photo_refs:
        delete_project_image(obsolete_ref)
    return redirect(url_for('project_resume', project_id=saved_id))


# noinspection PyUnusedImports
@app.route('/generate', methods=['POST'])  # Génaration du document Word à partir des données du formulaire
def generate():
    g = request.form.get  # On crée un alias pour simplifier l'accès aux données du formulaire

    # Récupère l'implantation globale choisie ou utilise la valeur du CSV par défaut
    implantation_val = (g('implantation_globale') or '').strip()
    if not implantation_val:
        # Si rien n'a été sélectionné manuellement, on utilise la valeur du CSV
        csv_val = (g('type_installation_csv') or '').strip()
        if csv_val:
            implantation_val = INSTALLATION_MAP.get(csv_val, csv_val)
    # Si aucune information n'est disponible, on peut définir une valeur par défaut:
    if not implantation_val:
        implantation_val = "Non défini"

    # On récupère les informations saisies par l'utilisateur, si elles sont manquantes, on prend une valeur par défaut
    nom_projet = (g('nom_projet') or g('nom projet') or 'inconnu').strip()  # Nom du projet
    ville = (g('ville') or 'inconnue').strip()  # Ville du projet
    deposecandelabres_val = (g('deposecandelabres') or '0').strip()
    abattagearbres_val = (g('abattagearbres') or '0').strip()
    deposecandelabres = "1" if deposecandelabres_val == '1' else ""
    abattagearbres = "1" if abattagearbres_val == '1' else ""
    adresse = (g('adresse') or 'inconnue').strip()  # Adresse du projet
    zones = json.loads(g('zones_json', '[]'))  # On récupère les zones sous forme de JSON depuis le formulaire

    # On prépare un dictionnaire avec toutes les informations qu'on va insérer dans le modèle Word
    ctx = {
        'implantation_globale': implantation_val,
        'nom_projet': nom_projet,  # Le nom du projet
        'ville': ville,  # Pareil
        'deposecandelabres': deposecandelabres,
        'abattagearbres': abattagearbres,
        'adresse': adresse,  # Pareil
        'date': datetime.today().strftime('%d/%m/%Y'),  # Date du jour, formatée en français
        'latitude': g('latitude', '').strip(),  # Latitude
        'longitude': g('longitude', '').strip(),  # Longitude
        'AC_VT': g('AC_VT', 'Autoconsommation'),  # Choix entre Autoconsommation ou Vente Totale
        'VOTRE_TENSION': get_voltage(g('bt_mt', 'BT')),  # 400V ou 800V
        'liaison_terre_zones': list({g(f'zone-{i}-liaison_terre', '') for i in range(len(zones))}),
        # Récupère la liaison à la terre pour chaque zone. On crée un ensemble pour éviter les doublons.
        'decouplage_zones': list({g(f'zone-{i}-decouplage', '') for i in range(len(zones))}),  # Pareil
        'has_paratonnerre': any(
            g(f'zone-{i}-paratonnerre') in {'oui', 'on'} for i in range(len(zones))
        ),
        # Pareil à la différence qu'on ne vérifie pas que l'ensemble des zones ait le paramètre de renséigné mais qu'au mois une zone l'ait pour savori si on affichera la partie dans 8.3.7 Fourniture et pose des coffrets DC
        'coffretDC': any(
            g(f'zone-{i}-coffretDC') in {'oui', 'on'} for i in range(len(zones))
        ),
        'has_sdis_or_icpe': any(
            # Pareil qu'au dessus mais cette fois on cherche à voir si ICPE OU préconisations SDIS apparait au moins une fois (l'un ou l'autre) toujours dans l'ensemble des zones
            ('Préconisations SDIS' in request.form.getlist(f'zone-{i}-autres_specificites')) or
            ('ICPE' in request.form.getlist(f'zone-{i}-typologie_batiment'))
            for i in range(len(zones))
        ),
        'Ombrieres': to_bool(request.form, 'Ombrieres'),
        # Vérifie si l'utilisateur a sélectionné "Ombrières" dans le formulaire. N'influe pas sur l'apparition du tableau dans le formulaire mais sur l'apparition du tableau dans le word au sein du lot charpente.
        'Hangars': to_bool(request.form, 'Hangars'),  # Pareil
        'travaux_rh': to_bool(request.form, 'travaux_rh'),
        # Pareil mais pour la section Réseaux humides dans le lot VRD
        'ouvrages_retention': to_bool(request.form, 'ouvrages_retention'),
        # Pareil mais pour savoir si le paragraphe à rédiger par les VRDistes doit apparaitre
        'KEEP_LOT_BORNES': 'keep_lot_bornes' in request.form,
        # Permet de vérifier si on a coché le lot des bornes de recharge pour décider si cette section sera incluse dans le document final.
        'KEEP_LOT_CHARPENTE': 'keep_lot_charpente' in request.form,  # Pareil
        'KEEP_LOT_GROS_OEUVRE': 'keep_lot_gros_oeuvre' in request.form,  # Pareil
        'KEEP_LOT_FONDATIONS_SPECIALES': 'keep_lot_fondations_speciales' in request.form,  # Pareil
        'KEEP_LOT_HTA': 'keep_lot_hta' in request.form,  # Pareil
        'KEEP_LOT_COUVERTURE': 'keep_lot_couverture' in request.form,
        'KEEP_DESAMIANTAGE': (
            'keep_lot_couverture' in request.form and 'keep_desamiantage' in request.form
        ),
        'KEEP_LOT_RENFORCEMENT': 'keep_lot_renforcement' in request.form,
        'bridage_dynamique_enabled': g('bridage_dyn') in {'oui', 'on'},
        'bridage_dynamique_defined': g('bridage_dyn') in {'oui', 'on', 'non'},
        'bridage_dynamique_value': (g('bridage_dyn_value', '') or '').strip(),
        'EPC_MODE': (g('epc_mode', 'non_determine') or 'non_determine').strip(),
        'TRAINING_ENABLED': g('training_required', 'non_determine') == 'oui',
        'TRAINING_RESPONSIBLE': (g('training_responsible', '') or '').strip(),
        'TRAINING_PEOPLE': (g('training_people', '') or '').strip(),
        'TRAINING_HOURS': (g('training_hours', '') or '').strip(),
    }

    ctx['HAS_STRUCTURAL_CONCRETE'] = (
        ctx['KEEP_LOT_CHARPENTE'] and (ctx['Ombrieres'] or ctx['Hangars'])
    )

    ctx['valorisation'] = "l'autoconsommation" if ctx['AC_VT'] == "Autoconsommation" else "la vente totale"

    for i, z in enumerate(zones):
        # Le nombre de panneaux peut être corrigé directement dans le formulaire.
        z['modules'] = _to_int(g(f'zone-{i}-modules', str(z.get('modules', '0'))))
        z['puissance'] = _to_float(g(f'zone-{i}-puissance', str(z.get('puissance', '0'))))

        for key in ('typologie_batiment', 'referentiel_technique', 'autres_specificites'):
            z[key] = request.form.getlist(f'zone-{i}-{key}')

            z[f'{key}_display'] = review_text(", ".join(z[key]))

        z['mode_valorisation'] = request.form.getlist(f'zone-{i}-mode_valorisation')
        # Reprise des brouillons enregistrés pendant la courte version à deux champs.
        if not z['mode_valorisation']:
            support = (g(f'zone-{i}-support_scheme', '') or '').strip()
            energy = (g(f'zone-{i}-energy_use', '') or '').strip()
            old_support = {'s21': 'S21', 'aos': 'AOS', 'ao_cre': 'AO CRE'}
            old_energy = {'acc': 'ACC', 'agregateur': 'Agrégateur', 'sans_injection': 'Sans revente'}
            z['mode_valorisation'] = [
                value for value in (old_support.get(support), old_energy.get(energy)) if value
            ]
        z['mode_valorisation_display'] = review_text(", ".join(z['mode_valorisation']))

        z['si'] = g(f'zone-{i}-si', 'Non défini')  # Choix du module photovoltaïque
        if z['si'] == '__manual__':
            z['si_label'] = request.form.get(f'zone-{i}-si-ref', 'Saisie manuelle')
        else:
            z['si_label'] = z['si']
        z['integration_display'] = review_text(
            z['si_label'] if z['si_label'] not in {'', 'Non défini'} else ''
        )

        z['module'] = g(f'zone-{i}-module', 'Non défini')  # Choix du module photovoltaïque
        if z['module'] == '__manual__':
            z['module_label'] = request.form.get(f'zone-{i}-module-ref', 'Saisie manuelle')
        else:
            z['module_label'] = z['module']
        z['module_display'] = review_text(
            z['module_label'] if z['module_label'] not in {'', 'Non défini'} else ''
        )

        z['inverter'] = (g(f'zone-{i}-inverter', 'Non défini') or 'Non défini').strip()
        extra_inverter_values = request.form.getlist(f'zone-{i}-inverter-extra')
        inverter_entries = []
        if z['inverter'] and z['inverter'] != 'Non défini':
            inverter_entries.append((z['inverter'], None))
        inverter_entries.extend(
            (value.strip(), extra_index)
            for extra_index, value in enumerate(extra_inverter_values)
            if value and value.strip()
        )
        z['inverters'] = []
        for name, extra_index in inverter_entries:
            if name == '__manual__':
                if extra_index is None:
                    label = request.form.get(f'zone-{i}-inverter-ref', 'Saisie manuelle')
                else:
                    manual_refs = request.form.getlist(f'zone-{i}-inverter-extra-ref')
                    label = manual_refs[extra_index] if extra_index < len(manual_refs) else 'Saisie manuelle'
            else:
                label = name
            z['inverters'].append({
                'name': name,
                'label': label,
                'extra_index': extra_index,
            })
        z['inverter_labels'] = [item['label'] for item in z['inverters']]
        z['inverter_count'] = len(z['inverters'])
        z['has_multiple_inverters'] = len(z['inverters']) > 1
        z['inverter_label'] = ', '.join(z['inverter_labels']) if z['inverter_labels'] else 'Non défini'
        z['inverter_display'] = review_text(
            z['inverter_label'] if z['inverter_label'] not in {'', 'Non défini'} else ''
        )
        z['inverter_location'] = (g(f'zone-{i}-inverter-location', '') or '').strip()
        z['inverter_location_other'] = (g(f'zone-{i}-inverter-location-other', '') or '').strip()
        z['inverter_roof_frame'] = (g(f'zone-{i}-inverter-roof-frame', 'non_determine') or 'non_determine').strip()
        z['webdyn'] = (g(f'zone-{i}-webdyn', 'Aucun') or 'Aucun').strip()  # Type de supervision (Webdyn)
        z['paratonnerre_choice'] = (g(f'zone-{i}-paratonnerre', 'non_determine') or 'non_determine').strip()
        z['paratonnerre'] = z['paratonnerre_choice'] in {'oui', 'on'}
        z['coffret_dc_choice'] = (g(f'zone-{i}-coffretDC', 'non_determine') or 'non_determine').strip()
        z['coffretDC'] = z['coffret_dc_choice'] in {'oui', 'on'}
        z['coffret_dc_display'] = review_text(
            {'oui': 'Oui', 'on': 'Oui', 'non': 'Non'}.get(z['coffret_dc_choice'], '')
        )
        z['coffret_dc_location'] = (g(f'zone-{i}-coffretDC-location', '') or '').strip()
        z['coffret_dc_location_other'] = (g(f'zone-{i}-coffretDC-location-other', '') or '').strip()
        z['bridage_choice'] = (g(f'zone-{i}-bridage_enabled', 'non_determine') or 'non_determine').strip()
        z['bridage_enabled'] = z['bridage_choice'] in {'oui', 'on'}
        z['bridage_value'] = (g(f'zone-{i}-bridage_value', '') or '').strip() if z[
            'bridage_enabled'] else ''  # On récupère la valeur du bridage et on l'assigne directement si activé et non vide

    flat_types = [t for z in zones for t in (z.get('typologie_batiment') or []) if
                  t]  # Rassemble toutes les typologies de bâtiment
    type_installation = ', '.join(
        sorted(set(flat_types)))  # On dédoublonne et on crée une liste des types d'installation
    has_ombrieres = any((z.get('type') or '') in OMB_TYPES for z in zones)  # Vérifie si des zones ont des ombrières
    has_toiture = any((z.get('type') or '') in TOITURE_TYPES for z in zones)  # Vérifie si des zones ont des toitures
    total_puiss, total_mod = compute_totals(zones)  # Calcule la puissance totale et le nombre de modules

    inverter_location_labels = {
        'ombriere_head': "en tête de poteau d’ombrière",
        'roof': "en toiture",
        'roof_frame': "en toiture",
        'external_facade': "en façade extérieure du bâtiment",
        'indoor_room': "dans un local technique intérieur dédié",
        'ground_frame': "au sol sur un châssis ou une dalle adaptés",
    }
    inverter_location_lines = []
    selected_inverter_locations = set()
    for zone_index, zone in enumerate(zones, 1):
        location = zone.get('inverter_location', '')
        selected_inverter_locations.add(location) if location else None
        if location == 'other':
            label = zone.get('inverter_location_other', '')
        else:
            label = inverter_location_labels.get(location, '')
        zone_name = zone.get('name') or f'Zone {zone_index}'
        if label:
            zone_label = zone_name[:1].lower() + zone_name[1:]
            inverter_location_lines.append(
                f"Pour la {zone_label}, les onduleurs seront installés {label}."
            )
        else:
            inverter_location_lines.append("")

    if zones and all(zone.get('inverter_location') and (
        zone.get('inverter_location') != 'other' or zone.get('inverter_location_other')
    ) for zone in zones):
        ctx['INVERTER_LOCATION_TEXT'] = " ".join(inverter_location_lines)
    else:
        ctx['INVERTER_LOCATION_TEXT'] = MissingTemplateValue()

    location_requirements = []
    if 'ombriere_head' in selected_inverter_locations:
        location_requirements.append(
            "En tête de poteau d’ombrière, les supports seront dimensionnés pour les charges, le vent, "
            "les vibrations et l’accessibilité de maintenance, avec protection contre les chocs et intempéries."
        )
    if selected_inverter_locations.intersection({'roof', 'roof_frame'}):
        location_requirements.append(
            "En toiture, l’implantation préservera l’étanchéité et les dégagements nécessaires à la ventilation, "
            "à l’exploitation et à la maintenance des onduleurs."
        )
    if 'external_facade' in selected_inverter_locations:
        location_requirements.append(
            "En façade extérieure, ils seront protégés des chocs et intempéries, fixés sur un support adapté "
            "et implantés en tenant compte des exigences de sécurité incendie applicables."
        )
    if 'indoor_room' in selected_inverter_locations:
        location_requirements.append(
            "Le local technique intérieur disposera d’une ventilation adaptée, d’une signalétique, d’un accès "
            "de maintenance et des performances de résistance au feu exigées par le référentiel du projet."
        )
    if 'ground_frame' in selected_inverter_locations:
        location_requirements.append(
            "Au sol, les onduleurs seront installés sur une dalle ou un châssis stable, hors d’eau, protégé des "
            "chocs et compatible avec les contraintes d’exploitation et de maintenance."
        )
    ctx['INVERTER_LOCATION_REQUIREMENTS'] = (
        " ".join(location_requirements) if location_requirements else MissingTemplateValue()
    )
    roof_zones = [zone for zone in zones if zone.get('inverter_location') in {'roof', 'roof_frame'}]
    ctx['HAS_ROOF_INVERTERS'] = bool(roof_zones)
    ctx['HAS_ROOF_CHASSIS'] = any(
        zone.get('inverter_roof_frame') == 'oui' or (
            zone.get('inverter_location') == 'roof_frame'
            and zone.get('inverter_roof_frame') == 'non_determine'
        )
        for zone in roof_zones
    )
    ctx['ROOF_CHASSIS_UNDEFINED'] = any(
        zone.get('inverter_roof_frame') == 'non_determine'
        and zone.get('inverter_location') != 'roof_frame'
        for zone in roof_zones
    )
    ctx['ROOF_CHASSIS_REVIEW'] = review_text(
        '', "À compléter : préciser si un châssis de pose est prévu pour les onduleurs en toiture."
    ) if ctx['ROOF_CHASSIS_UNDEFINED'] else review_text('')

    dc_choices = [zone.get('coffret_dc_choice', 'non_determine') for zone in zones]
    ctx['COFFRET_DC_UNDEFINED'] = any(choice == 'non_determine' for choice in dc_choices)
    ctx['SHOW_COFFRET_DC'] = ctx['coffretDC'] or ctx['COFFRET_DC_UNDEFINED']
    if ctx['COFFRET_DC_UNDEFINED']:
        ctx['EARTHING_DC_BOX_TEXT'] = review_text('', "Les coffrets DC ;")
    elif ctx['coffretDC']:
        ctx['EARTHING_DC_BOX_TEXT'] = review_text("Les coffrets DC ;")
    else:
        ctx['EARTHING_DC_BOX_TEXT'] = False
    ctx['DC_LABEL_LOCATION_TEXT'] = review_text(
        "Une étiquette sur la partie DC avec la mention « Attention, câbles courant continu sous tension » "
        "au niveau des boîtes de jonction, des coffrets DC et des canalisations DC ;"
        if ctx['SHOW_COFFRET_DC'] else
        "Une étiquette sur la partie DC avec la mention « Attention, câbles courant continu sous tension » "
        "au niveau des boîtes de jonction et des canalisations DC ;"
    )
    dc_switch_label = (
        "Une étiquette portant la mention « Ne pas manœuvrer en charge » à l’intérieur des coffrets DC "
        "et à proximité des sectionneurs-fusibles ;"
    )
    if ctx['COFFRET_DC_UNDEFINED']:
        ctx['DC_BOX_SWITCH_LABEL_TEXT'] = review_text('', dc_switch_label)
    elif ctx['coffretDC']:
        ctx['DC_BOX_SWITCH_LABEL_TEXT'] = review_text(dc_switch_label)
    else:
        ctx['DC_BOX_SWITCH_LABEL_TEXT'] = False
    ctx['STRING_LABEL_TEXT'] = review_text(
        "Chaque chaîne sera repérée par un étiquetage spécifique (N° Chaîne / N° MPPT / N° OND), en sortie "
        + ("de chaîne, au niveau des coffrets DC et au niveau de l’onduleur." if ctx['SHOW_COFFRET_DC'] else "de chaîne et au niveau de l’onduleur.")
    )

    dc_location_labels = {
        'ombriere_head': "en tête de poteau d’ombrière",
        'roof_frame': "en toiture sur un châssis métallique adapté",
        'external_facade': "en façade extérieure du bâtiment",
        'indoor_room': "dans un local technique dédié",
        'ground_frame': "au sol sur un châssis ou une dalle adaptés",
    }
    dc_location_lines = []
    dc_location_missing = False
    for zone_index, zone in enumerate(zones, 1):
        if not zone.get('coffretDC') and zone.get('coffret_dc_choice') != 'non_determine':
            continue
        location = zone.get('coffret_dc_location', '')
        label = (
            zone.get('coffret_dc_location_other', '')
            if location == 'other' else dc_location_labels.get(location, '')
        )
        zone_name = zone.get('name') or f'Zone {zone_index}'
        if label:
            zone_label = zone_name[:1].lower() + zone_name[1:]
            dc_location_lines.append(
                f"Pour la {zone_label}, les coffrets DC seront installés {label}."
            )
        else:
            dc_location_missing = True
    ctx['DC_BOX_LOCATION_TEXT'] = (
        MissingTemplateValue()
        if dc_location_missing else " ".join(dc_location_lines)
    )

    installation_responsibility = (
        g('ombriere_installation_responsibility', 'non_determine') or 'non_determine'
    ).strip()
    full_integration_text = "Le titulaire devra assurer la pose du système d’intégration."
    full_module_text = "Le titulaire devra assurer la pose des modules photovoltaïques."
    if has_ombrieres and ctx['KEEP_LOT_CHARPENTE']:
        if installation_responsibility == 'lot_charpente':
            ctx['INTEGRATION_INSTALLATION_TEXT'] = review_text(
                "Le titulaire devra assurer la pose du système d’intégration, hormis pour les ombrières "
                "photovoltaïques, pour lesquelles cette prestation sera réalisée par le lot Charpente."
            )
            ctx['MODULE_INSTALLATION_TEXT'] = review_text(
                "Le titulaire devra assurer la pose des modules photovoltaïques, hormis pour les ombrières "
                "photovoltaïques, pour lesquelles cette prestation sera réalisée par le lot Charpente."
            )
        elif installation_responsibility == 'titulaire_pv':
            ctx['INTEGRATION_INSTALLATION_TEXT'] = review_text(full_integration_text)
            ctx['MODULE_INSTALLATION_TEXT'] = review_text(full_module_text)
        else:
            missing_responsibility = (
                "À compléter : préciser si la pose des systèmes d’intégration et des modules des ombrières "
                "est à la charge du titulaire photovoltaïque ou du lot Charpente."
            )
            ctx['INTEGRATION_INSTALLATION_TEXT'] = review_text('', missing_responsibility)
            ctx['MODULE_INSTALLATION_TEXT'] = review_text('', missing_responsibility)
    else:
        ctx['INTEGRATION_INSTALLATION_TEXT'] = review_text(full_integration_text)
        ctx['MODULE_INSTALLATION_TEXT'] = review_text(full_module_text)

    selected_modes = {
        mode for z in zones for mode in (z.get('mode_valorisation') or [])
    }
    support_schemes = list(dict.fromkeys(
        mode for z in zones for mode in (z.get('mode_valorisation') or [])
        if mode in {'S21', 'AOS', 'AO CRE'}
    ))
    if 'ACC' in selected_modes:
        ctx['valorisation'] = "l’autoconsommation collective"
    elif 'Agrégateur' in selected_modes:
        ctx['valorisation'] = "la revente auprès d’un agrégateur"
    elif 'Sans revente' in selected_modes:
        ctx['valorisation'] = "l’autoconsommation sans revente"

    # On met à jour le contexte avec ces données globales
    ctx.update({
        'ZONES': zones,  # Liste des zones à inclure dans le document
        'NB_ZONES': len(zones),  # Nombre total de zones
        'type_installation': type_installation,  # Liste des types d'installation
        'has_ombrieres': has_ombrieres,  # Présence d'ombrières
        'has_toiture': has_toiture,  # Présence de toitures
        'TOTAL_PUISSANCE': total_puiss,  # Puissance totale
        'TOTAL_MODULES': total_mod,  # Nombre total de modules
        'SELECTED_INTEGRATION': [z.get('integration', '') for z in zones],
        # Liste des intégrations sélectionnées par zone
        'SELECTED_MODULES': [z.get('module', '') for z in zones],  # Liste des modules sélectionnés par zone
        'SELECTED_INV': [z.get('inverter', '') for z in zones],  # Liste des onduleurs sélectionnés par zone
        'SELECTED_INVERTERS': [z.get('inverter_labels', []) for z in zones],
        'HAS_MULTIPLE_INVERTERS': any(z.get('has_multiple_inverters') for z in zones),
        'AUTOCONSOMMATION': g('AC_VT', 'Vente Totale'),  # Choix AC/VT
        'BT_MT': g('bt_mt', 'BT'),  # Choix BT/MT
        'puissance_kwc': total_puiss  # Puissance totale pour le CCTP
    })
    project_financing = (g('project_financing', 'non_determine') or 'non_determine').strip()
    client_name = (g('maitre_ouvrage') or '').strip()
    if project_financing == 'tiers_investissement':
        effective_owner = (g('spv_name') or '').strip()
    elif project_financing == 'achat_direct':
        effective_owner = client_name
    else:
        effective_owner = ''

    ctx.update({
        'SUPPORT_SCHEMES': support_schemes,
        'HAS_VENTE_TOTALE': ctx['AC_VT'] == 'Vente Totale',
        'HAS_AUTOCONSOMMATION': ctx['AC_VT'] == 'Autoconsommation' and 'ACC' not in selected_modes,
        'HAS_ACC': 'ACC' in selected_modes,
        'HAS_AGGREGATEUR': 'Agrégateur' in selected_modes,
        'HAS_ICPE': any('ICPE' in (z.get('typologie_batiment') or []) for z in zones),
    })

    # Détection des plots soudés
    has_plots_soudes = any(
        'TT SOUDE' in (z.get('type') or '').upper()
        and g(f'zone-{i}-plots_soudes') in {'oui', 'on'}
        for i, z in enumerate(zones)
    )
    ctx['has_plots_soudes'] = has_plots_soudes

    lines = []  # Liste des lignes pour le bridage
    for idx, z in enumerate(zones, 1):
        if z.get('bridage_enabled'):
            inv = (z.get('inverter') or '').strip() or z.get('name', f'Zone {idx}')  # Nom de l'onduleur ou zone
            v = (z.get('bridage_value') or '').replace(',', '.').strip()  # Valeur du bridage
            lines.append(
                f"- L’onduleur {inv} sera bridé à {v} kVA" if v else
                f"- L’onduleur {inv} fera l’objet d’un bridage statique (valeur à définir)"
            )

    # Mise à jour du contexte pour le bridage
    ctx.update({'has_bridage': bool(lines), 'bridage_lines': lines, 'bridage_paragraph': "\n".join(lines)})

    webdyn_simple = [f"Zone {i + 1}" for i, z in enumerate(zones) if
                     (z.get('webdyn') or 'Aucun').strip() == 'Webdyn simple']  # Zones avec Webdyn simple
    webdyn_bridage = [f"Zone {i + 1}" for i, z in enumerate(zones) if (z.get(
        'webdyn') or 'Aucun').strip() == 'Webdyn avec bridage dynamique']  # Zones avec Webdyn et bridage dynamique
    coffret_suivi = [f"Zone {i + 1}" for i, z in enumerate(zones) if (z.get(
        'webdyn') or 'Aucun').strip() == 'Coffret de supervision ELUM']  # Zones avec coffret de supervision ELUM
    ctx.update({'webdyn_simple': webdyn_simple, 'webdyn_bridage': webdyn_bridage,
                'coffret_suivi': coffret_suivi})  # Mise à jour du contexte

    ctx.update({
        'OMB_TABLE': sanitize_rows(load_table_json(request.form, 'omb_table')),  # Données pour les ombrières
        'HANG_TABLE': sanitize_rows(load_table_json(request.form, 'hang_table'))  # Données pour les hangars
    })

    # Valeurs propres à la page de garde : les informations absentes doivent
    # rester immédiatement visibles dans le document à relire.
    ctx.update({
        'COVER_NOM_PROJET': review_text(
            g('nom_projet') or g('nom projet'), 'À compléter',
            size=24, bold=True, color='175649'
        ),
        'COVER_SITE_VILLE': review_text(
            g('ville'), 'À compléter', size=18, color='175649'
        ),
        'COVER_PUISSANCE': review_text(
            total_puiss if total_puiss else '', 'À compléter', size=18, color='175649'
        ),
        'COVER_MAITRE_OUVRAGE': review_text(
            effective_owner, 'À compléter', size=24, bold=True, color='175649'
        ),
        'COVER_ADRESSE': review_text(
            g('adresse'), 'À compléter', size=18, color='1D1D1B'
        ),
        'COVER_ADDRESS_VILLE': review_text(
            g('ville'), 'À compléter', size=18, color='1D1D1B'
        ),
    })

    tpl = DocxTemplate(app.config['TEMPLATE'])
    from docxtpl import InlineImage
    from docx.shared import Cm
    import os

    def inline_project_image(source, max_width_cm, max_height_cm):
        if not source:
            return ""
        try:
            if hasattr(source, 'read'):
                source.stream.seek(0)
                data = source.read(10 * 1024 * 1024 + 1)
                if len(data) > 10 * 1024 * 1024:
                    return ""
                source = BytesIO(data)
            elif str(source).startswith(('http://', 'https://')):
                response = requests.get(str(source), timeout=15)
                response.raise_for_status()
                if len(response.content) > 10 * 1024 * 1024:
                    return ""
                source = BytesIO(response.content)
            else:
                path = os.path.join(BASE_DIR, 'static', str(source).replace('/', os.sep))
                if not os.path.isfile(path):
                    return ""
                source = path
            from docx.image.image import Image
            image_info = Image.from_file(source)
            if hasattr(source, 'seek'):
                source.seek(0)
            max_width = Cm(max_width_cm)
            max_height = Cm(max_height_cm)
            if image_info.width * max_height > image_info.height * max_width:
                return InlineImage(tpl, source, width=max_width)
            return InlineImage(tpl, source, height=max_height)
        except Exception:
            return ""

    def missing_photo_placeholder():
        """Bandeau jaune utilisé dans le Word lorsqu'une photo est attendue."""
        import struct
        import zlib

        width, height = 1200, 100
        scanline = b'\x00' + bytes((255, 242, 0)) * width
        raw_pixels = scanline * height

        def png_chunk(kind, data):
            return (
                struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
            )

        png = (
            b'\x89PNG\r\n\x1a\n'
            + png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + png_chunk(b'IDAT', zlib.compress(raw_pixels))
            + png_chunk(b'IEND', b'')
        )
        return InlineImage(tpl, BytesIO(png), width=Cm(10))

    for photo_key, context_key in (
        ('structure_model', 'STRUCTURE_MODEL_PHOTO'),
        ('structure_location', 'STRUCTURE_LOCATION_PHOTO'),
        ('structure_reinforcement', 'STRUCTURE_REINFORCEMENT_PHOTO'),
    ):
        source = request.files.get(f'{photo_key}_photo_file')
        if not source or not source.filename:
            source = normalize_project_image_ref(
                next(iter(request.form.getlist(f'{photo_key}_photo_saved')), '')
            )
        ctx[context_key] = inline_project_image(source, 14.5, 9) or missing_photo_placeholder()
    ctx['STRUCTURE_STUDY_CONCLUSIONS'] = review_text(
        g('structure_study_conclusions'),
        "À compléter à partir des conclusions de l’étude structurelle."
    )
    ctx['STRUCTURE_STUDY_PRESCRIPTIONS'] = review_text(
        g('structure_study_prescriptions'),
        "À compléter : préciser les renforcements et travaux préconisés par l’étude structurelle."
    )
    def si_photo(img_name):
        if not img_name:
            return ""
        path = os.path.join("static", "si", img_name)
        if not os.path.exists(path):
            return ""
        return InlineImage(tpl, path, width=Cm(5))


    module_list = []
    for i, z in enumerate(zones):
        mod_name = (z.get('module') or '').strip()
        if not mod_name or mod_name == 'Non défini':
            continue

        if mod_name == '__manual__':
            # On récupère les données saisies manuellement dans le formulaire
            mod = {
                "Marque PV": request.form.get(f'zone-{i}-module-marque', ''),
                "Ref PV": request.form.get(f'zone-{i}-module-ref', ''),
                "Puissance Wc": request.form.get(f'zone-{i}-module-puissance', ''),
                "Type": request.form.get(f'zone-{i}-module-type', ''),
                "Cadre": request.form.get(f'zone-{i}-module-cadre', ''),
                "Backsheet": request.form.get(f'zone-{i}-module-backsheet', ''),
                "Poids kg": request.form.get(f'zone-{i}-module-poids', ''),
                "Dimensions mm": request.form.get(f'zone-{i}-module-dimensions', ''),
                "Longueur câble mm": request.form.get(f'zone-{i}-module-cable', ''),
                "Certif carbone": request.form.get(f'zone-{i}-module-certif', ''),
                "Garantie": request.form.get(f'zone-{i}-module-garantie', ''),
                "ETN": request.form.get(f'zone-{i}-module-etn', 'non'),
            }
            module_list.append(mod)
        else:
            for _, row in MODULE_DB.iterrows():
                if (row.get('Nom complet') or '').strip().upper() == mod_name.upper():
                    module_list.append(row.to_dict())
                    break

    ctx['module_list'] = module_list  # Injecte la liste dans le contexte

    inverter_list = []
    for i, z in enumerate(zones):
        for inverter_index, selected_inverter in enumerate(z.get('inverters', [])):
            inv_name = (selected_inverter.get('name') or '').strip()
            if not inv_name or inv_name == 'Non défini':
                continue
            extra_index = selected_inverter.get('extra_index')
            if extra_index is not None:
                inv = {}
                for suffix, document_key in INVERTER_FORM_FIELDS.items():
                    values = request.form.getlist(f'zone-{i}-inverter-extra-{suffix}')
                    inv[document_key] = values[extra_index] if extra_index < len(values) else ''
                # Compatibilité avec les anciens brouillons, sans caractéristiques enregistrées.
                if not any(str(value).strip() for value in inv.values()):
                    inv = get_inverter_from_db(inv_name)
            elif inv_name == '__manual__':
                inv = {
                    "Marque": request.form.get(f'zone-{i}-inverter-marque', ''),
                    "Référence": request.form.get(f'zone-{i}-inverter-ref', ''),
                    "Puissance kVA": request.form.get(f'zone-{i}-inverter-puissance', ''),
                    "Type": request.form.get(f'zone-{i}-inverter-type', ''),
                    "Tension nominale": request.form.get(f'zone-{i}-inverter-tension', ''),
                    "Type tension": request.form.get(f'zone-{i}-inverter-type-tension', ''),
                    "Raccordement DC": request.form.get(f'zone-{i}-inverter-raccord', ''),
                    "Parafoudre DC": request.form.get(f'zone-{i}-inverter-para-dc', ''),
                    "Parafoudre AC": request.form.get(f'zone-{i}-inverter-para-ac', ''),
                    "AFCI": request.form.get(f'zone-{i}-inverter-afci', ''),
                    "Garantie": request.form.get(f'zone-{i}-inverter-garantie', ''),
                    "Extension garantie": request.form.get(f'zone-{i}-inverter-ext-garantie', ''),
                }
            else:
                inv = get_inverter_from_db(inv_name)
            if inv:
                inv = dict(inv)
                inv['Zone'] = z.get('name', f'Zone {i + 1}')
                inv['zone_name'] = inv['Zone']
                inv['is_additional'] = inverter_index > 0
                inverter_list.append(inv)

    ctx['inverter_list'] = inverter_list
    ctx['NB_INVERTERS'] = len(inverter_list)
    ctx['NB_INVERTERS_BY_ZONE'] = [z.get('inverter_count', 0) for z in zones]

    si_list = []

    for i, z in enumerate(zones):
        si_name = (z.get('si') or '').strip()
        if not si_name or si_name == 'Non défini':
            continue

        if si_name == '__manual__':
            si = {
                "Marque": request.form.get(f'zone-{i}-si-marque', ''),
                "Référence": request.form.get(f'zone-{i}-si-ref', ''),
                "Image": request.form.get(f'zone-{i}-si-image', ''),
                "Fixation": request.form.get(f'zone-{i}-si-fixation', ''),
                "Compatibilité 1": request.form.get(f'zone-{i}-si-Compat1', ''),
                "Compatibilité 2": request.form.get(f'zone-{i}-si-Compat2', ''),
                "Compatibilité 3": request.form.get(f'zone-{i}-si-Compat3', ''),
                "Compatibilité 4": request.form.get(f'zone-{i}-si-Compat4', ''),
                "Compatibilité 5": request.form.get(f'zone-{i}-si-Compat5', ''),
                "Caractéristique 1": request.form.get(f'zone-{i}-si-carac1', ''),
                "Caractéristique 2": request.form.get(f'zone-{i}-si-carac2', ''),
                "Caractéristique 3": request.form.get(f'zone-{i}-si-carac3', ''),
                "Caractéristique 4": request.form.get(f'zone-{i}-si-carac4', ''),
                "Caractéristique 5": request.form.get(f'zone-{i}-si-carac5', ''),
                "Certification": request.form.get(f'zone-{i}-si-certification', ''),
                "Garantie": request.form.get(f'zone-{i}-si-garantie', ''),
            }
            si_list.append(si)

        else:
            selected = si_name.upper()
            for _, row in SI_DB.iterrows():
                if (row["Marque"] + " - " + row["Référence"]).upper() == selected:
                    si_data = row.to_dict()
                    si_data["Image"] = row.get("Image", "")
                    si_list.append(si_data)
                    break

    # Pour chaque SI, on crée une image InlineImage exploitable par docxtpl
    import os
    from docxtpl import InlineImage
    from docx.shared import Cm

    for si in si_list:
        img_name = (si.get("Image") or "").strip()

        if not img_name:
            si["PHOTO"] = ""
            continue
        if img_name.startswith("http://") or img_name.startswith("https://"):
            try:
                with urlopen(img_name) as resp:
                    si["PHOTO"] = InlineImage(tpl, BytesIO(resp.read()), width=Cm(5))
            except Exception:
                si["PHOTO"] = ""
            continue

        path = os.path.join("static", "si", img_name)
        if os.path.exists(path):
            si["PHOTO"] = InlineImage(tpl, path, width=Cm(5))
        else:
            si["PHOTO"] = ""

    ctx["si_list"] = si_list

    def dedupe_list(lst):
        seen = []
        out = []
        for item in lst:
            norm = normalize_dict(item)
            if norm not in seen:
                seen.append(norm)
                out.append(item)
        return out

    ctx["module_list"] = dedupe_list(ctx["module_list"])
    ctx["inverter_list"] = dedupe_list(ctx["inverter_list"])
    ctx["si_list"] = dedupe_list(ctx["si_list"])
    ctx["si_details"] = si_list
    # Les variables présentes dans le modèle mais absentes du contexte ne
    # doivent plus disparaître silencieusement dans le document final.
    for variable_name in tpl.get_undeclared_template_variables(context=ctx):
        ctx[variable_name] = MissingTemplateValue()
    tpl.render(mark_empty_template_values(ctx))
    buf = BytesIO()  # On crée un tampon mémoire pour stocker le fichier généré
    tpl.save(buf)  # On enregistre le fichier dans le tampon
    buf.seek(0)
    buf = highlight_missing_values(buf, ctx.get('COFFRET_DC_UNDEFINED', False))

    # Envoi du fichier au navigateur pour téléchargement
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"CCTP_{ctx.get('nom_projet', 'projet')}.docx",  # Nom du fichier téléchargé
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        # Type MIME pour un fichier Word
    )

# --- Admin (Flask) ---
def _get_integration_caracs(integration_id):
    if USE_SUPABASE:
        rows = _sb_select(
            "integrations_caracteristiques",
            filters={"integration_id": f"eq.{integration_id}"},
            order="id.asc",
        )
        return [r.get("texte", "") for r in rows if r.get("texte")]
    rows = query(
        "SELECT texte FROM integrations_caracteristiques WHERE integration_id = ? ORDER BY id ASC",
        (integration_id,),
    )
    return [r.get("texte", "") for r in rows if r.get("texte")]

def _set_integration_caracs(integration_id, lines):
    if USE_SUPABASE:
        _sb_delete("integrations_caracteristiques", {"integration_id": f"eq.{integration_id}"})
        payload = [{"integration_id": integration_id, "texte": t} for t in lines]
        if payload:
            _sb_insert("integrations_caracteristiques", payload)
        return
    execute_sql("DELETE FROM integrations_caracteristiques WHERE integration_id = ?", (integration_id,))
    for t in lines:
        execute_sql(
            "INSERT INTO integrations_caracteristiques (integration_id, texte) VALUES (?, ?)",
            (integration_id, t),
        )

@app.route("/admin")
def admin_index():
    return render_template("admin/index.html")

@app.route("/admin/modules", methods=["GET", "POST"])
def admin_modules():
    edit_id = request.args.get("edit")
    current = _admin_get("modules", edit_id) if edit_id else None
    if request.method == "POST":
        row_id = request.form.get("id")
        existing = _admin_get("modules", row_id) if row_id else None
        data = {
            "marque": request.form.get("marque", ""),
            "reference": request.form.get("reference", ""),
            "nom_complet": request.form.get("nom_complet", ""),
            "puissance_wc": request.form.get("puissance_wc", ""),
            "type": request.form.get("type", ""),
            "cadre": request.form.get("cadre", ""),
            "backsheet": request.form.get("backsheet", ""),
            "dimensions": request.form.get("dimensions", ""),
            "longueur_cable": request.form.get("longueur_cable", ""),
            "poids": request.form.get("poids", ""),
            "garantie": request.form.get("garantie", ""),
            "certif_carbone": request.form.get("certif_carbone", ""),
            "etn": request.form.get("etn", ""),
        }
        image_url = save_image(request.files.get("image"), "modules")
        if row_id:
            if image_url:
                data["image"] = image_url
            elif existing and existing.get("image"):
                data["image"] = existing.get("image")
            if USE_SUPABASE:
                _sb_update("modules", {"id": f"eq.{row_id}"}, data)
            else:
                _sqlite_update("modules", data, row_id)
        else:
            if image_url:
                data["image"] = image_url
            if USE_SUPABASE:
                _sb_insert("modules", data)
            else:
                _sqlite_insert("modules", data)
        return redirect(url_for("admin_modules"))

    rows = _admin_list("modules")
    return render_template("admin/modules.html", rows=rows, current=current)

@app.route("/admin/modules/<int:module_id>/delete", methods=["POST"])
def admin_modules_delete(module_id):
    if USE_SUPABASE:
        _sb_delete("modules", {"id": f"eq.{module_id}"})
    else:
        _sqlite_delete("modules", module_id)
    return redirect(url_for("admin_modules"))

@app.route("/admin/onduleurs", methods=["GET", "POST"])
def admin_onduleurs():
    edit_id = request.args.get("edit")
    current = _admin_get("onduleurs", edit_id) if edit_id else None
    if request.method == "POST":
        row_id = request.form.get("id")
        existing = _admin_get("onduleurs", row_id) if row_id else None
        data = {
            "nom_complet": request.form.get("nom_complet", ""),
            "marque": request.form.get("marque", ""),
            "reference": request.form.get("reference", ""),
            "puissance_kva": request.form.get("puissance_kva", ""),
            "type": request.form.get("type", ""),
            "tension_nominale": request.form.get("tension_nominale", ""),
            "type_tension": request.form.get("type_tension", ""),
            "raccordement_dc": request.form.get("raccordement_dc", ""),
            "para_dc": request.form.get("para_dc", ""),
            "para_ac": request.form.get("para_ac", ""),
            "afci": request.form.get("afci", ""),
            "garantie": request.form.get("garantie", ""),
            "extension_garantie": request.form.get("extension_garantie", ""),
        }
        image_url = save_image(request.files.get("image"), "onduleurs")
        if row_id:
            if image_url:
                data["image"] = image_url
            elif existing and existing.get("image"):
                data["image"] = existing.get("image")
            if USE_SUPABASE:
                _sb_update("onduleurs", {"id": f"eq.{row_id}"}, data)
            else:
                _sqlite_update("onduleurs", data, row_id)
        else:
            if image_url:
                data["image"] = image_url
            if USE_SUPABASE:
                _sb_insert("onduleurs", data)
            else:
                _sqlite_insert("onduleurs", data)
        return redirect(url_for("admin_onduleurs"))

    rows = _admin_list("onduleurs")
    return render_template("admin/onduleurs.html", rows=rows, current=current)

@app.route("/admin/onduleurs/<int:onduleur_id>/delete", methods=["POST"])
def admin_onduleurs_delete(onduleur_id):
    if USE_SUPABASE:
        _sb_delete("onduleurs", {"id": f"eq.{onduleur_id}"})
    else:
        _sqlite_delete("onduleurs", onduleur_id)
    return redirect(url_for("admin_onduleurs"))

@app.route("/admin/integrations", methods=["GET", "POST"])
def admin_integrations():
    edit_id = request.args.get("edit")
    current = _admin_get("integrations", edit_id) if edit_id else None
    caracs_text = "\n".join(_get_integration_caracs(edit_id)) if edit_id else ""
    if request.method == "POST":
        row_id = request.form.get("id")
        existing = _admin_get("integrations", row_id) if row_id else None
        data = {
            "marque": request.form.get("marque", ""),
            "ref": request.form.get("ref", ""),
            "fixation": request.form.get("fixation", ""),
            "compat1": request.form.get("compat1", ""),
            "compat2": request.form.get("compat2", ""),
            "compat3": request.form.get("compat3", ""),
            "compat4": request.form.get("compat4", ""),
            "compat5": request.form.get("compat5", ""),
            "carac1": request.form.get("carac1", ""),
            "carac2": request.form.get("carac2", ""),
            "carac3": request.form.get("carac3", ""),
            "carac4": request.form.get("carac4", ""),
            "carac5": request.form.get("carac5", ""),
            "certification": request.form.get("certification", ""),
            "garantie": request.form.get("garantie", ""),
        }
        image_url = save_image(request.files.get("image"), "si")
        if row_id:
            if image_url:
                data["image"] = image_url
            elif existing and existing.get("image"):
                data["image"] = existing.get("image")
            if USE_SUPABASE:
                _sb_update("integrations", {"id": f"eq.{row_id}"}, data)
            else:
                _sqlite_update("integrations", data, row_id)
            integration_id = row_id
        else:
            if image_url:
                data["image"] = image_url
            if USE_SUPABASE:
                inserted = _sb_insert("integrations", data)
                integration_id = inserted[0]["id"] if inserted else None
            else:
                integration_id = _sqlite_insert("integrations", data)

        caracs_raw = request.form.get("caracs", "")
        lines = [line.strip() for line in caracs_raw.splitlines() if line.strip()]
        if integration_id:
            _set_integration_caracs(integration_id, lines)

        return redirect(url_for("admin_integrations"))

    rows = _admin_list("integrations")
    return render_template(
        "admin/integrations.html",
        rows=rows,
        current=current,
        caracs_text=caracs_text,
    )

@app.route("/admin/integrations/<int:integration_id>/delete", methods=["POST"])
def admin_integrations_delete(integration_id):
    if USE_SUPABASE:
        _sb_delete("integrations_caracteristiques", {"integration_id": f"eq.{integration_id}"})
        _sb_delete("integrations", {"id": f"eq.{integration_id}"})
    else:
        execute_sql("DELETE FROM integrations_caracteristiques WHERE integration_id = ?", (integration_id,))
        _sqlite_delete("integrations", integration_id)
    return redirect(url_for("admin_integrations"))

# Point d’entrée : “python app.py” lance un petit serveur web en local (debug = True)
if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)

