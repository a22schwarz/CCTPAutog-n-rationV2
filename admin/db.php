<?php
try {
    // chemin absolu vers la database à la racine du projet
    $db_file = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'database.db';

    if (!file_exists($db_file)) {
        throw new Exception("database.db introuvable : " . $db_file);
    }

    // ON UTILISE $pdo (comme dans modules.php / onduleurs.php / integrations.php)
    $pdo = new PDO('sqlite:' . $db_file);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

} catch (Exception $e) {
    die("Erreur SQLite : " . $e->getMessage());
}
