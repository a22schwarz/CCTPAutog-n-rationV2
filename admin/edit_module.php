<?php
require 'db.php';

$id = $_GET['id'] ?? 0;

// Charger le module
$stmt = $pdo->prepare("SELECT * FROM modules WHERE id = ?");
$stmt->execute([$id]);
$module = $stmt->fetch(PDO::FETCH_ASSOC);

if (!$module) { die("Module introuvable."); }

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $sql = "UPDATE modules SET
        marque=?, reference=?, nom_complet=?, puissance_wc=?, type=?, cadre=?, backsheet=?, dimensions=?, longueur_cable=?, poids=?, garantie=?, certif_carbone=?, etn=?
        WHERE id=?";
    $pdo->prepare($sql)->execute([
        $_POST['marque'], $_POST['reference'], $_POST['nom_complet'],
        $_POST['puissance_wc'], $_POST['type'], $_POST['cadre'],
        $_POST['backsheet'], $_POST['dimensions'], $_POST['longueur_cable'],
        $_POST['poids'], $_POST['garantie'], $_POST['certif_carbone'],
        $_POST['etn'], $id
    ]);
    header("Location: modules.php?updated=1");
    exit;
}
?>
<h1>Modifier module</h1>
<form method="post">
<?php foreach ($module as $k=>$v): if ($k=='id') continue; ?>
    <label><?= $k ?> :</label><br>
    <input type="text" name="<?= $k ?>" value="<?= htmlspecialchars($v) ?>"><br><br>
<?php endforeach; ?>
<button type="submit">Enregistrer</button>
</form>
