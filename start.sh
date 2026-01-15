set -e

# Si le volume est monté et que la DB n'existe pas encore dessus,
# on copie la DB "de base" du projet.
if [ -n "$DB_PATH" ] && echo "$DB_PATH" | grep -q "^/data/"; then
  if [ ! -f "$DB_PATH" ]; then
    echo "DB absente sur volume -> copie de database.db vers $DB_PATH"
    cp /app/database.db "$DB_PATH"
  else
    echo "DB déjà présente sur volume -> ok"
  fi
fi

exec gunicorn -b 0.0.0.0:8080 wsgi:app
