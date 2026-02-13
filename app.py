from flask import Flask, render_template, request, send_file, url_for, redirect  # On importe Flask : (routes / pages / formulaires)
from docxtpl import DocxTemplate  # permet de remplir le modèle word avec les variables du contexte
from datetime import datetime  # pour la date
import pandas as pd  # poru lire le CSV
import sqlite3
import re, \
    json  # re pour simplifier la recherche dans le CSV et json  pour gérer le format json (utile pour les tableaux avec des valeurs différentes selon la zone)
from io import BytesIO  # le tampon mémoire qui sert à générer le .docx sans avoir à créer un fichier dans le dur
import os
import uuid
from urllib.parse import quote
from urllib.request import urlopen

import requests
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.environ.get("DB_PATH", "database.db")
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, DB_PATH)
os.environ["DB_PATH"] = DB_PATH

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "cctp-images")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Supabase est obligatoire. Definir SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY dans l'environnement."
    )
USE_SUPABASE = True

ADMIN_URL = os.environ.get("ADMIN_URL", "/admin")

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
    resp = requests.delete(url, headers=_sb_headers(), params=filters, timeout=10)
    resp.raise_for_status()
    return resp.json()

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
    return _sb_upload_image(file_storage, folder)


app = Flask(__name__)  # création de l'app Flask
app.config.update(TEMPLATE='TemplateCCTP.docx', CSV_SEP=';',
                  MAX_ZONES=4)  # on configure le nom du template word à remplir, ce qui sépare les infos du csv (en l'occurence un ;) et le nombre de zones max (car 4 zones possibles en VT)

@app.context_processor
def inject_admin_url():
    return {"admin_url": ADMIN_URL}

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
        print("Nom d'image manquant ou vide.")
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
        print(f"Tentative de récupération de l'image : {path}")  # Debugging line
        if os.path.isfile(path):
            print(f"Image trouvée à : {path}")  # Debugging line
            with open(path, "rb") as f:
                return f.read()

    print("Aucune image trouvée pour :", img_name)  # Debugging line
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


# convertit une valeur texte en nombre flottant (float) en gerant les virgules et les valeurs vides
def _to_float(s):
    try:
        s = (s or '').replace(',',
                              '.').strip()  # si s est None on le remplace par '', on change la virgule en point et on enleve les espaces
        return float(
            s) if s and s != '-' else 0.0  # si c'est pas vide et pas juste '-' on le transforme en float sinon on renvoie 0.0
    except ValueError:
        return 0.0  # si la conversion echoue on renvoie 0.0


# Pareil dns l'autre sens, on convertit un nombre décimal en entier
def _to_int(s):
    try:
        s = (s or '').strip()
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


@app.route(
    '/')  # definit la route racine qui affiche la page d'accueil pour envoyer un CSV,charge et renvoie la page HTML upload.html au navigateur
def upload():
    return render_template('upload.html')


