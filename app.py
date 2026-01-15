from flask import Flask, render_template, request, send_file, url_for  # On importe Flask : (routes / pages / formulaires)
from docxtpl import DocxTemplate  # permet de remplir le modèle word avec les variables du contexte
from datetime import datetime  # pour la date
import pandas as pd  # poru lire le CSV
import sqlite3
import re, \
    json  # re pour simplifier la recherche dans le CSV et json  pour gérer le format json (utile pour les tableaux avec des valeurs différentes selon la zone)
from io import BytesIO  # le tampon mémoire qui sert à générer le .docx sans avoir à créer un fichier dans le dur
import os
DB_PATH = os.environ.get("DB_PATH", "database.db")


app = Flask(__name__)  # création de l'app Flask
app.config.update(TEMPLATE='TemplateCCTP.docx', CSV_SEP=';',
                  MAX_ZONES=4)  # on configure le nom du template word à remplir, ce qui sépare les infos du csv (en l'occurence un ;) et le nombre de zones max (car 4 zones possibles en VT)

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


def load_module_df():
    rows = query("SELECT * FROM modules")
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
    rows = query("SELECT * FROM onduleurs")
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
    rows = query("SELECT * FROM integrations")
    if not rows:
        return pd.DataFrame(columns=[
            "Marque", "Référence", "Fixation", "Compatibilité 1", "Compatibilité 2", "Compatibilité 3", "Compatibilité 4", "Compatibilité 5",
            "Caractéristique 1", "Caractéristique 2", "Caractéristique 3", "Caractéristique 4", "Caractéristique 5", "Image",
            "Certification", "Garantie"
        ])

    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "marque": "Marque",
        "ref": "Référence",
        "fixation": "Fixation",
        "Compat1": "Compatibilité 1",
        "Compat2": "Compatibilité 2",
        "Compat3": "Compatibilité 3",
        "Compat4": "Compatibilité 4",
        "Compat5": "Compatibilité 5",
        "carac1": "Caractéristique 1",
        "carac2": "Caractéristique 2",
        "carac3": "Caractéristique 3",
        "carac4": "Caractéristique 4",
        "carac5": "Caractéristique 5",
        "image": "Image",
        "certification": "Certification",
        "garantie": "Garantie",
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



    data = dict(row)

    data["carac1"] = row["carac1"] or ""
    data["carac2"] = row["carac2"] or ""
    data["carac3"] = row["carac3"] or ""
    data["carac4"] = row["carac4"] or ""
    data["carac5"] = row["carac5"] or ""

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

    ctx = {
        # Construit le contexte envoyé au template formulaire.html ; il préremplit l’interface et transporte les données jusqu’à generate pour produire le Word
        'csv_text': ("\n".join(df.astype(str).agg(';'.join, axis=1))) if not df.empty else '',
        # Version texte du CSV (séparateur ;)
        'zones': zones,
        # Liste des zones détectées plus haut; utilisée pour afficher une colonne par zone dans la table de paramètres
        'zones_json': json.dumps(zones),
        # Sérialisation JSON ; pour que generate relise exactement les mêmes zones sans devoir relire le CSV
        'panel_options': list(PV_MODULES),
        # panneaux proposés dans les listes déroulantes ; le choix final remontera dans z['module'] et sera réutilisé dans le word
        'inverter_options': list(INVERTERS),  # Pareil
        'si_options': list(SI_OPTIONS),
        # Pour chaque zoneon propose la liste de SI correspondant grâce à la liste établie dans INTEGRATIONS
        'latitude': request.form.get('latitude', ''),  # on demande de remplir la latitude
        'longitude': request.form.get('longitude', ''),  # Pareil
        'AC_VT': request.form.get('AC_VT', 'Autoconsommation'),
        # Choix “Autoconsommation / Vente Totale”  et repris generate pour alimenter les balises word
        'bt_mt': request.form.get('bt_mt', 'BT'),
        # Choix BT/MT; repris par generate pour labalise VOTRE_TENSION dans le document word et les balises if bt_mt == "MT" dans 9.3.2.	Fourniture et pose TBGT
        'ZONES': zones,  # Permet au word d'utiliser zones en majuscules
        'NB_ZONES': len(zones),
        # Nombre total de zones utile dans le word pour afficher un bloc seulement s’il y a au moins une zone
        'default_module': module_info.get('Nom complet', '') if module_info else '',
        'module_details': module_info or {},

        **csv_data
        # ajoute dans le contexte toutes les infos projet extraites du CSV via les alias (ex. nom_projet, ville, adresse, puissance_kwc) ; chaque clé correspond directement à une balise du modèle Word pour être remplacée automatiquement
    }

    ctx['implantation_globale'] = implantation_val  # valeur mappée pour sélection par défaut
    ctx['type_installation_csv'] = ti_val  # stocke la valeur brute du CSV (pour usage ultérieur)

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

# Point d’entrée : “python app.py” lance un petit serveur web en local (debug = True)
if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)

