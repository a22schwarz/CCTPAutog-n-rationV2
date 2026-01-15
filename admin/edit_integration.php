<?php
require 'db.php';

$id = $_GET['id'] ?? 0;

$stmt = $pdo->prepare("SELECT * FROM integrations WHERE id = ?");
$stmt->execute([$id]);
$row = $stmt->fetch(PDO::FETCH_ASSOC);

if (!$row) { die("Intégration introuvable."); }

if ($_SERVER['REQUEST_METHOD'] === 'POST') {

    $cols = array_keys($row);
    unset($cols[array_search('id', $cols)]);

    $sql = "UPDATE integrations SET ";
    $sql .= implode("=?, ", $cols) . "=? WHERE id=?";

    $values = [];
    foreach ($cols as $c) $values[] = $_POST[$c];
    $values[] = $id;

    $pdo->prepare($sql)->execute($values);
    header("Location: integrations.php?updated=1");
    exit;
}
?>
<h1>Modifier système d'intégration</h1>
<form method="post">
<?php foreach ($row as $k=>$v): if ($k=='id') continue; ?>
    <label><?= $k ?></label><br>
    <input type="text" name="<?= $k ?>" value="<?= htmlspecialchars($v) ?>"><br><br>
<?php endforeach; ?>
<button type="submit">Enregistrer</button>
</form>
