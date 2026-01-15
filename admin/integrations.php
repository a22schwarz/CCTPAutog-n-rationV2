<?php
include "db.php";

$UPLOAD_DIR = "../static/si/";  // dossier où stocker les images

if (!is_dir($UPLOAD_DIR)) {
    mkdir($UPLOAD_DIR, 0777, true);
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['add'])) {

    // Gestion image
    $image_name = "";
    if (!empty($_FILES['image']['name'])) {
        $image_name = basename($_FILES['image']['name']);
        move_uploaded_file($_FILES['image']['tmp_name'], $UPLOAD_DIR . $image_name);
    }

    $stmt = $pdo->prepare("
INSERT INTO integrations
(marque, ref, fixation, Compat1, Compat2, Compat3, Compat4, Compat5, image, certification, garantie, carac1, carac2, carac3, carac4, carac5)
VALUES (:marque, :ref, :fixation, :Compat1, :Compat2, :Compat3, :Compat4, :Compat5, :image, :certif, :garantie, :carac1, :carac2, :carac3, :carac4, :carac5) ");

    $stmt->execute([
    ":marque"  => $_POST['marque'] ?? '',
    ":ref"     => $_POST['ref'] ?? '',
    ":fixation" => $_POST['fixation'] ?? '',
    ":image"   => $image_name,
    ":certif"  => $_POST['certification'] ?? '',
    ":garantie"=> $_POST['garantie'] ?? '',
    ":Compat1" => $_POST['Compat1'] ?? '',
    ":Compat2" => $_POST['Compat2'] ?? '',
    ":Compat3" => $_POST['Compat3'] ?? '',
    ":Compat4" => $_POST['Compat4'] ?? '',
    ":Compat5" => $_POST['Compat5'] ?? '',
    ":carac1" => $_POST['carac1'] ?? '',
    ":carac2" => $_POST['carac2'] ?? '',
    ":carac3" => $_POST['carac3'] ?? '',
    ":carac4" => $_POST['carac4'] ?? '',
    ":carac5" => $_POST['carac5'] ?? '',
]);


    // ID de l’intégration nouvellement créée
    $integration_id = $pdo->lastInsertId();

    /* -------- AJOUT DES CARACTÉRISTIQUES MULTIPLES -------- */
    if (!empty($_POST['carac']) && is_array($_POST['carac'])) {

        $stmtC = $pdo->prepare("
            INSERT INTO integrations_caracteristiques (integration_id, texte)
            VALUES (?, ?)
        ");

        foreach ($_POST['carac'] as $c) {
            $c = trim($c);
            if ($c !== "") {
                $stmtC->execute([$integration_id, $c]);
            }
        }
    }
}

if (isset($_GET['delete'])) {

    // supprime d'abord les caractéristiques liées
    $pdo->prepare("DELETE FROM integrations_caracteristiques WHERE integration_id=?")
        ->execute([$_GET['delete']]);

    // supprime ensuite l’intégration
    $pdo->prepare("DELETE FROM integrations WHERE id=?")
        ->execute([$_GET['delete']]);

    header("Location: integrations.php");
    exit;
}

$sql = "
SELECT i.*,
       GROUP_CONCAT(c.texte, '||') AS carac_concat
FROM integrations i
LEFT JOIN integrations_caracteristiques c
       ON c.integration_id = i.id
GROUP BY i.id
ORDER BY i.id DESC
";

$rows = $pdo->query($sql)->fetchAll(PDO::FETCH_ASSOC);
?>
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Systèmes d'intégration</title>

    <!-- Police + ton style.css -->
    <link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap" rel="stylesheet">
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

<main class="container">

    <header>
        <div>
            <h1>Systèmes d’intégration</h1>
<p><a href="index.php">← Retour</a></p>
        </div>
    </header>

    <section class="card">
        <h3>Ajouter un système d’intégration</h3>

        <form method="post" enctype="multipart/form-data" class="grid-3" style="gap:20px;">

            <div class="group">
                <label>Marque</label>
                <input name="marque" required>
            </div>

            <div class="group">
                <label>Référence</label>
                <input name="ref">
            </div>

            <div class="group">
                <label>Fixation</label>
                <input name="fixation">
            </div>

            <div class="group">
                <label>Compatibilité 1</label>
                <input name="Compat1">
            </div>

            <div class="group">
                <label>Compatibilité 2</label>
                <input name="Compat2">
            </div>

            <div class="group">
                <label>Compatibilité 3</label>
                <input name="Compat3">
            </div>

            <div class="group">
                <label>Compatibilité 4</label>
                <input name="Compat4">
            </div>

            <div class="group">
                <label>Compatibilité 5</label>
                <input name="Compat5">
            </div>

            <div class="group">
                <label>Caractéristique 1</label>
                <input name="carac1">
            </div>

            <div class="group">
                <label>Caractéristique 2</label>
                <input name="carac2">
            </div>

            <div class="group">
                <label>Caractéristique 3</label>
                <input name="carac3">
            </div>

            <div class="group">
                <label>Caractéristique 4</label>
                <input name="carac4">
            </div>

            <div class="group">
                <label>Caractéristique 5</label>
                <input name="carac5">
            </div>

            <div class="group" style="grid-column:1/-1">
                <label>Image</label>
                <input type="file" name="image" accept="image/*">
            </div>

            <div class="group">
                <label>Certification</label>
                <input name="certification">
            </div>

            <div class="group">
                <label>Garantie</label>
                <input name="garantie">
            </div>

            <div style="grid-column:1/-1; text-align:right;">
                <button type="submit" name="add" class="btn">Ajouter</button>
            </div>

        </form>
    </section>

    <section class="card">
        <h3>Liste des systèmes existants</h3>

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Marque</th>
                        <th>Réf</th>
                        <th>Fixation</th>
                        <th>Compatibilité 1</th>
                        <th>Compatibilité 2</th>
                        <th>Compatibilité 3</th>
                        <th>Compatibilité 4</th>
                        <th>Compatibilité 5</th>
                        <th>Caractéristique 1</th>
                        <th>Caractéristique 2</th>
                        <th>Caractéristique 3</th>
                        <th>Caractéristique 4</th>
                        <th>Caractéristique 5</th>
                        <th>Image</th>
                        <th>Certif</th>
                        <th>Garantie</th>
                        <th></th>
                    </tr>
                </thead>

                <tbody>
                <?php foreach ($rows as $r): ?>
                    <tr>
                        <td><?= $r['id'] ?></td>
                        <td><?= htmlspecialchars($r['marque']) ?></td>
                        <td><?= htmlspecialchars($r['ref']) ?></td>
                        <td><?= htmlspecialchars($r['fixation']) ?></td>
                        <td><?= htmlspecialchars($r['Compat1']) ?></td>
                        <td><?= htmlspecialchars($r['Compat2']) ?></td>
                        <td><?= htmlspecialchars($r['Compat3']) ?></td>
                        <td><?= htmlspecialchars($r['Compat4']) ?></td>
                        <td><?= htmlspecialchars($r['Compat5']) ?></td>
                        <td><?= htmlspecialchars($r['carac1']) ?></td>
                        <td><?= htmlspecialchars($r['carac2']) ?></td>
                        <td><?= htmlspecialchars($r['carac3']) ?></td>
                        <td><?= htmlspecialchars($r['carac4']) ?></td>
                        <td><?= htmlspecialchars($r['carac5']) ?></td>

                        <td>
                            <?php if ($r['image']): ?>
                                <img src="../static/si/<?= $r['image'] ?>" style="width:70px; border-radius:8px;">
                            <?php endif; ?>
                        </td>

                        <td><?= htmlspecialchars($r['certification']) ?></td>
                        <td><?= htmlspecialchars($r['garantie']) ?></td>

                        <td>
                            <a class="btn btn-ghost" href="?delete=<?= $r['id'] ?>" onclick="return confirm('Supprimer ?')">Suppr</a>
                            <a class="btn btn-warning" href="edit_integration.php?id=<?= $r['id'] ?>">Modifier</a>

                        </td>
                    </tr>
                <?php endforeach; ?>
                </tbody>

            </table>
        </div>
    </section>

</main>

</body>
</html>

