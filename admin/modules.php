<?php
include "db.php";

// AJOUTER
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['add'])) {
    $stmt = $pdo->prepare("
        INSERT INTO modules
        (marque, reference, nom_complet, puissance_wc, type, cadre, backsheet, dimensions, longueur_cable, poids, garantie)
        VALUES (:marque, :reference, :nom_complet, :puissance_wc, :type, :cadre, :backsheet, :dimensions, :longueur_cable, :poids, :garantie)
    ");

    $stmt->execute([
        ":marque"         => $_POST['marque'] ?? '',
        ":reference"      => $_POST['reference'] ?? '',
        ":nom_complet"    => $_POST['nom_complet'] ?? '',
        ":puissance_wc"   => $_POST['puissance_wc'] ?? 0,
        ":type"           => $_POST['type'] ?? '',
        ":cadre"          => $_POST['cadre'] ?? '',
        ":backsheet"      => $_POST['backsheet'] ?? '',
        ":dimensions"     => $_POST['dimensions'] ?? '',
        ":longueur_cable" => $_POST['longueur_cable'] ?? '',
        ":poids"          => $_POST['poids'] ?? '',
        ":garantie"       => $_POST['garantie'] ?? ''
    ]);
}

// SUPPRIMER
if (isset($_GET['delete'])) {
    $stmt = $pdo->prepare("DELETE FROM modules WHERE id=?");
    $stmt->execute([$_GET['delete']]);
    header("Location: modules.php");
    exit;
}

// LISTE
$rows = $pdo->query("SELECT * FROM modules ORDER BY id DESC")->fetchAll(PDO::FETCH_ASSOC);
?>
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Modules photovoltaïques</title>

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

<h1>Panneaux photovoltaïques</h1>
<p><a href="index.php">← Retour</a></p>

<div class="card">
<h2>Ajouter un module PV</h2>

<form method="post">

<div class="group"><label>Marque</label><input name="marque"></div>
<div class="group"><label>Référence</label><input name="reference"></div>
<div class="group"><label>Nom complet</label><input name="nom_complet"></div>
<div class="group"><label>Puissance (Wc)</label><input name="puissance_wc"></div>
<div class="group"><label>Type</label><input name="type"></div>
<div class="group"><label>Cadre</label><input name="cadre"></div>
<div class="group"><label>Backsheet</label><input name="backsheet"></div>
<div class="group"><label>Dimensions</label><input name="dimensions"></div>
<div class="group"><label>Longueur câble</label><input name="longueur_cable"></div>
<div class="group"><label>Poids (kg)</label><input name="poids"></div>
<div class="group"><label>Garantie</label><input name="garantie"></div>

<button class="btn" type="submit" name="add">Ajouter</button>

</form>
</div>

<div class="card">
<h2>Liste des modules</h2>

<table>
<thead>
<tr>
<th>ID</th><th>Marque</th><th>Réf</th><th>Nom complet</th><th>Wc</th><th>Type</th>
<th>Cadre</th><th>Backsheet</th><th>Dimensions</th><th>Longueur câble</th>
<th>Poids</th><th>Garantie</th>
</tr>
</thead>

<tbody>
<?php foreach ($rows as $r): ?>
<tr>
<td><?= $r['id'] ?></td>
<td><?= htmlspecialchars($r['marque']) ?></td>
<td><?= htmlspecialchars($r['reference']) ?></td>
<td><?= htmlspecialchars($r['nom_complet']) ?></td>
<td><?= htmlspecialchars($r['puissance_wc']) ?></td>
<td><?= htmlspecialchars($r['type']) ?></td>
<td><?= htmlspecialchars($r['cadre']) ?></td>
<td><?= htmlspecialchars($r['backsheet']) ?></td>
<td><?= htmlspecialchars($r['dimensions']) ?></td>
<td><?= htmlspecialchars($r['longueur_cable']) ?></td>
<td><?= htmlspecialchars($r['poids']) ?></td>
<td><?= htmlspecialchars($r['garantie']) ?></td>

<td><a class="btn-ghost" href="?delete=<?= $r['id'] ?>" onclick="return confirm('Supprimer ?');">Supprimer</a>
<a class="btn btn-warning" href="edit_module.php?id=<?= $row['id'] ?>">Modifier</a></td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
</div>

</body>
</html>
