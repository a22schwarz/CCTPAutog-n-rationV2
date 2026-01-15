<?php
include "db.php";

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['add'])) {
    $stmt = $pdo->prepare("
        INSERT INTO onduleurs
        (nom_complet, marque, reference, puissance_kva, type, tension_nominale, type_tension, raccordement_dc, para_dc, para_ac, afci, garantie, extension_garantie)
        VALUES (:nom_complet, :marque, :reference, :puissance_kva, :type, :tension_nominale, :type_tension, :raccordement_dc, :para_dc, :para_ac, :afci, :garantie, :extension_garantie)
    ");

    $stmt->execute([
        ":nom_complet"      => $_POST['nom_complet'] ?? '',
        ":marque"           => $_POST['marque'] ?? '',
        ":reference"        => $_POST['reference'] ?? '',
        ":puissance_kva"    => $_POST['puissance_kva'] ?? '',
        ":type"             => $_POST['type'] ?? '',
        ":tension_nominale" => $_POST['tension_nominale'] ?? '',
        ":type_tension"     => $_POST['type_tension'] ?? '',
        ":raccordement_dc"  => $_POST['raccordement_dc'] ?? '',
        ":para_dc"          => $_POST['para_dc'] ?? '',
        ":para_ac"          => $_POST['para_ac'] ?? '',
        ":afci"             => $_POST['afci'] ?? '',
        ":garantie"         => $_POST['garantie'] ?? '',
        ":extension_garantie" => $_POST['extension_garantie'] ?? ''
    ]);
}

if (isset($_GET['delete'])) {
    $stmt = $pdo->prepare("DELETE FROM onduleurs WHERE id=?");
    $stmt->execute([$_GET['delete']]);
    header("Location: onduleurs.php");
    exit;
}

$rows = $pdo->query("SELECT * FROM onduleurs ORDER BY id DESC")->fetchAll(PDO::FETCH_ASSOC);
?>
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Onduleurs</title>

    <style>
     :root{
  --orange:#ff5a37;
  --green:#175649;
  --grey:#e6e6e6;
  --bg:#f4f4f4;
  --text:#1f3b36;
  --muted:#6b7b76;
  --line:#e8eceb;
  --radius:12px;
}

*{
  box-sizing:border-box;
  font-family:'Source Sans Pro', Arial, sans-serif;
}

body{
  margin:0;
  background:var(--bg);
  padding:20px;
  color:var(--text);
}

h1{
  font-size:2rem;
  font-weight:700;
  color:var(--orange);
  margin-bottom:10px;
}

h3{
  margin-top:0;
  color:var(--green);
}

.card{
  width:100%;
  background:#fff;
  padding:20px;
  border-radius:var(--radius);
  box-shadow:0 8px 20px rgba(0,0,0,0.05);
  border:1px solid var(--line);
  margin-bottom:30px;
}

.group{
  display:flex;
  flex-direction:column;
  margin-bottom:12px;
}

.group label{
  font-weight:600;
  color:var(--muted);
  margin-bottom:4px;
}

input[type="text"],
input[type="file"],
select{
  padding:10px;
  border:1px solid var(--grey);
  border-radius:8px;
  font-size:1rem;
}

input:focus, select:focus{
  outline:none;
  border-color:var(--green);
  box-shadow:0 0 0 3px rgba(23,86,73,0.25);
}

.btn{
  background:var(--orange);
  color:#fff;
  padding:10px 16px;
  border:none;
  border-radius:8px;
  font-weight:700;
  cursor:pointer;
}

.btn:hover{
  background:var(--green);
}

/* --- TABLE FIXÉE / AMÉLIORÉE --- */

.table-wrap {
  width: 100%;
  overflow-x: auto;
  border-radius: 12px;
}

table{
  width:100%;
  border-collapse:collapse;
  background:#fff;
  border-radius:12px;
  overflow:hidden;
  font-size:0.9rem;
}

thead{
  background:var(--orange);
  color:white;
}

thead th{
  padding:12px 6px;
  text-align:center;
  font-size:.85rem;
  white-space:nowrap;
}

tbody td{
  padding:10px 6px;
  border-bottom:1px solid var(--line);
  text-align:center;
  vertical-align:middle;
}

tbody tr:nth-child(even){
  background:#fafafa;
}

tbody tr:hover{
  background:#f1f1f1;
}

td img{
  width:85px;
  height:auto;
  border-radius:6px;
  display:block;
  margin:auto;
}

/* --- BOUTONS ACTIONS --- */

.btn-ghost{
  background:#fff;
  color:var(--green);
  border:1px solid var(--green);
  padding:6px 12px;
  border-radius:8px;
  font-weight:600;
}

.btn-warning{
  background:#ffbe3b;
  border:none;
  padding:6px 12px;
  border-radius:8px;
  color:#333;
  font-weight:600;
  margin-left:5px;
  display:inline-block;
}

.btn-warning:hover{
  background:#e39b00;
}

</style>

</head>
<body>

<h1>Onduleurs</h1>
<p><a href="index.php">← Retour</a></p>

<div class="card">
<h2>Ajouter un onduleur</h2>

<form method="post">
<div class="group"><label>Nom complet</label><input name="nom_complet"></div>
<div class="group"><label>Marque</label><input name="marque"></div>
<div class="group"><label>Référence</label><input name="reference"></div>
<div class="group"><label>Puissance (kVA)</label><input name="puissance_kva"></div>
<div class="group"><label>Type</label><input name="type"></div>
<div class="group"><label>Tension nominale</label><input name="tension_nominale"></div>
<div class="group"><label>Type tension</label><input name="type_tension"></div>
<div class="group"><label>Raccordement DC</label><input name="raccordement_dc"></div>
<div class="group"><label>Parafoudre DC</label><input name="para_dc"></div>
<div class="group"><label>Parafoudre AC</label><input name="para_ac"></div>
<div class="group"><label>AFCI</label><input name="afci"></div>
<div class="group"><label>Garantie</label><input name="garantie"></div>
<div class="group"><label>Extension garantie</label><input name="extension_garantie"></div>
<button class="btn" type="submit" name="add">Ajouter</button>

</form>
</div>

<div class="card">
<h2>Liste des onduleurs</h2>

<table>
<thead>
<tr>
<th>ID</th>
<th>Nom complet</th>
<th>Marque</th>
<th>Réf</th>
<th>kVA</th>
<th>Type</th>
<th>Tension nominale</th>
<th>Type tension</th>
<th>Raccordement DC</th>
<th>Parafoud. DC</th>
<th>Parafoud. AC</th>
<th>AFCI</th>
<th>Garantie</th>
<th>Ext. garantie</th>
<th></th>
</tr>
</thead>

<tbody>
<?php foreach ($rows as $r): ?>
<tr>
<td><?= $r['id'] ?></td>
<td><?= htmlspecialchars($r['nom_complet']) ?></td>
<td><?= htmlspecialchars($r['marque']) ?></td>
<td><?= htmlspecialchars($r['reference']) ?></td>
<td><?= $r['puissance_kva'] ?></td>
<td><?= htmlspecialchars($r['type']) ?></td>
<td><?= htmlspecialchars($r['tension_nominale']) ?></td>
<td><?= htmlspecialchars($r['type_tension']) ?></td>
<td><?= htmlspecialchars($r['raccordement_dc']) ?></td>
<td><?= htmlspecialchars($r['para_dc']) ?></td>
<td><?= htmlspecialchars($r['para_ac']) ?></td>
<td><?= htmlspecialchars($r['afci']) ?></td>
<td><?= htmlspecialchars($r['garantie']) ?></td>
<td><?= htmlspecialchars($r['extension_garantie']) ?></td>

<td><a class="btn-ghost" href="?delete=<?= $r['id'] ?>" onclick="return confirm('Supprimer ?');">Supprimer</a>
<a class="btn btn-warning" href="edit_onduleur.php?id=<?= $row['id'] ?>">Modifier</a></td>
</tr>
<?php endforeach; ?>
</tbody>

</table>
</div>

</body>
</html>
