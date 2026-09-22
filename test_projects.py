import base64
import json
from io import BytesIO
import os
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import app as app_module
from werkzeug.datastructures import FileStorage


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    @patch.object(app_module, "query")
    def test_list_projects_uses_sqlite_locally(self, query):
        query.return_value = [{"id": 1, "name": "Local", "form_data": "{}"}]
        with patch.object(app_module, "USE_SUPABASE", False):
            projects = app_module._list_projects()
        self.assertEqual(projects[0]["name"], "Local")
        query.assert_called_once_with("SELECT * FROM projects")

    @patch.object(app_module, "_sb_select")
    def test_list_projects_uses_supabase_in_production(self, select):
        select.return_value = [{"id": 2, "name": "Cloud", "form_data": {}}]
        with patch.object(app_module, "USE_SUPABASE", True):
            projects = app_module._list_projects()
        self.assertEqual(projects[0]["name"], "Cloud")
        select.assert_called_once_with("projects", order="updated_at.desc")

    @patch.object(app_module, "_sqlite_insert", return_value=7)
    def test_create_project_serializes_form_data_for_sqlite(self, insert):
        with patch.object(app_module, "USE_SUPABASE", False):
            response = self.client.post(
                "/projects/save",
                data={"nom_projet": "Projet local", "ville": "Lyon"},
            )
        self.assertEqual(response.status_code, 302)
        payload = insert.call_args.args[1]
        self.assertEqual(json.loads(payload["form_data"])["ville"], ["Lyon"])

    @patch.object(app_module, "_sb_insert", return_value=[{"id": 8}])
    def test_create_project_sends_json_to_supabase(self, insert):
        with patch.object(app_module, "USE_SUPABASE", True):
            response = self.client.post(
                "/projects/save",
                data={"nom_projet": "Projet cloud", "ville": "Paris"},
            )
        self.assertEqual(response.status_code, 302)
        payload = insert.call_args.args[1]
        self.assertEqual(payload["form_data"]["ville"], ["Paris"])

    @patch.object(app_module, "_sb_delete")
    @patch.object(app_module, "_get_project", return_value={"id": 9})
    def test_delete_project_uses_supabase(self, get_project, delete):
        with patch.object(app_module, "USE_SUPABASE", True):
            response = self.client.post("/projects/9/delete")
        self.assertEqual(response.status_code, 302)
        delete.assert_called_once_with("projects", {"id": "eq.9"})

    @patch.object(app_module, "_sqlite_delete")
    @patch.object(app_module, "_get_project", return_value={"id": 10})
    def test_delete_project_uses_sqlite_locally(self, get_project, delete):
        with patch.object(app_module, "USE_SUPABASE", False):
            response = self.client.post("/projects/10/delete")
        self.assertEqual(response.status_code, 302)
        delete.assert_called_once_with("projects", 10)

    @patch.object(app_module, "_get_project", return_value=None)
    def test_delete_missing_project_returns_404(self, get_project):
        response = self.client.post("/projects/999/delete")
        self.assertEqual(response.status_code, 404)
        get_project.assert_called_once_with(999)

    @patch.object(app_module, "_sqlite_insert", return_value=12)
    def test_blank_project_name_uses_default(self, insert):
        with patch.object(app_module, "USE_SUPABASE", False):
            response = self.client.post(
                "/projects/save",
                data={"nom_projet": "   "},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(insert.call_args.args[1]["name"], "Projet sans nom")

    @patch.object(app_module, "_sb_update")
    @patch.object(app_module, "_get_project", return_value={"id": 11})
    def test_update_project_uses_supabase(self, get_project, update):
        with patch.object(app_module, "USE_SUPABASE", True):
            response = self.client.post(
                "/projects/save",
                data={"project_id": "11", "nom_projet": "Projet modifié"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/projects/11", response.location)
        filters, payload = update.call_args.args[1:]
        self.assertEqual(filters, {"id": "eq.11"})
        self.assertEqual(payload["name"], "Projet modifié")
        get_project.assert_called_once_with(11)

    def test_update_rejects_invalid_project_id(self):
        response = self.client.post(
            "/projects/save",
            data={"project_id": "11-invalid", "nom_projet": "Projet"},
        )
        self.assertEqual(response.status_code, 400)

    @patch.object(app_module, "_get_project", return_value=None)
    def test_update_rejects_missing_project(self, get_project):
        response = self.client.post(
            "/projects/save",
            data={"project_id": "999", "nom_projet": "Projet"},
        )
        self.assertEqual(response.status_code, 404)
        get_project.assert_called_once_with(999)

    @patch.object(app_module, "_get_project", return_value=None)
    def test_missing_project_returns_404(self, get_project):
        response = self.client.get("/projects/404")
        self.assertEqual(response.status_code, 404)
        get_project.assert_called_once_with(404)

    @patch.object(app_module, "_list_projects", return_value=[])
    def test_home_page_renders(self, list_projects):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<!doctype html>", response.data)

    def test_sqlite_project_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "projects.db")
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL DEFAULT 'Projet sans nom',
                    form_data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()
            connection.close()

            with (
                patch.object(app_module, "USE_SUPABASE", False),
                patch.object(app_module, "DB_PATH", db_path),
            ):
                created = self.client.post(
                    "/projects/save",
                    data={"nom_projet": "Cycle SQLite", "ville": "Nantes"},
                )
                self.assertEqual(created.status_code, 302)
                project_id = int(created.location.rstrip("/").rsplit("/", 1)[1])

                home = self.client.get("/")
                self.assertEqual(home.status_code, 200)
                self.assertIn("Cycle SQLite".encode(), home.data)

                deleted = self.client.post(f"/projects/{project_id}/delete")
                self.assertEqual(deleted.status_code, 302)
                self.assertIsNone(app_module._get_project(project_id))

    def test_project_image_reference_rejects_path_traversal(self):
        self.assertEqual(
            app_module.normalize_project_image_ref("project-images/../../secret.png"),
            "",
        )
        self.assertEqual(
            app_module.normalize_project_image_ref("https://example.com/image.png"),
            "",
        )

    def test_project_image_reference_accepts_generated_local_name(self):
        reference = f"project-images/{'a' * 32}.png"
        self.assertEqual(app_module.normalize_project_image_ref(reference), reference)

    def test_project_photo_refs_reads_saved_json(self):
        reference = f"project-images/{'c' * 32}.jpg"
        project = {
            "form_data": json.dumps({"structure_model_photo_saved": [reference]})
        }
        self.assertEqual(app_module.project_photo_refs(project), {reference})

    def test_delete_project_image_removes_local_file(self):
        filename = f"{'d' * 32}.png"
        reference = f"project-images/{filename}"
        with tempfile.TemporaryDirectory() as temp_dir:
            image_dir = os.path.join(temp_dir, "static", "project-images")
            os.makedirs(image_dir)
            image_path = os.path.join(image_dir, filename)
            with open(image_path, "wb") as image_file:
                image_file.write(b"temporary")
            with (
                patch.object(app_module, "BASE_DIR", temp_dir),
                patch.object(app_module, "USE_SUPABASE", False),
            ):
                app_module.delete_project_image(reference)
            self.assertFalse(os.path.exists(image_path))

    @patch.object(app_module, "save_image")
    def test_project_image_rejects_non_image_extension(self, save_image):
        uploaded = FileStorage(stream=BytesIO(b"not an image"), filename="payload.exe")
        self.assertEqual(app_module.save_project_image(uploaded), "")
        save_image.assert_not_called()

    @patch.object(app_module, "save_image")
    def test_project_image_rejects_fake_png(self, save_image):
        uploaded = FileStorage(stream=BytesIO(b"not an image"), filename="payload.png")
        self.assertEqual(app_module.save_project_image(uploaded), "")
        save_image.assert_not_called()

    @patch.object(app_module, "save_image", return_value=f"{'b' * 32}.png")
    def test_project_image_accepts_valid_png(self, save_image):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        uploaded = FileStorage(stream=BytesIO(png), filename="photo.png")
        self.assertEqual(
            app_module.save_project_image(uploaded),
            f"project-images/{'b' * 32}.png",
        )
        save_image.assert_called_once_with(uploaded, "project-images")

    def test_generate_returns_a_rendered_docx(self):
        response = self.client.post(
            "/generate",
            data={
                "nom_projet": "Recette",
                "ville": "Paris",
                "adresse": "1 rue Test",
                "zones_json": "[]",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.mimetype,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn("CCTP_Recette.docx", response.headers["Content-Disposition"])

        document = BytesIO(response.data)
        self.assertTrue(zipfile.is_zipfile(document))
        document.seek(0)
        with zipfile.ZipFile(document) as archive:
            xml = " ".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in archive.namelist()
                if name.endswith(".xml")
            )
        self.assertNotIn("{{", xml)
        self.assertNotIn("{%", xml)


if __name__ == "__main__":
    unittest.main()