# Après l’envoi du CSV ; elle lit le fichier si présent, prépare toutes les données et affiche le grand formulaire par zones
@app.route('/form', methods=['POST'])
def form():

    global PV_MODULES, INVERTERS, MODULE_DB, INVERTER_DB, SI_DB

    # Recharge TOUJOURS la base à chaque appel
    MODULE_DB = load_module_df()
    INVERTER_DB = load_inverter_df()
    SI_DB = load_si_df()

    PV_MODULES = set(MODULE_DB["Nom complet"].dropna().unique().tolist())
    INVERTERS = set(INVERTER_DB["Nom complet"].dropna().unique().tolist())
    SI_OPTIONS = set((SI_DB["Marque"] + " - " + SI_DB["Référence"]).dropna().unique().tolist())

    f = request.files.get('csv_file')  # Récupère le fichier envoyé depuis upload.html
    df = parse_csv(f) if f and f.filename.lower().endswith(
        '.csv') else pd.DataFrame()  # Si on a bien un .csv, on le lit avec parse_csv pour obtenir un tableau exploitable ; sinon on part sur un DataFrame vide pour quand même afficher le formulaire
    zones = detect_zones(df)  # Détecte automatiquement “Zone 1”, “Zone 2”, etc. depuis le CSV
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

    ctx = {'csv_text': ("\n".join(df.astype(str).agg(';'.join, axis=1))) if not df.empty else '', 'zones': zones,
           'admin_url': ADMIN_URL,
           'zones_json': json.dumps(zones), 'panel_options': list(PV_MODULES), 'inverter_options': list(INVERTERS),
           'si_options': list(SI_OPTIONS), 'latitude': request.form.get('latitude', ''),
           'longitude': request.form.get('longitude', ''), 'AC_VT': request.form.get('AC_VT', 'Autoconsommation'),
           'bt_mt': request.form.get('bt_mt', 'BT'), 'ZONES': zones, 'NB_ZONES': len(zones),
           'default_module': module_info.get('Nom complet', '') if module_info else '',
           'module_details': module_info or {}, **csv_data, 'implantation_globale': implantation_val,
           'type_installation_csv': ti_val}

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
        print("SI ROW DEBUG =", si_row)

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

    return render_template('formulaire.html', **ctx)


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
        'has_paratonnerre': any(f'zone-{i}-paratonnerre' in request.form for i in range(len(zones))),
        # Pareil à la différence qu'on ne vérifie pas que l'ensemble des zones ait le paramètre de renséigné mais qu'au mois une zone l'ait pour savori si on affichera la partie dans 8.3.7 Fourniture et pose des coffrets DC
        'coffretDC': any(f'zone-{i}-coffretDC' in request.form for i in range(len(zones))),
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
        'bridage_dynamique_enabled': to_bool(request.form, 'bridage_dyn'),  # Pareil pour le bridage
        'bridage_dynamique_value': (g('bridage_dyn_value', '') or '').strip(),
    }

    ctx['valorisation'] = "l'autoconsommation" if ctx['AC_VT'] == "Autoconsommation" else "la vente totale"

    for i, z in enumerate(zones):
        for key in ('mode_valorisation', 'typologie_batiment', 'referentiel_technique', 'autres_specificites'):
            z[key] = request.form.getlist(f'zone-{i}-{key}')

            # Valeur par défaut spécifique pour la typologie bâtiment
            if key == 'typologie_batiment':
                z[f'{key}_display'] = ", ".join(z[key]) if z[key] else "A compléter"
            else:
                z[f'{key}_display'] = ", ".join(z[key]) if z[key] else "Non défini"

        z['si'] = g(f'zone-{i}-si', 'Non défini')  # Choix du module photovoltaïque
        if z['si'] == '__manual__':
            z['si_label'] = request.form.get(f'zone-{i}-si-ref', 'Saisie manuelle')
        else:
            z['si_label'] = z['si']

        z['module'] = g(f'zone-{i}-module', 'Non défini')  # Choix du module photovoltaïque
        if z['module'] == '__manual__':
            z['module_label'] = request.form.get(f'zone-{i}-module-ref', 'Saisie manuelle')
        else:
            z['module_label'] = z['module']

        z['inverter'] = g(f'zone-{i}-inverter', 'Non défini')
        if z['inverter'] == '__manual__':
            z['inverter_label'] = request.form.get(f'zone-{i}-inverter-ref', 'Saisie manuelle')
        else:
            z['inverter_label'] = z['inverter']
        z['webdyn'] = (g(f'zone-{i}-webdyn', 'Aucun') or 'Aucun').strip()  # Type de supervision (Webdyn)
        z['paratonnerre'] = f'zone-{i}-paratonnerre' in request.form  # Présence de paratonnerre
        z['coffretDC'] = f'zone-{i}-coffretDC' in request.form
        z['bridage_enabled'] = (g(f'zone-{i}-bridage_enabled') is not None)  # Activation du bridage statique
        z['bridage_value'] = (g(f'zone-{i}-bridage_value', '') or '').strip() if z[
            'bridage_enabled'] else ''  # On récupère la valeur du bridage et on l'assigne directement si activé et non vide

    flat_types = [t for z in zones for t in (z.get('typologie_batiment') or []) if
                  t]  # Rassemble toutes les typologies de bâtiment
    type_installation = ', '.join(
        sorted(set(flat_types)))  # On dédoublonne et on crée une liste des types d'installation
    has_ombrieres = any((z.get('type') or '') in OMB_TYPES for z in zones)  # Vérifie si des zones ont des ombrières
    has_toiture = any((z.get('type') or '') in TOITURE_TYPES for z in zones)  # Vérifie si des zones ont des toitures
    total_puiss, total_mod = compute_totals(zones)  # Calcule la puissance totale et le nombre de modules

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
        'AUTOCONSOMMATION': g('AC_VT', 'Vente Totale'),  # Choix AC/VT
        'BT_MT': g('bt_mt', 'BT'),  # Choix BT/MT
        'puissance_kwc': total_puiss  # Puissance totale pour le CCTP
    })

    # Détection des plots soudés
    has_plots_soudes = any(
        'TT SOUDE' in (z.get('type') or '').upper() and f'zone-{i}-plots_soudes' in request.form
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

    tpl = DocxTemplate(app.config['TEMPLATE'])
    from docxtpl import InlineImage
    from docx.shared import Cm
    import os

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
        inv_name = (z.get('inverter') or '').strip()
        if not inv_name or inv_name == 'Non défini':
            continue
        if inv_name == '__manual__':
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
            inverter_list.append(inv)
        else:
            inv = get_inverter_from_db(inv_name)
            if inv:
                inverter_list.append(inv)

    ctx['inverter_list'] = inverter_list

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

    print("===== DEBUG SI_LIST =====")
    for si in si_list:
        img_name = (si.get("Image") or "").strip()
        print("----")
        print("SI :", si.get("Marque"), "-", si.get("Référence"))
        print("Image demandée :", img_name)

        if not img_name:
            print("AUCUNE image définie pour ce SI")
            si["PHOTO"] = ""
            continue
        if img_name.startswith("http://") or img_name.startswith("https://"):
            try:
                with urlopen(img_name) as resp:
                    si["PHOTO"] = InlineImage(tpl, BytesIO(resp.read()), width=Cm(5))
                print("✔ Image URL chargée !")
            except Exception:
                print("✘ Image URL introuvable :", img_name)
                si["PHOTO"] = ""
            continue

        path = os.path.join("static", "si", img_name)
        print("Chemin testé :", path)

        print("Fichiers présents dans static/si :", os.listdir(os.path.join("static", "si")))

        if os.path.exists(path):
            print("✔ Image trouvée !")
            si["PHOTO"] = InlineImage(tpl, path, width=Cm(5))
        else:
            print("✘ Image introuvable :", path)
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

    tpl.render(ctx)  # On remplace les balises par les données du contexte
    buf = BytesIO()  # On crée un tampon mémoire pour stocker le fichier généré
    tpl.save(buf)  # On enregistre le fichier dans le tampon
    buf.seek(0)  # On se positionne au début du tampon pour pouvoir l'envoyer

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

